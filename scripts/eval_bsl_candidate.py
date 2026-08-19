#!/usr/bin/env python3
"""Статически оценивает BSL-кандидаты и управляет экономным Best-of-N=2."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from omvl_llm_runtime import sanitize_bsl_output


SYNTAX_PENALTY = 1000
TEMPDB_PENALTY = 500
LINTER_PENALTY = 300
METADATA_PENALTY = 100
TEMP_TABLE_RE = re.compile(r"\bПОМЕСТИТЬ\s+(ВТ[А-Яа-яA-Za-z0-9_]*)\b", re.IGNORECASE)
METADATA_RE = re.compile(
    r"\b(Справочники|Документы|РегистрыСведений|РегистрыНакопления|"
    r"ПланыВидовХарактеристик|Перечисления)\.([А-Яа-яA-Za-z_][А-Яа-яA-Za-z0-9_]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SyntaxDiagnostic:
    """Короткий итог синтаксического диагностика без raw-вывода компилятора."""

    status: str
    command: tuple[str, ...]
    detail: str


def _compact_detail(value: str, limit: int = 400) -> str:
    """Сохраняет одну безопасную диагностическую строку ограниченной длины."""
    compact = " ".join(value.split())
    return compact[:limit]


def run_syntax_diagnostic(
    candidate: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SyntaxDiagnostic:
    """Запускает OneScript -check; отсутствие инструмента является явным STOP."""
    oscript = shutil.which("oscript")
    if oscript is None:
        return SyntaxDiagnostic("UNAVAILABLE", (), "oscript не найден в PATH")
    command = (oscript, "-check", str(candidate))
    try:
        result = runner(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SyntaxDiagnostic("UNAVAILABLE", command, "превышен лимит синтаксической проверки")
    except OSError as exc:
        return SyntaxDiagnostic("UNAVAILABLE", command, _compact_detail(str(exc)))
    if result.returncode == 0:
        return SyntaxDiagnostic("PASS", command, "OneScript -check завершен успешно")
    detail = _compact_detail(result.stderr or result.stdout or "OneScript -check завершился с ошибкой")
    return SyntaxDiagnostic("FAIL", command, detail)


def _tempdb_leaks(text: str) -> list[str]:
    """Ищет временные таблицы без явного уничтожения в том же кандидате."""
    names = sorted({match.group(1) for match in TEMP_TABLE_RE.finditer(text)}, key=str.casefold)
    leaks: list[str] = []
    for name in names:
        destroy = re.compile(rf"\bУНИЧТОЖИТЬ\s+{re.escape(name)}\b", re.IGNORECASE)
        if destroy.search(text) is None:
            leaks.append(name)
    return leaks


def _metadata_references(text: str) -> set[str]:
    """Извлекает только статические ссылки на метаданные, видимые в BSL-тексте."""
    return {
        f"{match.group(1)}.{match.group(2)}".casefold()
        for match in METADATA_RE.finditer(text)
    }


def evaluate_candidate(
    candidate: Path,
    *,
    metadata_anchors: Sequence[str] = (),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Возвращает детерминированную стоимость кандидата и причины без LLM-вызовов."""
    if not candidate.is_file():
        return {
            "schema_version": "1.0",
            "candidate": str(candidate),
            "cost": SYNTAX_PENALTY,
            "accepted": False,
            "status": "STOP_DIAGNOSTICS_UNAVAILABLE",
            "issues": ["Файл BSL-кандидата не найден"],
        }
    text = candidate.read_text(encoding="utf-8", errors="replace")
    syntax = run_syntax_diagnostic(candidate, runner=runner)
    issues: list[dict[str, Any]] = []
    cost = 0
    if syntax.status == "UNAVAILABLE":
        return {
            "schema_version": "1.0",
            "candidate": str(candidate),
            "cost": None,
            "accepted": False,
            "status": "STOP_DIAGNOSTICS_UNAVAILABLE",
            "issues": [{"kind": "diagnostics_unavailable", "detail": syntax.detail}],
            "syntax": {"status": syntax.status, "command": list(syntax.command)},
        }
    if syntax.status != "PASS":
        cost += SYNTAX_PENALTY
        issues.append({"kind": "syntax", "penalty": SYNTAX_PENALTY, "detail": syntax.detail})
    leaks = _tempdb_leaks(text)
    if leaks:
        cost += TEMPDB_PENALTY
        issues.append({"kind": "tempdb_leak", "penalty": TEMPDB_PENALTY, "tables": leaks})
    valid, lint_errors = sanitize_bsl_output(text)
    if not valid:
        cost += LINTER_PENALTY
        issues.append({"kind": "bsl_linter", "penalty": LINTER_PENALTY, "errors": lint_errors})
    anchors = {anchor.casefold() for anchor in metadata_anchors if anchor.strip()}
    unanchored = sorted(_metadata_references(text) - anchors)
    if unanchored:
        cost += METADATA_PENALTY
        issues.append(
            {"kind": "unanchored_metadata", "penalty": METADATA_PENALTY, "references": unanchored}
        )
    return {
        "schema_version": "1.0",
        "candidate": str(candidate),
        "cost": cost,
        "accepted": cost == 0,
        "status": "PASS" if cost == 0 else "REJECTED",
        "issues": issues,
        "syntax": {"status": syntax.status, "command": list(syntax.command)},
    }


