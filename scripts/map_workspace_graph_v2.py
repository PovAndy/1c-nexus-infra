#!/usr/bin/env python3
"""Строит полиглотный граф файлов, функций, вызовов и MCP-инструментов."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import tempfile
import warnings
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import networkx as nx
from tree_sitter import Node
from tree_sitter_languages import get_parser


КОРЕНЬ_ПРОЕКТА = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
ПУТЬ_ГРАФА = КОРЕНЬ_ПРОЕКТА / "temp" / "workspace_graph_v2.json"

РАСШИРЕНИЯ = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".sh": "shell",
    ".json": "json",
    ".toml": "toml",
}

ИГНОРИРУЕМЫЕ_КАТАЛОГИ = {
    ".git",
    ".venv",
    ".venv-gemini-bridge",
    "logs",
    "node_modules",
    "temp",
}

ИГНОРИРУЕМЫЕ_ПРЕФИКСЫ = (
    ("context", "mempalace", "vendor"),
    (".gemini", "skills"),
    (".agents", "skills"),
)

ТИПЫ_ФУНКЦИЙ = {
    "python": {"function_definition"},
    "javascript": {
        "arrow_function",
        "function_declaration",
        "function_expression",
        "generator_function_declaration",
        "generator_function",
        "method_definition",
    },
    "typescript": {
        "arrow_function",
        "function_declaration",
        "function_expression",
        "generator_function_declaration",
        "generator_function",
        "method_definition",
    },
}

ТИПЫ_КЛАССОВ = {
    "python": {"class_definition"},
    "javascript": {"class_declaration", "class"},
    "typescript": {"class_declaration", "abstract_class_declaration", "class"},
}

РЕГИСТРАТОРЫ_MCP = {
    "add_tool",
    "addTool",
    "register_tool",
    "registerTool",
    "tool",
}

ДОПУСТИМОЕ_ИМЯ_ВЫЗОВА = re.compile(
    r"^[^\W\d]\w*(?:(?:\.|\?\.)[^\W\d]\w*)*$",
    flags=re.UNICODE,
)


@dataclass(frozen=True)
class Вызов:
    """Содержит минимальные данные для отложенного разрешения цели вызова."""

    источник: str
    файл: str
    имя: str


def разобрать_аргументы() -> argparse.Namespace:
    """Возвращает параметры командной строки с безопасными значениями по умолчанию."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=КОРЕНЬ_ПРОЕКТА,
        help="Корень сканируемого проекта",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ПУТЬ_ГРАФА,
        help="Путь итогового JSON",
    )
    return parser.parse_args()


def каталог_игнорируется(имя: str) -> bool:
    """Проверяет каталог по контракту исключений."""
    return (
        имя in ИГНОРИРУЕМЫЕ_КАТАЛОГИ
        or имя.startswith(".venv")
        or "pycache" in имя.lower()
    )


def путь_игнорируется(корень: Path, путь: Path) -> bool:
    """Исключает известные сторонние деревья из навигационного индекса."""
    try:
        части = путь.relative_to(корень).parts
    except ValueError:
        return True
    return any(части[: len(префикс)] == префикс for префикс in ИГНОРИРУЕМЫЕ_ПРЕФИКСЫ)


def исходные_файлы(корень: Path) -> Iterator[tuple[Path, str]]:
    """Обходит поддерживаемые файлы в стабильном порядке без перехода по ссылкам."""
    for текущий, каталоги, файлы in os.walk(корень, followlinks=False):
        текущий_путь = Path(текущий)
        каталоги[:] = sorted(
            имя
            for имя in каталоги
            if not каталог_игнорируется(имя)
            and not путь_игнорируется(корень, текущий_путь / имя)
        )
        for имя in sorted(файлы):
            путь = текущий_путь / имя
            язык = РАСШИРЕНИЯ.get(путь.suffix.lower())
            if язык is not None and not путь.is_symlink():
                yield путь, язык


