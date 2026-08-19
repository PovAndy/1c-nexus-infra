#!/usr/bin/env python3
"""Проверяет неизменяемый статический prompt-контракт reasoning-моделей."""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path


ROOT = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
CONSUMERS = (".clinerules", ".cursorrules", "AGENTS.md", "system_prompt.md")
BEGIN = "<!-- OMVL_STATIC_PREFIX_V1:BEGIN -->"
END = "<!-- OMVL_STATIC_PREFIX_V1:END -->"
REQUIRED_TAGS = (
    "<environment_context>",
    "<agent_role>",
    "<hard_constraints>",
    "<definition_of_done>",
    "<task_input>",
    "<cache_contract>",
)
FORBIDDEN_COT = (
    "think step-by-step",
    "think step by step",
    "reason through this",
    "reflect on your answer",
    "думай пошагово",
    "размышляй пошагово",
    "покажи цепочку рассуждений",
    "<scratchpad>",
)
MIN_LEXICAL_UNITS = 1100
MIN_UTF8_BYTES = 15000


def static_prefix(path: Path) -> str:
    """Возвращает включительно маркированный неизменный префикс файла."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith(BEGIN):
        raise ValueError(f"{path.name}: префикс должен начинаться с маркера BEGIN")
    if content.count(BEGIN) != 1 or content.count(END) != 1:
        raise ValueError(f"{path.name}: маркеры версии должны встречаться ровно по одному разу")
    end_at = content.index(END) + len(END)
    return content[:end_at]


def lexical_units(value: str) -> int:
    """Считает консервативную локальную метрику наполненности без SDK-токенизатора."""
    return len(re.findall(r"[\wА-Яа-яЁё]+", value, flags=re.UNICODE))


def validate() -> tuple[str, int, int]:
    """Проверяет идентичность префикса, структуру и запрет CoT-триггеров."""
    prefixes = {name: static_prefix(ROOT / name) for name in CONSUMERS}
    canonical = prefixes[CONSUMERS[0]]
    mismatches = [name for name, prefix in prefixes.items() if prefix != canonical]
    if mismatches:
        raise ValueError("Статический префикс расходится: " + ", ".join(mismatches))
    missing = [tag for tag in REQUIRED_TAGS if tag not in canonical]
    if missing:
        raise ValueError("Отсутствуют обязательные XML-теги: " + ", ".join(missing))
    folded = canonical.casefold()
    present_cot = [pattern for pattern in FORBIDDEN_COT if pattern.casefold() in folded]
    if present_cot:
        raise ValueError("Обнаружены запрещенные CoT-триггеры: " + ", ".join(present_cot))
    units = lexical_units(canonical)
    size = len(canonical.encode("utf-8"))
    if units < MIN_LEXICAL_UNITS or size < MIN_UTF8_BYTES:
        raise ValueError(
            "Недостаточный запас статического префикса: "
            f"лексических единиц={units}, байт UTF-8={size}"
        )
    system_prompt = (ROOT / "system_prompt.md").read_text(encoding="utf-8")
    if "<developer_message_convention>" not in system_prompt:
        raise ValueError("system_prompt.md не фиксирует developer-конвенцию")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), units, size


def main() -> int:
    try:
        digest, units, size = validate()
    except (OSError, ValueError) as exc:
        print(f"FAIL prompt-contract: {exc}")
        return 1
    print(
        "PASS prompt-contract: "
        f"sha256={digest}; lexical_units={units}; utf8_bytes={size}; consumers={len(CONSUMERS)}"
    )
    print(
        "Примечание: точный cache hit и число provider-токенов подтверждаются только "
        "телеметрией выбранного API; локально зафиксирована стабильность префикса и запас объема."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
