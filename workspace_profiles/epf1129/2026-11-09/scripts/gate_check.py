#!/usr/bin/env python3
"""Проверяет локальный реестр приемочных ворот без shell-интерпретации."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "GATES.md"
ALLOWED_RUNNERS = frozenset({"python3", "pytest", "oscript", "git"})
SAFE_GIT_SUBCOMMANDS = frozenset({"diff", "status", "rev-parse", "check-ignore"})
MAX_OUTPUT_BYTES = 16_384
DEFAULT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Gate:
    """Одна декларативная проверка из GATES.md."""

    gate_id: str
    command: str
    expected_exit: int | None
    expected_regex: str | None
    evidence_path: Path


class GateError(ValueError):
    """Некорректный или небезопасный контракт ворот."""


def _safe_evidence_path(value: str, root: Path) -> Path:
    candidate = Path(value.strip())
    if candidate.is_absolute() or ".." in candidate.parts:
        raise GateError("EVIDENCE должен быть относительным путем без '..'")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(resolved_root / "temp" / "gates"):
        raise GateError("EVIDENCE должен располагаться внутри temp/gates/")
    return resolved


def _parse_expectation(raw: str) -> tuple[int | None, str | None]:
    exit_code: int | None = None
    pattern: str | None = None
    for part in (item.strip() for item in raw.split(";")):
        if not part:
            continue
        if part.startswith("exitcode="):
            value = part.removeprefix("exitcode=").strip()
            try:
                exit_code = int(value)
            except ValueError as exc:
                raise GateError("EXPECT exitcode должен быть целым числом") from exc
        elif part.startswith("regex="):
            pattern = part.removeprefix("regex=").strip()
            if not pattern:
                raise GateError("EXPECT regex не может быть пустым")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise GateError(f"EXPECT содержит некорректный regex: {exc}") from exc
        else:
            raise GateError("EXPECT допускает только exitcode=<n> и regex=<паттерн>")
    if exit_code is None and pattern is None:
        raise GateError("EXPECT должен содержать exitcode или regex")
    return exit_code, pattern


def parse_ledger(path: Path, *, root: Path = ROOT) -> list[Gate]:
    """Разбирает компактный Markdown-реестр без исполнения его содержимого."""
    if not path.is_file():
        raise GateError(f"Не найден реестр ворот: {path}")
    gates: list[Gate] = []
    current_id = ""
    fields: dict[str, str] = {}

    def flush() -> None:
        nonlocal fields
        if not current_id:
            return
        required = {"CHECK", "EXPECT", "EVIDENCE"}
        missing = required - set(fields)
        if missing:
            raise GateError(f"Ворота {current_id}: нет поля {', '.join(sorted(missing))}")
        expected_exit, expected_regex = _parse_expectation(fields["EXPECT"])
        gates.append(
            Gate(
                gate_id=current_id,
                command=fields["CHECK"].strip(),
                expected_exit=expected_exit,
                expected_regex=expected_regex,
                evidence_path=_safe_evidence_path(fields["EVIDENCE"], root),
            )
        )
        fields = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.fullmatch(r"##\s+([A-Za-z0-9][A-Za-z0-9._-]*)\s*", line.strip())
        if heading:
            flush()
            current_id = heading.group(1)
            continue
        field = re.fullmatch(r"(CHECK|EXPECT|EVIDENCE):\s*(.+)", line.strip())
        if field and current_id:
            key, value = field.groups()
            if key in fields:
                raise GateError(f"Ворота {current_id}: поле {key} указано повторно")
            fields[key] = value
    flush()
    if not gates:
        raise GateError("Реестр не содержит ворот")
    ids = [gate.gate_id for gate in gates]
    if len(ids) != len(set(ids)):
        raise GateError("Реестр содержит повторяющиеся идентификаторы ворот")
    return gates


def _command_argv(command: str) -> list[str]:
    if any(token in command for token in (";", "|", "&", "`", "$(", ">", "<", "\n", "\r")):
        raise GateError("CHECK содержит shell-метасимвол или перевод строки")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise GateError(f"CHECK невозможно разобрать: {exc}") from exc
    if not argv:
        raise GateError("CHECK не может быть пустым")
    runner = Path(argv[0]).name
    if runner not in ALLOWED_RUNNERS:
        raise GateError(f"Runner '{runner}' не входит в разрешенный whitelist")
    if runner == "git" and (len(argv) < 2 or argv[1] not in SAFE_GIT_SUBCOMMANDS):
        raise GateError("Для git разрешены только read-only подкоманды")
    if runner == "python3":
        argv[0] = sys.executable
    return argv


def _fingerprint(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8", errors="replace")
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}


def _load_previous(evidence_path: Path, gate: Gate) -> bool:
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("status") == "PASS"
        and payload.get("gate_id") == gate.gate_id
        and payload.get("command_sha256") == hashlib.sha256(gate.command.encode("utf-8")).hexdigest()
    )


def _write_evidence(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_gate(gate: Gate, *, root: Path = ROOT, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Выполняет только заранее ограниченную команду и сохраняет хеш доказательства."""
    try:
        argv = _command_argv(gate.command)
    except GateError as exc:
        return False, str(exc)
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            shell=False,
        )
        output = (completed.stdout or "")[:MAX_OUTPUT_BYTES]
        exit_ok = gate.expected_exit is None or completed.returncode == gate.expected_exit
        regex_ok = gate.expected_regex is None or bool(re.search(gate.expected_regex, output, re.MULTILINE))
        passed = exit_ok and regex_ok
        detail = "PASS" if passed else f"FAIL exit={completed.returncode}; regex={regex_ok}"
        evidence = {
            "gate_id": gate.gate_id,
            "status": "PASS" if passed else "FAIL",
            "command_sha256": hashlib.sha256(gate.command.encode("utf-8")).hexdigest(),
            "returncode": completed.returncode,
            "expected_exit": gate.expected_exit,
            "regex_matched": regex_ok,
            "output": _fingerprint(output),
        }
    except subprocess.TimeoutExpired:
        passed, detail = False, f"FAIL timeout={timeout}s"
        evidence = {"gate_id": gate.gate_id, "status": "FAIL", "timeout_seconds": timeout}
    _write_evidence(gate.evidence_path, evidence)
    return passed, detail


