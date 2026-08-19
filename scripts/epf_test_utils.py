#!/usr/bin/env python3
"""Общие проверки версии внешней обработки без привязки тестов к релизу."""

from __future__ import annotations

import re


VERSION_FUNCTION_RE = re.compile(
    r"Функция\s+Адапт_ВерсияОбработки\(\)\s+Экспорт\s+"
    r"Возврат\s+\"(?P<version>v25-(?P<cycle>\d+)\.(?P<revision>\d+))\";\s+"
    r"КонецФункции",
    re.DOTALL,
)


def current_processing_version(object_text: str, minimum_revision: int) -> str:
    """Возвращает текущую версию и проверяет, что это не старее контракта теста."""

    matches = list(VERSION_FUNCTION_RE.finditer(object_text))
    if len(matches) != 1:
        raise AssertionError(
            "expected exactly one Адапт_ВерсияОбработки function, "
            f"found {len(matches)}"
        )
    match = matches[0]
    cycle = int(match.group("cycle"))
    revision = int(match.group("revision"))
    if (cycle, revision) < (122, minimum_revision):
        raise AssertionError(
            f"processing version {cycle}.{revision} is older than required "
            f"122.{minimum_revision}"
        )
    return match.group("version")


def version_return_marker(version: str) -> str:
    return f'Возврат "{version}";'


def require_form_version(form_xml_text: str, version: str) -> None:
    if version not in form_xml_text:
        raise AssertionError(
            f"main form title does not contain current processing version {version}"
        )