def текст_узла(узел: Node, исходник: bytes) -> str:
    """Извлекает UTF-8-текст узла без аварии на поврежденном файле."""
    return исходник[узел.start_byte : узел.end_byte].decode(
        "utf-8", errors="replace"
    )


def краткое_имя(узел: Node | None, исходник: bytes) -> str | None:
    """Возвращает имя синтаксического узла, если оно пригодно для идентификатора."""
    if узел is None:
        return None
    значение = " ".join(текст_узла(узел, исходник).split())
    return значение or None


def имя_функции(узел: Node, исходник: bytes) -> str:
    """Определяет имя объявленной либо присвоенной анонимной функции."""
    имя = краткое_имя(узел.child_by_field_name("name"), исходник)
    if имя:
        return имя

    родитель = узел.parent
    if родитель is not None:
        if родитель.type in {"variable_declarator", "pair"}:
            имя = краткое_имя(
                родитель.child_by_field_name("name")
                or родитель.child_by_field_name("key"),
                исходник,
            )
        elif родитель.type in {"assignment_expression", "augmented_assignment"}:
            имя = краткое_имя(родитель.child_by_field_name("left"), исходник)
        if имя:
            return имя

    строка, столбец = узел.start_point
    return f"анонимная_L{строка + 1}_C{столбец + 1}"


def имя_класса(узел: Node, исходник: bytes) -> str:
    """Возвращает имя класса либо устойчивую координатную заглушку."""
    имя = краткое_имя(узел.child_by_field_name("name"), исходник)
    if имя:
        return имя
    строка, столбец = узел.start_point
    return f"класс_L{строка + 1}_C{столбец + 1}"


def разделить_параметры(текст: str) -> list[str]:
    """Делит сигнатуру по запятым верхнего уровня, сохраняя типы и значения."""
    текст = текст.strip()
    if текст.startswith("(") and текст.endswith(")"):
        текст = текст[1:-1]
    if not текст:
        return []

    результат: list[str] = []
    начало = 0
    глубина = 0
    кавычка: str | None = None
    экранирован = False
    пары = {"(": ")", "[": "]", "{": "}"}
    закрывающие = set(пары.values())

    for индекс, символ in enumerate(текст):
        if кавычка is not None:
            if экранирован:
                экранирован = False
            elif символ == "\\":
                экранирован = True
            elif символ == кавычка:
                кавычка = None
            continue
        if символ in {"'", '"', "`"}:
            кавычка = символ
        elif символ in пары:
            глубина += 1
        elif символ in закрывающие:
            глубина = max(0, глубина - 1)
        elif символ == "," and глубина == 0:
            часть = " ".join(текст[начало:индекс].split())
            if часть:
                результат.append(часть)
            начало = индекс + 1

    часть = " ".join(текст[начало:].split())
    if часть:
        результат.append(часть)
    return результат


def аргументы_функции(узел: Node, исходник: bytes) -> list[str]:
    """Извлекает аргументы функции в порядке объявления."""
    параметры = (
        узел.child_by_field_name("parameters")
        or узел.child_by_field_name("parameter")
    )
    if параметры is None:
        return []
    return разделить_параметры(текст_узла(параметры, исходник))


def первая_строка(значение: str) -> str:
    """Нормализует первую непустую строку документации."""
    for строка in значение.splitlines():
        строка = строка.strip().lstrip("*").strip()
        if строка:
            return строка
    return ""


def документация_python(узел: Node, исходник: bytes) -> str:
    """Извлекает первую строку Python-docstring через безопасный literal_eval."""
    тело = узел.child_by_field_name("body")
    if тело is None or not тело.named_children:
        return ""
    выражение = тело.named_children[0]
    if выражение.type != "expression_statement" or not выражение.named_children:
        return ""
    литерал = выражение.named_children[0]
    if литерал.type not in {"string", "concatenated_string"}:
        return ""
    try:
        значение = ast.literal_eval(текст_узла(литерал, исходник))
    except (SyntaxError, ValueError):
        return ""
    return первая_строка(значение) if isinstance(значение, str) else ""


