"""Оценивает только релевантные BSL/XML-изменения и возвращает блокирующий сигнал."""

from __future__ import annotations

import json
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any, Callable

try:
    from .common import is_runtime_path, resolve_target
except ImportError:  # прямой запуск скрипта
    from common import is_runtime_path, resolve_target


def _evaluate_bsl(path: Path) -> dict[str, Any]:
    try:
        from scripts.eval_bsl_candidate import evaluate_candidate
    except ModuleNotFoundError:
        from eval_bsl_candidate import evaluate_candidate

    return evaluate_candidate(path)


def evaluate_target(
    file_path: str | None,
    *,
    bsl_evaluator: Callable[[Path], dict[str, Any]] = _evaluate_bsl,
) -> tuple[int, str]:
    """Возвращает 0 для безопасного/нерелевантного файла, 2 для доказанного дефекта."""
    # Самый частый путь не должен выполнять resolve(), stat() или импорт оценщика.
    # Расширение — только предварительный фильтр; проверка границ пути остаётся ниже
    # для файлов, которые действительно будут разбираться.
    suffix = Path(file_path or "").suffix.casefold()
    if suffix not in {".bsl", ".xml"}:
        return 0, ""
    target = resolve_target(file_path)
    if target is None or is_runtime_path(target) or not target.is_file():
        return 0, ""
    if suffix == ".xml":
        try:
            element_tree.parse(target)
        except (OSError, element_tree.ParseError) as exc:
            return 2, json.dumps({"kind": "xml_syntax", "detail": str(exc)[:300]}, ensure_ascii=False)
        return 0, ""
    result = bsl_evaluator(target)
    cost = result.get("cost")
    if result.get("status") != "PASS" or not isinstance(cost, int) or cost > 0:
        return 2, json.dumps(
            {
                "kind": "bsl_candidate_rejected",
                "cost": cost,
                "status": result.get("status", "unknown"),
                "issues": result.get("issues", [])[:8],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return 0, ""
