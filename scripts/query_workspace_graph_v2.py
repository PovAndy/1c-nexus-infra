#!/usr/bin/env python3
"""Выполняет компактные freshness-guarded запросы к Workspace Graph V2."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import workspace_graph_v2_manager as manager


КОРЕНЬ_ПРОЕКТА = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))


def загрузить_актуальный_граф(корень: Path) -> dict[str, Any]:
    """Гарантирует свежесть и читает граф только в локальный процесс."""
    пути = manager.построить_пути(корень)
    manager.обеспечить_актуальность(пути, причина="query")
    данные = json.loads(пути.граф.read_text(encoding="utf-8"))
    if not isinstance(данные, dict):
        raise SystemExit("Граф должен содержать JSON-объект")
    return данные


def совпадает(значение: str, шаблон: str) -> bool:
    """Сопоставляет без учета регистра, поддерживая точное совпадение."""
    return шаблон.casefold() in значение.casefold()


def ограничить(строки: list[str], limit: int) -> list[str]:
    """Ограничивает локальный результат до токено-безопасного объема."""
    if len(строки) <= limit:
        return строки
    остаток = len(строки) - limit
    return [*строки[:limit], f"… скрыто результатов: {остаток}"]


def сводка(данные: dict[str, Any]) -> list[str]:
    """Возвращает краткие агрегаты без выгрузки узлов."""
    узлы = данные.get("nodes", [])
    ребра = данные.get("edges", [])
    типы_узлов = Counter(
        узел.get("type") for узел in узлы if isinstance(узел, dict)
    )
    типы_ребер = Counter(
        ребро.get("type") for ребро in ребра if isinstance(ребро, dict)
    )
    return [
        f"schema={данные.get('schema_version')}",
        f"узлов={len(узлы)}: {dict(sorted(типы_узлов.items()))}",
        f"ребер={len(ребра)}: {dict(sorted(типы_ребер.items()))}",
        f"ошибок_разбора={данные.get('parse_error_files', 0)}",
    ]


def найти_файлы(
    данные: dict[str, Any], шаблон: str, limit: int
) -> list[str]:
    """Находит файловые узлы по части относительного пути."""
    строки = [
        f"{узел['id']} | lang={узел.get('lang', '-')}"
        for узел in данные.get("nodes", [])
        if isinstance(узел, dict)
        and узел.get("type") == "file"
        and совпадает(str(узел.get("id", "")), шаблон)
    ]
    return ограничить(sorted(строки), limit)


def найти_функции(
    данные: dict[str, Any], шаблон: str, limit: int
) -> list[str]:
    """Находит функции и выводит только сигнатуру с первой строкой документации."""
    строки = []
    for узел in данные.get("nodes", []):
        if (
            not isinstance(узел, dict)
            or узел.get("type") != "function"
            or not совпадает(str(узел.get("id", "")), шаблон)
        ):
            continue
        аргументы = ", ".join(str(аргумент) for аргумент in узел.get("args", []))
        документация = str(узел.get("doc", ""))
        строка = f"{узел['id']}({аргументы})"
        if документация:
            строка += f" — {документация}"
        строки.append(строка)
    return ограничить(sorted(строки), limit)


def найти_инструменты(
    данные: dict[str, Any], шаблон: str, limit: int
) -> list[str]:
    """Находит MCP-инструменты по идентификатору."""
    строки = [
        str(узел["id"])
        for узел in данные.get("nodes", [])
        if isinstance(узел, dict)
        and узел.get("type") == "mcp_tool"
        and совпадает(str(узел.get("id", "")), шаблон)
    ]
    return ограничить(sorted(строки), limit)


def разрешить_цели(данные: dict[str, Any], шаблон: str) -> set[str]:
    """Разрешает точный id либо набор функций по подстроке."""
    функции = {
        str(узел.get("id"))
        for узел in данные.get("nodes", [])
        if isinstance(узел, dict) and узел.get("type") == "function"
    }
    if шаблон in функции:
        return {шаблон}
    return {идентификатор for идентификатор in функции if совпадает(идентификатор, шаблон)}


def найти_связи(
    данные: dict[str, Any],
    шаблон: str,
    направление: str,
    limit: int,
) -> list[str]:
    """Возвращает CALLS-ребра для callers либо callees."""
    цели = разрешить_цели(данные, шаблон)
    строки: set[str] = set()
    for ребро in данные.get("edges", []):
        if not isinstance(ребро, dict) or ребро.get("type") != "CALLS":
            continue
        источник = str(ребро.get("source", ""))
        цель = str(ребро.get("target", ""))
        if направление == "callers" and цель in цели:
            строки.add(f"{источник} -> {цель}")
        elif направление == "callees" and источник in цели:
            строки.add(f"{источник} -> {цель}")
    return ограничить(sorted(строки), limit)


def разобрать_аргументы() -> argparse.Namespace:
    """Разбирает один тип токено-безопасного запроса."""
    parser = argparse.ArgumentParser(description=__doc__)
    группа = parser.add_mutually_exclusive_group()
    группа.add_argument("--file", default="")
    группа.add_argument("--function", default="")
    группа.add_argument("--tool", default="")
    группа.add_argument("--callers", default="")
    группа.add_argument("--callees", default="")
    группа.add_argument("--summary", action="store_true")
    parser.add_argument("--root", type=Path, default=КОРЕНЬ_ПРОЕКТА)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--ensure", action="store_true", help="обновить Graph и завершиться")
    return parser.parse_args()


def main() -> int:
    """Обеспечивает свежесть и печатает только целевую выборку."""
    args = разобрать_аргументы()
    limit = max(1, min(args.limit, 100))
    данные = загрузить_актуальный_граф(args.root.expanduser().resolve())
    if args.ensure:
        print("Graph V2 актуален")
        return 0
    if args.file:
        строки = найти_файлы(данные, args.file, limit)
    elif args.function:
        строки = найти_функции(данные, args.function, limit)
    elif args.tool:
        строки = найти_инструменты(данные, args.tool, limit)
    elif args.callers:
        строки = найти_связи(данные, args.callers, "callers", limit)
    elif args.callees:
        строки = найти_связи(данные, args.callees, "callees", limit)
    else:
        строки = сводка(данные)
    if строки:
        print("\n".join(строки))
    else:
        print("Совпадений нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
