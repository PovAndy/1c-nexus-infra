#!/usr/bin/env python3
"""Проверяет, что runtime-артефакты не попадают в индекс Git."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


КОРЕНЬ_ПРОЕКТА = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
ЗАПРЕЩЕННЫЕ_ПРЕФИКСЫ = (
    ".venv/",
    ".venv-",
    ".code-index/",
    "docs/.code-index/",
)


def выполнить(команда: list[str]) -> subprocess.CompletedProcess[str]:
    """Запускает короткую Git-команду в корне проекта."""
    return subprocess.run(
        команда,
        cwd=КОРЕНЬ_ПРОЕКТА,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> int:
    """Проверяет только индекс и не изменяет рабочее дерево."""
    result = выполнить(["git", "ls-files"])
    if result.returncode != 0:
        print((result.stderr or result.stdout).strip(), file=sys.stderr)
        return 2
    tracked = [
        path
        for path in result.stdout.splitlines()
        if path.startswith(ЗАПРЕЩЕННЫЕ_ПРЕФИКСЫ)
    ]
    if tracked:
        print(f"HYGIENE_FAIL tracked_runtime={len(tracked)}", file=sys.stderr)
        for path in tracked[:10]:
            print(f"HYGIENE_PATH {path}", file=sys.stderr)
        return 1
    print("HYGIENE_OK tracked_runtime=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
