#!/usr/bin/env python3
"""Локальный FSM-менеджер RAG-памяти knowledge_base.json v2.0."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
KB_PATH = ROOT_DIR / "knowledge_base.json"
SEED_PATH = ROOT_DIR / "data" / "knowledge_base.seed.json"

STATUS_LABELS = {
    "under_review": "на проверке",
    "success": "удачно",
    "failed": "неудачно",
    "partial": "частично",
    "unstable": "нестабильно",
}
LEGACY_STATUS_ALIASES = {
    "SUCCESS": "success",
    "FAIL": "failed",
}
INDEX_FIELDS = {
    "by_topic": "topic",
    "by_subtopic": "subtopic",
    "by_kind": "kind",
    "by_mem_room": "mem_room",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", value.strip()).strip("-").lower()
    return slug[:80] or "task"


def _empty_kb() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "version": "2.0",
        "taxonomy": {
            "x17_recovery": {},
            "validation": {},
            "environment_setup": {},
            "anti_patterns": {},
            "1c_logic": {},
        },
        "error_solution_table": [],
        "indexes": {},
    }


def _seed_kb() -> dict[str, Any]:
    """Загружает каноническую seed-структуру schema 2.0 из data/knowledge_base.seed.json."""
    try:
        return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_kb()


def _ensure_kb_seeded(path: Path) -> None:
    """Автоинициализирует knowledge_base.json из seed, если файла ещё нет."""
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _seed_kb()
    _ensure_schema(data)
    with path.open("w+", encoding="utf-8") as handle:
        _write_locked(handle, data)


def _load_kb_from_text(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return _empty_kb()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ОШИБКА: knowledge_base.json поврежден: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("ОШИБКА: knowledge_base.json должен содержать JSON-объект")
    return data


def _ensure_schema(data: dict[str, Any]) -> None:
    data.setdefault("schema_version", "2.0")
    data.setdefault("version", data["schema_version"])
    data.setdefault("taxonomy", {})
    data["taxonomy"].setdefault("x17_recovery", {})
    data["taxonomy"].setdefault("validation", {})
    data["taxonomy"].setdefault("environment_setup", {})
    data["taxonomy"].setdefault("anti_patterns", {})
    data["taxonomy"].setdefault("1c_logic", {})
    table = data.setdefault("error_solution_table", [])
    if not isinstance(table, list):
        raise SystemExit("ОШИБКА: error_solution_table должен быть массивом")
    data.setdefault("indexes", {})


def _normalize_status(value: str) -> str:
    raw = value.strip()
    status = LEGACY_STATUS_ALIASES.get(raw.upper(), raw.lower())
    if status not in STATUS_LABELS:
        allowed = ", ".join(STATUS_LABELS)
        raise SystemExit(f"ОШИБКА: неизвестный статус '{value}'. Допустимо: {allowed}")
    return status


def _topic_for_task(task: str) -> str:
    if re.search(r"x17|лс|ls|регистр|register|epf|1c|1с", task, re.IGNORECASE):
        return "x17_recovery"
    return "validation"


def _entry_id(task: str, status: str, created_at: str) -> str:
    digest = hashlib.sha1(f"{task}|{status}|{created_at}".encode("utf-8")).hexdigest()[:10]
    return f"kb-auto-{_slug(task)}-{digest}"


def _build_entry(args: argparse.Namespace, status: str) -> dict[str, Any]:
    created_at = _now_iso()
    task = args.task or f"Обновление статуса {args.id}"
    topic = args.topic or _topic_for_task(task)
    label = STATUS_LABELS[status]
    return {
        "id": _entry_id(task, status, created_at),
        "kind": "session_result",
        "topic": topic,
        "subtopic": f"fsm_{status}",
        "mem_room": "auto-rag-log",
        "title": f"{task} [{label}]",
        "context": task,
        "problem": args.error_log if status == "failed" else "",
        "symptoms": [args.error_log] if args.error_log else [],
        "root_cause": "",
        "failed_attempts": [args.error_log] if status == "failed" and args.error_log else [],
        "successful_fix": args.code_fix if status in {"success", "partial", "unstable"} else "",
        "recommended_fix": args.code_fix,
        "lesson": args.code_fix or args.error_log or f"Автологирование задачи {task}",
        "evidence": ["kb_manager.py auto-log"],
        "source_lines": [],
        "confidence": "medium",
        "tags": ["auto-log", status, topic],
        "fsm_status": status,
        "status": label,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _validate_jsonable(data: dict[str, Any]) -> None:
    try:
        json.dumps(data, ensure_ascii=False)
    except TypeError as exc:
        raise SystemExit(f"ОШИБКА: структура не сериализуется в JSON: {exc}") from exc


def _expected_indexes(data: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    indexes: dict[str, dict[str, list[str]]] = {
        index_name: {} for index_name in INDEX_FIELDS
    }
    for entry in data.get("error_solution_table", []):
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            continue
        for index_name, field_name in INDEX_FIELDS.items():
            field_value = entry.get(field_name)
            if isinstance(field_value, str) and field_value:
                indexes[index_name].setdefault(field_value, []).append(entry_id)
    for buckets in indexes.values():
        for bucket, entry_ids in buckets.items():
            buckets[bucket] = sorted(set(entry_ids))
    return {
        index_name: dict(sorted(buckets.items()))
        for index_name, buckets in indexes.items()
    }


def _validate_integrity(data: dict[str, Any], *, require_indexes: bool = True) -> None:
    if data.get("schema_version") != "2.0":
        raise SystemExit("ОШИБКА: schema_version knowledge_base.json должна быть 2.0")
    table = data.get("error_solution_table")
    if not isinstance(table, list):
        raise SystemExit("ОШИБКА: error_solution_table должен быть массивом")

    entry_ids: list[str] = []
    for position, entry in enumerate(table):
        if not isinstance(entry, dict):
            raise SystemExit(
                f"ОШИБКА: error_solution_table[{position}] должен быть объектом"
            )
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise SystemExit(
                f"ОШИБКА: error_solution_table[{position}] не содержит корректный id"
            )
        entry_ids.append(entry_id)
        fsm_status = entry.get("fsm_status")
        if fsm_status is not None and fsm_status not in STATUS_LABELS:
            raise SystemExit(
                f"ОШИБКА: запись '{entry_id}' содержит неизвестный fsm_status"
            )
        topic = entry.get("topic")
        if not isinstance(topic, str) or not topic:
            raise SystemExit(f"ОШИБКА: запись '{entry_id}' не содержит topic")

    if len(entry_ids) != len(set(entry_ids)):
        raise SystemExit("ОШИБКА: error_solution_table содержит повторяющиеся id")

    if require_indexes and data.get("indexes") != _expected_indexes(data):
        raise SystemExit(
            "ОШИБКА: indexes не соответствуют error_solution_table; выполните --reindex"
        )
    _validate_jsonable(data)


def _rebuild_indexes(data: dict[str, Any]) -> None:
    data["indexes"] = _expected_indexes(data)


def _write_locked(handle: Any, data: dict[str, Any]) -> None:
    _validate_jsonable(data)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    handle.seek(0)
    handle.truncate()
    handle.write(payload)
    handle.flush()
    os.fsync(handle.fileno())
    handle.seek(0)
    json.loads(handle.read())


def _find_entry(table: list[Any], entry_id: str) -> dict[str, Any] | None:
    for entry in table:
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    return None


def _title_without_status(title: str) -> str:
    labels = "|".join(re.escape(label) for label in STATUS_LABELS.values())
    return re.sub(rf"\s*\[(?:{labels})\]\s*$", "", title).strip()


def _update_entry_status(
    data: dict[str, Any], entry_id: str, status: str, args: argparse.Namespace
) -> str:
    table = data["error_solution_table"]
    entry = _find_entry(table, entry_id)
    if entry is None:
        raise SystemExit(f"ОШИБКА: запись с id '{entry_id}' не найдена")
    now = _now_iso()
    label = STATUS_LABELS[status]
    if args.task.strip():
        entry["context"] = args.task.strip()
        title_base = args.task.strip()
    else:
        title_base = _title_without_status(str(entry.get("title", entry.get("context", entry_id))))
    entry["title"] = f"{title_base} [{label}]"
    entry["subtopic"] = f"fsm_{status}"
    entry["fsm_status"] = status
    entry["status"] = label
    tags = [
        tag for tag in entry.get("tags", [])
        if tag not in STATUS_LABELS and tag not in STATUS_LABELS.values()
    ]
    for tag in (status, entry.get("topic", "")):
        if tag and tag not in tags:
            tags.append(tag)
    entry["tags"] = tags
    if args.error_log:
        entry["problem"] = args.error_log
        entry["symptoms"] = [args.error_log]
        if status == "failed":
            entry["failed_attempts"] = [args.error_log]
    if args.code_fix:
        if status in {"success", "partial", "unstable"}:
            entry["successful_fix"] = args.code_fix
        entry["recommended_fix"] = args.code_fix
        entry["lesson"] = args.code_fix
    entry["updated_at"] = now
    data["last_ingest"] = now
    return now


def _add_entry(data: dict[str, Any], args: argparse.Namespace, status: str) -> dict[str, Any]:
    entry = _build_entry(args, status)
    data["error_solution_table"].append(entry)
    data["last_ingest"] = entry["created_at"]
    return entry


def _locked_mutation(path: Path, args: argparse.Namespace, status: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            data = _load_kb_from_text(handle.read())
            _ensure_schema(data)
            if args.id:
                _update_entry_status(data, args.id, status, args)
                result = f"OK kb_manager: updated {args.id} status={STATUS_LABELS[status]}"
            else:
                entry = _add_entry(data, args, status)
                result = f"OK kb_manager: added {entry['id']} status={STATUS_LABELS[status]}"
            _rebuild_indexes(data)
            _validate_integrity(data)
            _write_locked(handle, data)
            return result
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _locked_validate(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"ОШИБКА: knowledge_base.json не найден: {path}")
    with path.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            data = _load_kb_from_text(handle.read())
            _validate_integrity(data)
            table_size = len(data["error_solution_table"])
            return f"OK kb_manager: schema=2.0 entries={table_size} indexes=actual"
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _locked_reindex(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"ОШИБКА: knowledge_base.json не найден: {path}")
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            data = _load_kb_from_text(handle.read())
            _ensure_schema(data)
            expected = _expected_indexes(data)
            changed = data.get("indexes") != expected
            if changed:
                data["indexes"] = expected
                data["last_ingest"] = _now_iso()
            _validate_integrity(data)
            if changed:
                _write_locked(handle, data)
            state = "rebuilt" if changed else "actual"
            return (
                "OK kb_manager: "
                f"schema=2.0 entries={len(data['error_solution_table'])} indexes={state}"
            )
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FSM-запись опыта в knowledge_base.json v2.0")
    parser.add_argument("--id", default="", help="ID существующей записи для обновления статуса")
    parser.add_argument("--task", default="", help="Краткое имя или описание задачи")
    parser.add_argument("--status", default="", help="FSM-статус: under_review/success/failed/partial/unstable")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Проверить схему, уникальность id и актуальность indexes без записи",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Атомарно синхронизировать indexes с error_solution_table",
    )
    parser.add_argument(
        "--topic",
        choices=("x17_recovery", "validation", "environment_setup", "anti_patterns", "1c_logic"),
        default="",
        help="Явный раздел RAG; без параметра используется автоматическая классификация",
    )
    parser.add_argument("--code_fix", default="", help="Что исправлено или какой паттерн применен")
    parser.add_argument("--error_log", default="", help="Краткий лог ошибки или симптом")
    parser.add_argument("--kb", default=str(KB_PATH), help="Путь к knowledge_base.json")
    args = parser.parse_args()
    actions = int(bool(args.status)) + int(args.validate) + int(args.reindex)
    if actions != 1:
        parser.error("задайте ровно одно действие: --status, --validate или --reindex")
    if args.status:
        args.status = _normalize_status(args.status)
    if not args.id and not args.task.strip():
        if args.status:
            parser.error("--task обязателен при создании новой записи")
    return args


def main() -> int:
    args = parse_args()
    path = Path(args.kb)
    _ensure_kb_seeded(path)
    if args.validate:
        message = _locked_validate(path)
    elif args.reindex:
        message = _locked_reindex(path)
    else:
        message = _locked_mutation(path, args, args.status)
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
