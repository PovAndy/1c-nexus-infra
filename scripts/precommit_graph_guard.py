#!/usr/bin/env python3
"""Быстрая fail-closed проверка состояния Graph V2 для Git pre-commit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, object] | None:
    """Возвращает небольшой JSON-объект либо отсутствие корректного состояния."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validate(root: Path, lock_state: str) -> tuple[bool, str]:
    """Проверяет stat-связь graph/state без обхода исходников и ожидания lock."""
    runtime = root / "temp"
    state = load_json(runtime / "workspace_graph_v2.state.json")
    graph = runtime / "workspace_graph_v2.json"
    dirty = runtime / "workspace_graph_v2.dirty"
    if state is None:
        return False, "отсутствует или повреждено состояние Graph V2"
    if state.get("state_version") != "1.0" or state.get("graph_schema_version") != "2.0":
        return False, "состояние Graph V2 имеет неподдерживаемую схему"
    if state.get("root") != str(root.resolve()) or state.get("graph") != str(graph.resolve()):
        return False, "состояние Graph V2 относится к другому проекту"
    try:
        stat = graph.stat()
    except OSError:
        return False, "файл Graph V2 отсутствует"
    if state.get("graph_size") != stat.st_size or state.get("graph_mtime_ns") != stat.st_mtime_ns:
        return False, "Graph V2 расходится с сохраненным digest-состоянием"
    if dirty.exists() and lock_state == "idle":
        return False, "Graph V2 помечен как dirty; дождитесь watcher или выполните ensure"
    if dirty.exists() and lock_state == "busy":
        return False, "Graph V2 изменяется другим процессом; повторите commit после watcher"
    return True, "graph_state_digest=OK"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--lock-state", choices=("idle", "busy"), required=True)
    args = parser.parse_args()
    ok, message = validate(args.root.resolve(), args.lock_state)
    if not ok:
        print(f"ОШИБКА pre-commit Graph V2: {message}")
        return 1
    print(f"Graph V2: {message}; lock={args.lock_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
