#!/usr/bin/env python3
"""Fail-closed проверка безопасной схемы локального .env без вывода секретов."""

from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / ".env.openrouter.local"
TARGETS = ("postgres2", "postgres8", "postgres9", "postgres4", "postgres3", "postgres7", "zagruzka2")
OPTIONAL_TARGETS = ("base02",)
ASSIGNMENT_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\Z")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        return value[1:-1]
    return value


def load_assignments(path: Path) -> tuple[dict[str, str], dict[str, list[int]], list[str]]:
    values: dict[str, str] = {}
    lines_by_name: dict[str, list[int]] = {}
    errors: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ASSIGNMENT_RE.fullmatch(raw)
        if not match:
            errors.append(f"malformed assignment at line {number}")
            continue
        name, value = match.groups()
        values[name] = _unquote(value)
        lines_by_name.setdefault(name, []).append(number)
    return values, lines_by_name, errors


def configured_targets(values: dict[str, str]) -> tuple[str, ...]:
    """Проверяет дополнительный контур при наличии его слота или выборе target."""
    active = values.get("OMVL_1C_ACTIVE_TARGET")
    optional = tuple(
        target for target in OPTIONAL_TARGETS
        if active == target or any(
            name.endswith(f"_{target.upper()}") for name in values
        )
    )
    return TARGETS + optional


def validate(path: Path) -> list[str]:
    if not path.is_file():
        return ["missing .env file"]
    mode = stat.S_IMODE(path.stat().st_mode)
    errors: list[str] = []
    if mode & 0o077:
        errors.append(".env permissions permit group or other access")

    values, lines_by_name, parse_errors = load_assignments(path)
    errors.extend(parse_errors)
    for name, lines in sorted(lines_by_name.items()):
        if len(lines) > 1:
            errors.append(f"duplicate variable {name} at lines {','.join(map(str, lines))}")

    active = values.get("OMVL_1C_ACTIVE_TARGET")
    for name in ("RSVDATA_TARGET", "LDS_1C_BRIDGE_TARGET"):
        if values.get(name) != active:
            errors.append(f"target mismatch: {name}")
    targets = configured_targets(values)
    if active not in targets:
        errors.append("active target is missing or unsupported")
    if values.get("LDS_1C_BRIDGE_READ_ONLY") != "1":
        errors.append("global bridge read-only guard is not enabled")

    for target in targets:
        for prefix in ("LDS_1C_BRIDGE_URL_", "LDS_1C_BRIDGE_URL_IP_"):
            name = f"{prefix}{target.upper()}"
            value = values.get(name)
            if not value:
                errors.append(f"missing {name}")
                continue
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"invalid URL in {name}")
            elif f"/{target}/" not in parsed.path:
                errors.append(f"target path mismatch in {name}")
        if values.get(f"LDS_1C_BRIDGE_READ_ONLY_{target.upper()}") != "1":
            errors.append(f"read-only guard is not enabled for {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка безопасного контракта .env без вывода секретов")
    parser.add_argument("--path", type=Path, default=DEFAULT_ENV)
    args = parser.parse_args()
    errors = validate(args.path)
    if errors:
        print("ENV_CONTRACT: FAIL")
        for error in errors:
            print(f"ENV_CONTRACT_ERROR: {error}")
        return 1
    values, _, _ = load_assignments(args.path)
    print(f"ENV_CONTRACT: PASS; targets={len(configured_targets(values))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