def adaptive_decision(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Применяет ровно один fast-path либо строго две целевые вариации."""
    if not results:
        raise ValueError("Не передан Candidate 1")
    first = results[0]
    if first["status"] == "STOP_DIAGNOSTICS_UNAVAILABLE":
        return {"status": "STOP_DIAGNOSTICS_UNAVAILABLE", "selected": None, "llm_calls": 0}
    if first["cost"] == 0:
        return {"status": "ACCEPTED_FAST_PATH", "selected": first["candidate"], "llm_calls": 0}
    if len(results) == 1:
        return {
            "status": "REQUEST_EXACTLY_TWO_TARGETED_VARIATIONS",
            "selected": None,
            "llm_calls": 2,
            "issues": first["issues"],
        }
    if len(results) != 3:
        raise ValueError("Fallback-path допускает ровно два дополнительных кандидата")
    fallbacks = results[1:]
    if any(item["status"] == "STOP_DIAGNOSTICS_UNAVAILABLE" for item in fallbacks):
        return {"status": "STOP_DIAGNOSTICS_UNAVAILABLE", "selected": None, "llm_calls": 0}
    selected = min(fallbacks, key=lambda item: int(item["cost"]))
    return {
        "status": "SELECTED_FALLBACK" if selected["cost"] == 0 else "STOP_NO_SAFE_CANDIDATE",
        "selected": selected["candidate"] if selected["cost"] == 0 else None,
        "llm_calls": 2,
        "best_cost": selected["cost"],
    }


def parse_args() -> argparse.Namespace:
    """Разбирает ограниченный CLI-контракт оценщика."""
    parser = argparse.ArgumentParser(description="Статическая оценка BSL-кандидатов")
    parser.add_argument("candidate", type=Path, help="Candidate 1")
    parser.add_argument(
        "--fallback",
        type=Path,
        nargs="*",
        default=(),
        help="Ровно два кандидата fallback-path после целевых исправлений",
    )
    parser.add_argument(
        "--metadata-anchor",
        action="append",
        default=[],
        help="Доказанная ссылка на метаданные вида Справочники.Контрагенты",
    )
    return parser.parse_args()


def main() -> int:
    """Печатает компактный JSON-контракт для оркестратора и возвращает его статус."""
    args = parse_args()
    if len(args.fallback) not in {0, 2}:
        print("FAIL: --fallback принимает ровно два файла", file=sys.stderr)
        return 2
    candidates = [args.candidate, *args.fallback]
    results = [evaluate_candidate(path, metadata_anchors=args.metadata_anchor) for path in candidates]
    decision = adaptive_decision(results)
    print(json.dumps({"decision": decision, "results": results}, ensure_ascii=False, indent=2))
    return 0 if decision["status"] in {"ACCEPTED_FAST_PATH", "SELECTED_FALLBACK"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
