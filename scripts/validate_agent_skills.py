#!/usr/bin/env python3
"""Проверяет минимальный agentskills.io-контракт локальных инфраструктурных навыков."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("grill-me", "unlazy", "task-observer")
NAME_RE = re.compile(r"^name:\s*([a-z0-9]+(?:-[a-z0-9]+)*)\s*$", re.MULTILINE)
DESCRIPTION_RE = re.compile(r'^description:\s*"(.+)"\s*$', re.MULTILINE)


def validate_skill(path: Path) -> list[str]:
    """Возвращает список нарушений компактного манифеста одного навыка."""
    manifest = path / "SKILL.md"
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return ["отсутствует SKILL.md"]
    if not text.startswith("---\n"):
        return ["frontmatter должен начинаться с ---"]
    frontmatter_end = text.find("\n---", 4)
    if frontmatter_end < 0:
        return ["frontmatter не закрыт"]
    frontmatter = text[4:frontmatter_end]
    name = NAME_RE.search(frontmatter)
    description = DESCRIPTION_RE.search(frontmatter)
    errors: list[str] = []
    if name is None or name.group(1) != path.name:
        errors.append("name отсутствует, не kebab-case или не равен имени каталога")
    if description is None:
        errors.append("description отсутствует")
    elif len(description.group(1)) >= 1024:
        errors.append("description должен быть короче 1024 символов")
    elif "Триггер:" not in description.group(1) or "Антитриггер:" not in description.group(1):
        errors.append("description должен содержать Триггер и Антитриггер")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    base = args.root.resolve() / ".agents" / "skills"
    failed = False
    for name in SKILLS:
        errors = validate_skill(base / name)
        if errors:
            failed = True
            print(f"FAIL {name}: {'; '.join(errors)}")
        else:
            print(f"PASS {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
