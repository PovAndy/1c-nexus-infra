#!/usr/bin/env python3
"""Единый stdin-JSON диспетчер событийных hook-обработчиков рабочей среды."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.hooks.post_write_evaluator import evaluate_target
    from scripts.hooks.pre_write_backup import backup_target
    from scripts.hooks.stop_hook_gate_check import check_stop
except ModuleNotFoundError:  # запуск как scripts/run_hook.py
    from hooks.post_write_evaluator import evaluate_target
    from hooks.pre_write_backup import backup_target
    from hooks.stop_hook_gate_check import check_stop


ROOT = Path(__file__).resolve().parents[1]
VALID_EVENTS = frozenset({"pre-write", "post-write", "pre-compact", "stop-hook", "session-start"})
PATCH_PATH_RE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.MULTILINE)
UNIFIED_PATH_RE = re.compile(r"^\+\+\+ (?:[ab]/)?(.+?)(?:\t.*)?$", re.MULTILINE)


def read_event(stdin: Any, fallback_path: str = "") -> dict[str, Any]:
    """Читает один JSON-контекст; некорректный input становится пустым безопасным событием."""
    raw = stdin.read().strip()
    if not raw:
        return {"file_path": fallback_path, "file_paths": _unique_paths([fallback_path]), "tool_name": "", "tool_input": {}}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"file_path": fallback_path, "file_paths": _unique_paths([fallback_path]), "tool_name": "", "tool_input": {}}
    if not isinstance(payload, dict):
        return {"file_path": fallback_path, "file_paths": _unique_paths([fallback_path]), "tool_name": "", "tool_input": {}}
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    file_path = payload.get("file_path") or tool_input.get("file_path") or fallback_path
    command = tool_input.get("command")
    file_paths = _unique_paths(
        [file_path if isinstance(file_path, str) else fallback_path]
        + _paths_from_patch(command if isinstance(command, str) else "")
    )
    return {
        "file_path": file_path if isinstance(file_path, str) else fallback_path,
        "file_paths": file_paths,
        "tool_name": payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else "",
        "tool_input": tool_input,
    }


def _unique_paths(paths: list[str]) -> list[str]:
    """Сохраняет порядок и исключает служебные/пустые пути из hook-контекста."""
    result: list[str] = []
    for path in paths:
        normalized = path.strip()
        if normalized and normalized != "/dev/null" and normalized not in result:
            result.append(normalized)
    return result


def _paths_from_patch(command: str) -> list[str]:
    """Извлекает целевые файлы из apply_patch и unified-diff без обращения к shell."""
    paths = PATCH_PATH_RE.findall(command)
    if not paths:
        paths = UNIFIED_PATH_RE.findall(command)
    return _unique_paths(paths)


def _session_start() -> tuple[int, str]:
    """Сверяет фактическую точку и планирует Graph V2 без ожидания его блокировки."""
    reality = [sys.executable, str(ROOT / "scripts" / "reconcile_reality.py")]
    try:
        completed = subprocess.run(reality, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        message = "Reality Reconciliation не завершился в лимит; не считайте handover подтвержденным."
    else:
        message = completed.stdout.strip() or "Reality Reconciliation не вернул диагностического результата."
    graph = [
        sys.executable,
        str(ROOT / "scripts" / "workspace_graph_v2_manager.py"),
        "ensure",
        "--quiet",
        "--reason",
        "hook:session-start",
    ]
    try:
        subprocess.Popen(graph, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        message += " Graph V2 не удалось запланировать; перед навигацией выполните его явную проверку."
    return 0, json.dumps({"kind": "reality_reconciliation", "action": message[:1200]}, ensure_ascii=False)


def _pre_compact() -> tuple[int, str]:
    """Сохраняет компактную локальную выжимку перед сжатием без внешних сервисов."""
    command = [
        sys.executable,
        str(ROOT / "scripts" / "distill_sessions.py"),
        "--max-files",
        "40",
        "--max-lines-per-file",
        "4000",
    ]
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=18, check=False)
    except subprocess.TimeoutExpired:
        return 0, '{"kind":"distillation_deferred"}'
    if completed.returncode != 0:
        return 0, '{"kind":"distillation_deferred"}'
    return 0, ""


def dispatch(event_name: str, event: dict[str, Any]) -> tuple[int, str]:
    """Маршрутизирует строго известный набор событий, не вызывая сторонние команды."""
    paths = event.get("file_paths")
    paths = paths if isinstance(paths, list) else [str(event.get("file_path", ""))]
    if event_name == "pre-write":
        for path in paths:
            backup_target(str(path))
        return 0, ""
    if event_name == "post-write":
        for path in paths:
            code, diagnostic = evaluate_target(str(path))
            if code:
                return code, diagnostic
        return 0, ""
    if event_name == "pre-compact":
        return _pre_compact()
    if event_name == "stop-hook":
        return check_stop()
    if event_name == "session-start":
        return _session_start()
    return 2, '{"kind":"unsupported_event"}'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="stdin-JSON dispatcher инфраструктурных hook-событий")
    parser.add_argument("event", choices=tuple(sorted(VALID_EVENTS)))
    parser.add_argument("file_path", nargs="?", default="", help="Fallback-путь только для CLI-проверки")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    event = read_event(sys.stdin, args.file_path)
    try:
        code, diagnostic = dispatch(args.event, event)
    except OSError as exc:
        code, diagnostic = 2, json.dumps({"kind": "hook_io_error", "detail": str(exc)[:300]}, ensure_ascii=False)
    if code:
        if diagnostic:
            print(diagnostic, file=sys.stderr)
        return code
    if args.event in {"stop-hook", "pre-compact"}:
        print(json.dumps({"continue": True}, ensure_ascii=False))
    elif args.event == "session-start" and diagnostic:
        try:
            message = str(json.loads(diagnostic).get("action", ""))
        except json.JSONDecodeError:
            message = "Graph V2 временно недоступен; требуется отдельная проверка."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}, ensure_ascii=False))
    elif diagnostic:
        print(diagnostic, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