def run_ledger(path: Path, *, root: Path = ROOT, reverify: bool = False, evidence_run: str | None = None) -> int:
    """Возвращает 1, пока хотя бы одни ворота не подтверждены заново."""
    try:
        gates = parse_ledger(path, root=root)
        if evidence_run is not None:
            if not reverify or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", evidence_run):
                raise GateError("Новый набор доказательств требует --reverify и безопасное имя версии")
            destination = root / "temp" / "gates" / evidence_run
            if destination.exists() or destination.is_symlink():
                raise GateError("Набор доказательств уже существует; выберите новую версию")
            if len({gate.evidence_path.name for gate in gates}) != len(gates):
                raise GateError("Имена файлов доказательств должны быть уникальными")
            destination.mkdir(parents=True, exist_ok=False)
            gates = [replace(gate, evidence_path=destination / gate.evidence_path.name) for gate in gates]
    except GateError as exc:
        print(f"FAIL gate-check: {exc}")
        return 1
    failures = 0
    for gate in gates:
        if not reverify and _load_previous(gate.evidence_path, gate):
            print(f"SKIP {gate.gate_id}: ранее подтверждено; используйте --reverify")
            continue
        passed, detail = run_gate(gate, root=root)
        print(f"{gate.gate_id}: {detail}")
        failures += int(not passed)
    if failures:
        print(f"STOP gate-check: не пройдено ворот: {failures}")
        return 1
    print("PASS gate-check: все объявленные ворота подтверждены")
    return 0


def self_test() -> int:
    """Проверяет парсер, whitelist и фактическую запись доказательства в изоляции."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ledger = root / "GATES.md"
        ledger.write_text(
            "# Реестр\n\n## G1\nCHECK: python3 -c \"print('READY')\"\n"
            "EXPECT: exitcode=0; regex=^READY$\nEVIDENCE: temp/gates/g1.json\n",
            encoding="utf-8",
        )
        if run_ledger(ledger, root=root, reverify=True) != 0:
            return 1
        try:
            _command_argv("bash -c true")
        except GateError:
            print("PASS gate-check self-test")
            return 0
    print("FAIL gate-check self-test")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed проверка GATES.md")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--reverify", action="store_true", help="Перепроверить также ранее PASS-ворота")
    parser.add_argument("--self-test", action="store_true", help="Запустить изолированную самопроверку")
    parser.add_argument("--evidence-run", help="Перепроверить в новом temp/gates/<version>/, сохранив исходные доказательства")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    return run_ledger(args.ledger, reverify=args.reverify, evidence_run=args.evidence_run)


if __name__ == "__main__":
    raise SystemExit(main())
