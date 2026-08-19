#!/usr/bin/env python3
"""Интеграционно проверяет автоматизацию Graph V2, RAG и индексов KB."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import workspace_graph_v2_manager as graph_manager


КОРЕНЬ_ПРОЕКТА = Path(__file__).resolve().parents[1]
GRAPH_MANAGER = КОРЕНЬ_ПРОЕКТА / "scripts" / "workspace_graph_v2_manager.py"
KB_MANAGER = КОРЕНЬ_ПРОЕКТА / "scripts" / "kb_manager.py"
RAG_MANAGER = КОРЕНЬ_ПРОЕКТА / "scripts" / "rag_lifecycle_manager.py"


def выполнить(
    команда: list[str],
    *,
    cwd: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Запускает команду и завершает тест с короткой диагностикой."""
    результат = subprocess.run(
        команда,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if результат.returncode != 0:
        деталь = (результат.stderr or результат.stdout).strip()
        raise AssertionError(
            f"Команда завершилась с кодом {результат.returncode}: {деталь}"
        )
    return результат


def дождаться(условие: Any, timeout: float, сообщение: str) -> None:
    """Ожидает условие малыми интервалами без блокирующего sleep."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if условие():
            return
        time.sleep(0.1)
    raise AssertionError(сообщение)


def идентификаторы_графа(путь: Path) -> set[str]:
    """Читает только идентификаторы узлов тестового графа."""
    данные = json.loads(путь.read_text(encoding="utf-8"))
    return {
        str(узел["id"])
        for узел in данные["nodes"]
        if isinstance(узел, dict) and "id" in узел
    }


def тест_graph_ensure_and_watch(база: Path) -> dict[str, Any]:
    """Проверяет rebuild, no-op, параллельный ensure и watcher."""
    корень = база / "graph-project"
    корень.mkdir()
    исходник = корень / "sample.py"
    исходник.write_text(
        'def alpha(value):\n    """Первая версия."""\n    return value\n',
        encoding="utf-8",
    )
    vendor = корень / "context" / "mempalace" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "third_party.py").write_text(
        "def неподдерживаемый(:\n",
        encoding="utf-8",
    )
    пути = graph_manager.построить_пути(корень)

    обновлен, _ = graph_manager.обеспечить_актуальность(
        пути, причина="test:first"
    )
    assert обновлен
    обновлен, _ = graph_manager.обеспечить_актуальность(
        пути, причина="test:no-op"
    )
    assert not обновлен
    assert "sample.py::alpha" in идентификаторы_графа(пути.граф)
    начальный_граф = json.loads(пути.граф.read_text(encoding="utf-8"))
    assert начальный_граф["parse_error_files"] == 0
    assert начальный_граф["parse_errors"] == []
    assert "context/mempalace/vendor/third_party.py" not in идентификаторы_графа(
        пути.граф
    )

    исходник.write_text(
        'def beta(value, flag=False):\n    """Вторая версия."""\n    return value if flag else None\n',
        encoding="utf-8",
    )
    процессы = [
        subprocess.Popen(
            [
                sys.executable,
                str(GRAPH_MANAGER),
                "ensure",
                "--root",
                str(корень),
                "--quiet",
                "--reason",
                "test:concurrency",
            ],
            cwd=КОРЕНЬ_ПРОЕКТА,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    for процесс in процессы:
        stdout, stderr = процесс.communicate(timeout=60)
        assert процесс.returncode == 0, stderr or stdout
    assert "sample.py::beta" in идентификаторы_графа(пути.граф)
    graph_manager.проверить_граф(пути.граф, корень.resolve())

    watcher = subprocess.Popen(
        [
            sys.executable,
            str(GRAPH_MANAGER),
            "watch",
            "--root",
            str(корень),
            "--debounce",
            "0.2",
        ],
        cwd=КОРЕНЬ_ПРОЕКТА,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        дождаться(
            lambda: (
                (статус := graph_manager.прочитать_json(пути.статус_watcher))
                is not None
                and статус.get("state") == "running"
                and статус.get("pid") == watcher.pid
            ),
            15,
            "watcher не перешел в running",
        )
        исходник.write_text(
            'def gamma(payload):\n    """Событийная версия."""\n    return payload\n',
            encoding="utf-8",
        )
        дождаться(
            lambda: "sample.py::gamma" in идентификаторы_графа(пути.граф),
            20,
            "watcher не обновил граф после события",
        )
    finally:
        watcher.terminate()
        try:
            watcher.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            watcher.kill()
            watcher.communicate(timeout=5)
    assert watcher.returncode == 0
    return {
        "graph_nodes": len(
            json.loads(пути.граф.read_text(encoding="utf-8"))["nodes"]
        ),
        "concurrent_ensure": len(процессы),
        "watcher_event": True,
    }


def пустая_kb() -> dict[str, Any]:
    """Возвращает минимальную корректную KB для изолированного теста."""
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
        "indexes": {
            "by_topic": {},
            "by_subtopic": {},
            "by_kind": {},
            "by_mem_room": {},
        },
    }


def тест_rag_lifecycle_and_indexes(база: Path) -> dict[str, Any]:
    """Проверяет FSM, индексы, checkpoint и конкурентные записи."""
    kb = база / "knowledge_base.json"
    state = база / "rag_state.json"
    lock = база / "rag_state.lock"
    kb.write_text(
        json.dumps(пустая_kb(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    base_args = [
        "--kb",
        str(kb),
        "--state",
        str(state),
        "--lock",
        str(lock),
    ]
    выполнить(
        [
            sys.executable,
            str(RAG_MANAGER),
            "start",
            "--task",
            "Тест автоматического RAG lifecycle",
            "--topic",
            "environment_setup",
            "--evidence",
            "Создан тестовый diff",
            *base_args,
        ],
        cwd=КОРЕНЬ_ПРОЕКТА,
    )
    выполнить(
        [
            sys.executable,
            str(RAG_MANAGER),
            "verified",
            "--evidence",
            "Автоматические проверки пройдены",
            *base_args,
        ],
        cwd=КОРЕНЬ_ПРОЕКТА,
    )
    выполнить(
        [
            sys.executable,
            str(RAG_MANAGER),
            "feedback",
            "--result",
            "success",
            "--evidence",
            "Тестовая приемка подтверждена",
            *base_args,
        ],
        cwd=КОРЕНЬ_ПРОЕКТА,
    )

    процессы = [
        subprocess.Popen(
            [
                sys.executable,
                str(KB_MANAGER),
                "--task",
                f"Параллельная запись {номер}",
                "--status",
                "under_review",
                "--topic",
                "validation",
                "--kb",
                str(kb),
            ],
            cwd=КОРЕНЬ_ПРОЕКТА,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for номер in range(5)
    ]
    for процесс in процессы:
        stdout, stderr = процесс.communicate(timeout=30)
        assert процесс.returncode == 0, stderr or stdout

    git_root = база / "git-project"
    git_root.mkdir()
    выполнить(["git", "init", "-q"], cwd=git_root)
    (git_root / "automation.py").write_text(
        "def checkpoint():\n    return True\n",
        encoding="utf-8",
    )
    выполнить(["git", "add", "automation.py"], cwd=git_root)
    checkpoint_state = база / "checkpoint_state.json"
    выполнить(
        [
            sys.executable,
            str(RAG_MANAGER),
            "checkpoint",
            "--root",
            str(git_root),
            "--kb",
            str(kb),
            "--state",
            str(checkpoint_state),
            "--lock",
            str(база / "checkpoint.lock"),
        ],
        cwd=КОРЕНЬ_ПРОЕКТА,
    )
    выполнить(
        [sys.executable, str(KB_MANAGER), "--validate", "--kb", str(kb)],
        cwd=КОРЕНЬ_ПРОЕКТА,
    )

    данные = json.loads(kb.read_text(encoding="utf-8"))
    table = данные["error_solution_table"]
    ids = {запись["id"] for запись in table}
    indexed_ids = {
        entry_id
        for buckets in данные["indexes"].values()
        for values in buckets.values()
        for entry_id in values
    }
    assert ids <= indexed_ids
    assert len(ids) == len(table) == 7
    assert any(запись.get("fsm_status") == "success" for запись in table)
    return {
        "rag_entries": len(table),
        "indexes_cover_all_entries": True,
        "parallel_writes": len(процессы),
        "git_checkpoint": True,
    }


def main() -> int:
    """Запускает оба изолированных интеграционных контура."""
    with tempfile.TemporaryDirectory(prefix="epf1129-automation-") as каталог:
        база = Path(каталог)
        graph = тест_graph_ensure_and_watch(база)
        rag = тест_rag_lifecycle_and_indexes(база)
    print({"graph": graph, "rag": rag, "status": "PASS"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