def очистить_js_комментарий(текст: str) -> str:
    """Преобразует JS-комментарий в краткую строку документации."""
    текст = текст.strip()
    if текст.startswith("/*") and текст.endswith("*/"):
        текст = текст[2:-2]
    elif текст.startswith("//"):
        текст = текст[2:]
    return первая_строка(текст)


def документация_js(узел: Node, исходник: bytes) -> str:
    """Извлекает первую строку строкового литерала или предшествующего комментария."""
    тело = узел.child_by_field_name("body")
    if тело is not None and тело.type == "statement_block" and тело.named_children:
        выражение = тело.named_children[0]
        if выражение.type == "expression_statement" and выражение.named_children:
            литерал = выражение.named_children[0]
            if литерал.type in {"string", "template_string"}:
                return первая_строка(
                    текст_узла(литерал, исходник).strip("'\"`")
                )

    предыдущий = узел.prev_named_sibling
    if предыдущий is not None and предыдущий.type == "comment":
        return очистить_js_комментарий(текст_узла(предыдущий, исходник))
    return ""


def имя_вызова(узел: Node, исходник: bytes) -> str | None:
    """Возвращает нормализованное имя вызываемой функции."""
    функция = узел.child_by_field_name("function")
    имя = краткое_имя(функция, исходник)
    if not имя:
        return None
    имя = имя.replace("?.", ".")
    if len(имя) > 200 or ДОПУСТИМОЕ_ИМЯ_ВЫЗОВА.fullmatch(имя) is None:
        return None
    return имя


def строковый_литерал(узел: Node | None, исходник: bytes) -> str | None:
    """Читает простой строковый аргумент Python/JavaScript без выполнения кода."""
    if узел is None or узел.type not in {"string", "template_string"}:
        return None
    текст = текст_узла(узел, исходник).strip()
    if узел.type == "template_string":
        if "${" in текст or not (текст.startswith("`") and текст.endswith("`")):
            return None
        return текст[1:-1]
    try:
        значение = ast.literal_eval(текст)
    except (SyntaxError, ValueError):
        if len(текст) >= 2 and текст[0] == текст[-1] and текст[0] in {"'", '"'}:
            значение = текст[1:-1]
        else:
            return None
    return значение if isinstance(значение, str) and значение else None


def mcp_инструмент(узел: Node, имя: str, исходник: bytes) -> str | None:
    """Опознает распространенные вызовы регистрации MCP-инструмента."""
    if имя.rsplit(".", maxsplit=1)[-1] not in РЕГИСТРАТОРЫ_MCP:
        return None
    аргументы = узел.child_by_field_name("arguments")
    if аргументы is None or not аргументы.named_children:
        return None
    return строковый_литерал(аргументы.named_children[0], исходник)


def добавить_отношение(
    граф: nx.DiGraph, источник: str, цель: str, отношение: str
) -> None:
    """Добавляет отношение в DiGraph без потери второго типа той же пары узлов."""
    данные = граф.get_edge_data(источник, цель, default={})
    отношения = list(данные.get("relations", []))
    if отношение not in отношения:
        отношения.append(отношение)
        отношения.sort()
    граф.add_edge(источник, цель, relations=отношения)


