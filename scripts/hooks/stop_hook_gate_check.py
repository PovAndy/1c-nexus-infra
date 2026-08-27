"""Проверяет GATES.md при остановке агента и ограничивает бесплодный цикл остановок."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Callable

try:
    from .common import atomic_json, file_fingerprint, read_json, workspace_root
except ImportError:  # прямой запуск скрипта
    from common import atomic_json, file_fingerprint, read_json, workspace_root


STATE_PATH = workspace_root() / "temp" / ".stop_hook_state.json"


def _workspace_fingerprint() -> str:
    """Привязывает счетчик к GATES и последнему Graph inventory, не читая исходники."""
    root = workspace_root()
    gates = file_fingerprint(root / "GATES.md")
    graph_state = read_json(root / "temp" / "workspace_graph_v2.state.json") or {}
    inventory = str(graph_state.get("inventory_digest", "missing"))
    return f"{gates}:{inventory}"


def check_stop(gate_runner: Callable[..., int] | None = None) -> tuple[int, str]:
    """Возвращает 2 при незакрытых воротах и STOP после пяти одинаковых неудач."""
    if gate_runner is None:
        try:
            from scripts.gate_check import run_ledger
        except ModuleNotFoundError:
            from gate_check import run_ledger
        gate_runner = run_ledger

    root = workspace_root()
    # Codex Stop принимает только один JSON на stdout. Реестр печатает
    # человекочитаемые строки, поэтому изолируем их внутри hook-обработчика.
    with redirect_stdout(io.StringIO()):
        passed = gate_runner(root / "GATES.md", root=root, reverify=True) == 0
    if passed:
        STATE_PATH.unlink(missing_ok=True)
        return 0, ""
    fingerprint = _workspace_fingerprint()
    previous = read_json(STATE_PATH) or {}
    failures = int(previous.get("failures", 0)) + 1 if previous.get("fingerprint") == fingerprint else 1
    atomic_json(STATE_PATH, {"version": 1, "fingerprint": fingerprint, "failures": failures})
    if failures >= 5:
        return 2, json.dumps(
            {
                "kind": "stop_hook_escalation",
                "failures": failures,
                "action": "Ворота пять раз не прошли без изменения исходников. Нужна явная проверка человеком.",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return 2, json.dumps(
        {"kind": "gates_unmet", "failures": failures, "action": "Исправьте ворота и повторите проверку."},
        ensure_ascii=False,
        separators=(",", ":"),
    )
