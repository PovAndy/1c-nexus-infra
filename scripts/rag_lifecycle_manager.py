#!/usr/bin/env python3
"""Автоматизирует доказуемый FSM-жизненный цикл RAG без прямой записи в KB."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


КОРЕНЬ_ПРОЕКТА = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
КОРЕНЬ_WORKSPACE = КОРЕНЬ_ПРОЕКТА
KB_MANAGER = КОРЕНЬ_ПРОЕКТА / "scripts" / "kb_manager.py"
KB_PATH = КОРЕНЬ_WORKSPACE / "knowledge_base.json"
STATE_PATH = КОРЕНЬ_ПРОЕКТА / "temp" / "rag_lifecycle_active.json"
LOCK_PATH = КОРЕНЬ_ПРОЕКТА / "temp" / "rag_lifecycle_active.lock"
ФИНАЛЬНЫЕ_СТАТУСЫ = {"success", "failed", "partial"}
ТЕМЫ = {
    "x17_recovery",
    "validation",
    "environment_setup",
    "anti_patterns",
    "1c_logic",
}


def сейчас_iso() -> str:
    """Возвращает UTC-время без микросекунд."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def блокировка(путь: Path) -> Iterator[None]:
    """Сериализует операции над активным lifecycle-state."""
    путь.parent.mkdir(parents=True, exist_ok=True)
    with путь.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def прочитать_json(путь: Path) -> dict[str, Any] | None:
    """Читает небольшой JSON-state либо сообщает об отсутствии."""
    try:
        данные = json.loads(путь.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return данные if isinstance(данные, dict) else None


def записать_json_атомарно(путь: Path, данные: dict[str, Any]) -> None:
    """Сохраняет lifecycle-state атомарно и с приватными правами."""
    путь.parent.mkdir(parents=True, exist_ok=True)
    дескриптор, имя = tempfile.mkstemp(
        prefix=f".{путь.name}.",
        suffix=".tmp",
        dir=путь.parent,
        text=True,
    )
    os.fchmod(дескриптор, 0o600)
    временный = Path(имя)
    try:
        with os.fdopen(дескриптор, "w", encoding="utf-8") as поток:
            json.dump(данные, поток, ensure_ascii=False, indent=2)
            поток.write("\n")
            поток.flush()
            os.fsync(поток.fileno())
        временный.replace(путь)
    except BaseException:
        временный.unlink(missing_ok=True)
        raise


def вызвать_kb_manager(kb: Path, аргументы: list[str]) -> str:
    """Вызывает единственный разрешенный writer и возвращает одну строку статуса."""
    команда = [
        sys.executable,
        str(KB_MANAGER),
        *аргументы,
        "--kb",
        str(kb),
    ]
    результат = subprocess.run(
        команда,
        cwd=КОРЕНЬ_ПРОЕКТА,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if результат.returncode != 0:
        деталь = (результат.stderr or результат.stdout).strip()
        raise RuntimeError(деталь or "kb_manager завершился с ошибкой")
    return результат.stdout.strip()


def валидировать_kb(kb: Path) -> str:
    """Проверяет схему, уникальность id и синхронность indexes."""
    return вызвать_kb_manager(kb, ["--validate"])


def найти_запись(kb: Path, entry_id: str) -> dict[str, Any] | None:
    """Находит одну запись после shared read, не меняя базу знаний."""
    with kb.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            данные = json.load(handle)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    for запись in данные.get("error_solution_table", []):
        if isinstance(запись, dict) and запись.get("id") == entry_id:
            return запись
    return None


def добавить_запись(
    kb: Path,
    *,
    задача: str,
    тема: str,
    code_fix: str,
    error_log: str = "",
) -> str:
    """Создает under_review и извлекает присвоенный kb_manager id."""
    аргументы = [
        "--task",
        задача,
        "--status",
        "under_review",
        "--topic",
        тема,
        "--code_fix",
        code_fix,
    ]
    if error_log:
        аргументы.extend(["--error_log", error_log])
    вывод = вызвать_kb_manager(kb, аргументы)
    совпадение = re.search(r"\badded\s+(\S+)\s+status=", вывод)
    if совпадение is None:
        raise RuntimeError("kb_manager не вернул id новой записи")
    валидировать_kb(kb)
    return совпадение.group(1)


def обновить_запись(
    kb: Path,
    *,
    entry_id: str,
    статус: str,
    code_fix: str,
    error_log: str = "",
) -> None:
    """Обновляет FSM-статус через kb_manager и сразу валидирует индексы."""
    аргументы = [
        "--id",
        entry_id,
        "--status",
        статус,
        "--code_fix",
        code_fix,
    ]
    if error_log:
        аргументы.extend(["--error_log", error_log])
    вызвать_kb_manager(kb, аргументы)
    валидировать_kb(kb)


def staged_снимок(корень: Path) -> tuple[list[str], str]:
    """Возвращает имена staged-файлов и digest служебного raw-diff."""
    имена = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=корень,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if имена.returncode != 0:
        raise RuntimeError(имена.stderr.decode("utf-8", errors="replace").strip())
    файлы = sorted(
        элемент.decode("utf-8", errors="surrogateescape")
        for элемент in имена.stdout.split(b"\0")
        if элемент
    )
    if not файлы:
        return [], ""
    raw = subprocess.run(
        ["git", "diff", "--cached", "--raw", "-z", "--no-renames"],
        cwd=корень,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if raw.returncode != 0:
        raise RuntimeError(raw.stderr.decode("utf-8", errors="replace").strip())
    return файлы, hashlib.sha256(raw.stdout).hexdigest()


def тема_для_файлов(файлы: list[str]) -> str:
    """Классифицирует checkpoint без чтения содержимого diff."""
    if any(путь.startswith("src/") for путь in файлы):
        return "x17_recovery"
    инфраструктурные = (
        "scripts/",
        "docs/",
        ".vscode/",
        ".githooks/",
        "tools/systemd/",
        ".clinerules",
        ".gitignore",
    )
    if any(путь.startswith(инфраструктурные) for путь in файлы):
        return "environment_setup"
    return "validation"


def краткое_описание_файлов(файлы: list[str]) -> str:
    """Формирует ограниченное описание staged scope без содержимого."""
    показаны = файлы[:5]
    хвост = f", еще {len(файлы) - len(показаны)}" if len(файлы) > len(показаны) else ""
    return ", ".join(показаны) + хвост


def начать(
    kb: Path,
    state_path: Path,
    *,
    задача: str,
    тема: str,
    code_fix: str,
    digest: str = "",
) -> dict[str, Any]:
    """Создает новую активную задачу и сохраняет ее локальный state."""
    entry_id = добавить_запись(
        kb,
        задача=задача,
        тема=тема,
        code_fix=code_fix,
    )
    state = {
        "state_version": "1.0",
        "entry_id": entry_id,
        "task": задача,
        "topic": тема,
        "fsm_status": "under_review",
        "staged_digest": digest,
        "created_at": сейчас_iso(),
        "updated_at": сейчас_iso(),
        "closed_at": "",
    }
    записать_json_атомарно(state_path, state)
    return state


def checkpoint(
    kb: Path,
    state_path: Path,
    корень: Path,
) -> tuple[str, dict[str, Any] | None]:
    """Создает или обновляет under_review по staged metadata."""
    файлы, digest = staged_снимок(корень)
    if not файлы:
        валидировать_kb(kb)
        return "staged-изменений нет", прочитать_json(state_path)

    state = прочитать_json(state_path)
    запись = (
        найти_запись(kb, str(state.get("entry_id", "")))
        if state is not None
        else None
    )
    if (
        state is not None
        and запись is not None
        and запись.get("fsm_status") not in ФИНАЛЬНЫЕ_СТАТУСЫ
    ):
        if state.get("staged_digest") == digest:
            валидировать_kb(kb)
            return "checkpoint уже зафиксирован", state
        code_fix = (
            f"Автоматический staged checkpoint {digest[:12]}; "
            f"файлов={len(файлы)}; {краткое_описание_файлов(файлы)}"
        )
        обновить_запись(
            kb,
            entry_id=str(state["entry_id"]),
            статус="under_review",
            code_fix=code_fix,
        )
        state["fsm_status"] = "under_review"
        state["staged_digest"] = digest
        state["updated_at"] = сейчас_iso()
        записать_json_атомарно(state_path, state)
        return "активная запись обновлена", state

    задача = (
        f"Автоматический Git checkpoint: {len(файлы)} файлов "
        f"({краткое_описание_файлов(файлы)})"
    )
    тема = тема_для_файлов(файлы)
    code_fix = (
        f"Staged metadata зафиксирована без чтения содержимого diff; "
        f"digest={digest[:12]}"
    )
    state = начать(
        kb,
        state_path,
        задача=задача,
        тема=тема,
        code_fix=code_fix,
        digest=digest,
    )
    return "создана under_review запись", state


def текущая_активная_запись(
    kb: Path, state_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Возвращает согласованные state и запись либо останавливает операцию."""
    state = прочитать_json(state_path)
    if state is None:
        raise RuntimeError("активная RAG-задача не найдена")
    запись = найти_запись(kb, str(state.get("entry_id", "")))
    if запись is None:
        raise RuntimeError("активная RAG-запись отсутствует в error_solution_table")
    return state, запись


def разобрать_аргументы() -> argparse.Namespace:
    """Разбирает lifecycle-команду и ее доказательства."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("start", "checkpoint", "verified", "feedback", "status", "validate"),
    )
    parser.add_argument("--task", default="")
    parser.add_argument("--topic", choices=sorted(ТЕМЫ), default="environment_setup")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--result", choices=sorted(ФИНАЛЬНЫЕ_СТАТУСЫ), default="")
    parser.add_argument("--error-log", default="")
    parser.add_argument("--root", type=Path, default=КОРЕНЬ_ПРОЕКТА)
    parser.add_argument("--kb", type=Path, default=KB_PATH)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    return parser.parse_args()


def main() -> int:
    """Выполняет сериализованный RAG lifecycle."""
    args = разобрать_аргументы()
    корень = args.root.expanduser().resolve()
    kb = args.kb.expanduser().resolve()
    state_path = args.state.expanduser().resolve()
    lock_path = args.lock.expanduser().resolve()

    with блокировка(lock_path):
        if args.command == "validate":
            print(валидировать_kb(kb))
            return 0
        if args.command == "status":
            валидировать_kb(kb)
            state = прочитать_json(state_path)
            if state is None:
                print("rag_lifecycle=idle")
                return 0
            запись = найти_запись(kb, str(state.get("entry_id", "")))
            статус = запись.get("fsm_status") if запись else "missing"
            print(
                f"rag_lifecycle={статус} entry_id={state.get('entry_id', '-')}"
            )
            return 0
        if args.command == "start":
            if not args.task.strip():
                raise SystemExit("--task обязателен для start")
            state = начать(
                kb,
                state_path,
                задача=args.task.strip(),
                тема=args.topic,
                code_fix=args.evidence or "Задача принята в работу",
            )
            print(f"rag_lifecycle=under_review entry_id={state['entry_id']}")
            return 0
        if args.command == "checkpoint":
            результат, state = checkpoint(kb, state_path, корень)
            entry_id = state.get("entry_id", "-") if state else "-"
            print(f"rag_lifecycle=under_review entry_id={entry_id} action={результат}")
            return 0

        state, запись = текущая_активная_запись(kb, state_path)
        if запись.get("fsm_status") in ФИНАЛЬНЫЕ_СТАТУСЫ:
            raise RuntimeError("активная запись уже закрыта финальным статусом")
        if args.command == "verified":
            if not args.evidence.strip():
                raise SystemExit("--evidence обязателен для verified")
            обновить_запись(
                kb,
                entry_id=str(state["entry_id"]),
                статус="unstable",
                code_fix=args.evidence.strip(),
            )
            state["fsm_status"] = "unstable"
        else:
            if not args.result:
                raise SystemExit("--result обязателен для feedback")
            evidence = args.evidence.strip() or f"Пользовательский результат: {args.result}"
            обновить_запись(
                kb,
                entry_id=str(state["entry_id"]),
                статус=args.result,
                code_fix=evidence,
                error_log=args.error_log.strip(),
            )
            state["fsm_status"] = args.result
            state["closed_at"] = сейчас_iso()
        state["updated_at"] = сейчас_iso()
        записать_json_атомарно(state_path, state)
        print(
            f"rag_lifecycle={state['fsm_status']} entry_id={state['entry_id']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