def анализировать_код(
    граф: nx.DiGraph,
    относительный_путь: str,
    язык: str,
    исходник: bytes,
) -> tuple[list[Вызов], int]:
    """Добавляет объявления и MCP-инструменты, возвращает отложенные вызовы."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        parser = get_parser(язык)
    дерево = parser.parse(исходник)
    вызовы: list[Вызов] = []
    ошибки = int(дерево.root_node.has_error)

    def посетить(
        узел: Node,
        область: tuple[str, ...],
        текущая_функция: str | None,
    ) -> None:
        if узел.type in ТИПЫ_КЛАССОВ.get(язык, set()):
            имя = имя_класса(узел, исходник)
            for ребенок in узел.named_children:
                посетить(ребенок, (*область, имя), текущая_функция)
            return

        if узел.type in ТИПЫ_ФУНКЦИЙ.get(язык, set()):
            имя = имя_функции(узел, исходник)
            полное_имя = ".".join((*область, имя))
            идентификатор = f"{относительный_путь}::{полное_имя}"
            документация = (
                документация_python(узел, исходник)
                if язык == "python"
                else документация_js(узел, исходник)
            )
            граф.add_node(
                идентификатор,
                id=идентификатор,
                type="function",
                args=аргументы_функции(узел, исходник),
                doc=документация,
            )
            добавить_отношение(
                граф, относительный_путь, идентификатор, "DEFINES"
            )
            for ребенок in узел.named_children:
                посетить(ребенок, (*область, имя), идентификатор)
            return

        if узел.type == "call":
            имя = имя_вызова(узел, исходник)
            if имя:
                вызовы.append(
                    Вызов(
                        источник=текущая_функция or относительный_путь,
                        файл=относительный_путь,
                        имя=имя,
                    )
                )
        elif узел.type == "call_expression":
            имя = имя_вызова(узел, исходник)
            if имя:
                вызовы.append(
                    Вызов(
                        источник=текущая_функция or относительный_путь,
                        файл=относительный_путь,
                        имя=имя,
                    )
                )
                if язык in {"javascript", "typescript"}:
                    инструмент = mcp_инструмент(узел, имя, исходник)
                    if инструмент:
                        идентификатор = f"mcp::{инструмент}"
                        граф.add_node(
                            идентификатор,
                            id=идентификатор,
                            type="mcp_tool",
                        )
                        добавить_отношение(
                            граф,
                            относительный_путь,
                            идентификатор,
                            "EXPOSES_TOOL",
                        )

        for ребенок in узел.named_children:
            посетить(ребенок, область, текущая_функция)

    посетить(дерево.root_node, (), None)
    return вызовы, ошибки


def разрешить_вызовы(граф: nx.DiGraph, вызовы: list[Вызов]) -> None:
    """Связывает вызовы с локальными, уникальными глобальными или внешними целями."""
    функции = [
        (идентификатор, атрибуты)
        for идентификатор, атрибуты in граф.nodes(data=True)
        if атрибуты.get("type") == "function"
        and not атрибуты.get("external", False)
    ]
    по_файлу_и_имени: dict[tuple[str, str], list[str]] = defaultdict(list)
    по_файлу_и_хвосту: dict[tuple[str, str], list[str]] = defaultdict(list)
    по_хвосту: dict[str, list[str]] = defaultdict(list)

    for идентификатор, _ in функции:
        файл, имя = идентификатор.split("::", maxsplit=1)
        хвост = имя.rsplit(".", maxsplit=1)[-1]
        по_файлу_и_имени[(файл, имя)].append(идентификатор)
        по_файлу_и_хвосту[(файл, хвост)].append(идентификатор)
        по_хвосту[хвост].append(идентификатор)

    for вызов in вызовы:
        нормализованное = вызов.имя.replace("?.", ".")
        хвост = нормализованное.rsplit(".", maxsplit=1)[-1]
        кандидаты = по_файлу_и_имени.get(
            (вызов.файл, нормализованное), []
        )
        if len(кандидаты) != 1:
            кандидаты = по_файлу_и_хвосту.get((вызов.файл, хвост), [])
        if len(кандидаты) != 1:
            кандидаты = по_хвосту.get(хвост, [])

        if len(кандидаты) == 1:
            цель = кандидаты[0]
        else:
            цель = f"external::{нормализованное}"
            граф.add_node(
                цель,
                id=цель,
                type="function",
                args=[],
                doc="",
                external=True,
            )
        добавить_отношение(граф, вызов.источник, цель, "CALLS")


def сериализовать_граф(
    граф: nx.DiGraph,
    корень: Path,
    ошибки_разбора: list[dict[str, str]],
) -> dict[str, object]:
    """Формирует детерминированный JSON-контракт графа."""
    узлы = []
    for идентификатор, атрибуты in sorted(
        граф.nodes(data=True), key=lambda элемент: элемент[0]
    ):
        данные = dict(атрибуты)
        данные.setdefault("id", идентификатор)
        узлы.append(данные)

    ребра = []
    for источник, цель, атрибуты in sorted(
        граф.edges(data=True), key=lambda элемент: (элемент[0], элемент[1])
    ):
        for отношение in атрибуты.get("relations", []):
            ребра.append(
                {"source": источник, "target": цель, "type": отношение}
            )

    return {
        "schema_version": "2.0",
        "root": str(корень),
        "parse_error_files": len(ошибки_разбора),
        "parse_errors": ошибки_разбора,
        "nodes": узлы,
        "edges": ребра,
    }


def записать_атомарно(путь: Path, данные: dict[str, object]) -> None:
    """Записывает JSON через временный файл и атомарную замену."""
    путь.parent.mkdir(parents=True, exist_ok=True)
    дескриптор, временное_имя = tempfile.mkstemp(
        prefix=f".{путь.name}.",
        suffix=".tmp",
        dir=путь.parent,
        text=True,
    )
    временный_путь = Path(временное_имя)
    try:
        with os.fdopen(дескриптор, "w", encoding="utf-8") as поток:
            json.dump(данные, поток, ensure_ascii=False, indent=2)
            поток.write("\n")
            поток.flush()
            os.fsync(поток.fileno())
        временный_путь.replace(путь)
    except BaseException:
        временный_путь.unlink(missing_ok=True)
        raise


def построить_граф(корень: Path) -> tuple[nx.DiGraph, int, list[dict[str, str]]]:
    """Сканирует рабочую область и возвращает граф с краткой статистикой."""
    граф = nx.DiGraph()
    все_вызовы: list[Вызов] = []
    файлов = 0
    ошибки_разбора: list[dict[str, str]] = []

    for путь, язык in исходные_файлы(корень):
        относительный_путь = путь.relative_to(корень).as_posix()
        граф.add_node(
            относительный_путь,
            id=относительный_путь,
            type="file",
            lang=язык,
        )
        файлов += 1
        if язык not in ТИПЫ_ФУНКЦИЙ:
            continue
        try:
            исходник = путь.read_bytes()
            вызовы, ошибка = анализировать_код(
                граф, относительный_путь, язык, исходник
            )
        except (OSError, ValueError) as exc:
            ошибки_разбора.append(
                {
                    "file": относительный_путь,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        все_вызовы.extend(вызовы)
        if ошибка:
            ошибки_разбора.append(
                {
                    "file": относительный_путь,
                    "reason": "Tree-sitter сообщил синтаксическую ошибку",
                }
            )

    разрешить_вызовы(граф, все_вызовы)
    return граф, файлов, ошибки_разбора


def main() -> int:
    """Создает JSON-граф и печатает только краткую итоговую статистику."""
    параметры = разобрать_аргументы()
    корень = параметры.root.expanduser().resolve()
    выход = параметры.output.expanduser()
    if not выход.is_absolute():
        выход = (Path.cwd() / выход).resolve()
    if not корень.is_dir():
        raise SystemExit(f"Корень проекта не найден: {корень}")

    граф, файлов, ошибки_разбора = построить_граф(корень)
    данные = сериализовать_граф(граф, корень, ошибки_разбора)
    записать_атомарно(выход, данные)

    print(
        "Граф V2 создан: "
        f"файлов={файлов}, узлов={len(данные['nodes'])}, "
        f"ребер={len(данные['edges'])}, "
        f"файлов_с_ошибками_разбора={len(ошибки_разбора)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
