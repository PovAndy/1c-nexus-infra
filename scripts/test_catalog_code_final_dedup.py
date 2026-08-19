#!/usr/bin/env python3
"""Static safety contract for [23.5]-[23.6] final catalog-code dedup."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"
SOURCE_AUDIT = ROOT / "temp/122.108/active-code-source-audit.txt"


def fail(message: str) -> None:
    raise AssertionError(message)


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"Функция\s+{re.escape(name)}\([^)]*\)(?:\s+Экспорт)?"
        rf"(?P<body>.*?)КонецФункции",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        fail(f"function is missing: {name}")
    return match.group("body")


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def find_named(root: ET.Element, tag: str, name: str) -> ET.Element:
    for element in root.iter():
        if local_name(element) == tag and element.get("name") == name:
            return element
    fail(f"form node is missing: {tag}.{name}")


def bsl_call_argument_counts(source: str, function_name: str) -> list[int]:
    """Count top-level arguments of BSL calls, ignoring commas in strings."""

    counts: list[int] = []
    pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(")
    for match in pattern.finditer(source):
        position = match.end()
        depth = 1
        commas = 0
        has_content = False
        in_string = False
        while position < len(source) and depth > 0:
            char = source[position]
            if in_string:
                if char == '"':
                    if position + 1 < len(source) and source[position + 1] == '"':
                        position += 2
                        continue
                    in_string = False
                position += 1
                continue
            if char == '"':
                in_string = True
                has_content = True
            elif char == "(":
                depth += 1
                has_content = True
            elif char == ")":
                depth -= 1
                if depth == 0:
                    counts.append(0 if not has_content else commas + 1)
                    break
            elif char == "," and depth == 1:
                commas += 1
            elif not char.isspace():
                has_content = True
            position += 1
        if depth != 0:
            fail(f"unclosed BSL call: {function_name} at {match.start()}")
    return counts


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8-sig")
    version = current_processing_version(object_text, 111)
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_root = ET.fromstring(FORM_XML.read_text(encoding="utf-8-sig"))

    if version_return_marker(version) not in object_text:
        fail("unexpected processing version")

    split_argument_counts = bsl_call_argument_counts(object_text, "СтрРазделить")
    if not split_argument_counts or min(split_argument_counts) < 2:
        fail(
            "every СтрРазделить call must contain the mandatory delimiter; "
            f"argument counts={split_argument_counts}"
        )

    preview_name = (
        "Адапт_СформироватьPreviewФинальнойДедупликацииКодовСправочников"
    )
    fix_name = "Адапт_ИсправитьФинальнуюДедупликациюКодовСправочников"
    preview = function_body(object_text, preview_name)
    fix = function_body(object_text, fix_name)
    target_map = function_body(
        object_text,
        "Адапт_КартаЦелевыхКодовПредопределенных36_14",
    )

    for forbidden in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "УдалитьОбъект(",
        "ЗаменитьСсылки(",
        "ВыполнитьПакет(",
        "ДокументыГруппы[0]",
    ):
        if forbidden in preview:
            fail(f"[23.5] is not ReadOnly: {forbidden}")

    for fragment in (
        "Групп = 39",
        "Элементов = 6529",
        "План.Количество() = 6520",
        "Технических = 6503",
        "Предопределенных = 17",
        "КЕЕП = 9",
        "CATALOG_FINAL_DEDUP_V1",
        "TECHNICAL_BASE36",
        "PREDEFINED_TARGET",
        "ПредопределенноеЗначение(",
        "Адапт_КартаЦелевыхКодовПредопределенных36_14",
        "Адапт_ДобавитьДлительностьВОтчет",
        "Адапт_СообщитьПрогресс",
    ):
        if fragment not in preview:
            fail(f"required [23.5] fragment is missing: {fragment}")

    if target_map.count("|") != 54:
        fail("target 36.14 map must contain exactly 27 catalog/name/code rows")
    for target in (
        "ЕдиныйНалоговыйПлатеж|000000002",
        "ТипДокументаДляОтветаНаПодзапрос|000000022",
        "РезервыПоОплатеТруда|00030",
        "ПриобретениеМалоценногоОборудованияИЗапасов|000000013",
    ):
        if target not in target_map:
            fail(f"target 36.14 code is missing: {target}")

    for fragment in (
        "Адапт_ЭтоКонтурЗагрузка1ДляПилотаНумерации()",
        "ОжидаетсяОпераций = 6520",
        "ОжидаетсяТехнических = 6503",
        "ОжидаетсяПредопределенных = 17",
        "PREFLIGHT_STABLE=PASS",
        "НачатьТранзакцию()",
        "ОтменитьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОбъектСправочника.Код = СтрокаПлана.ЦелевойКод",
        "ОбъектСправочника.ОбменДанными.Загрузка = Истина",
        "STOP_TARGET_OCCUPIED",
        "STOP_PREDEFINED_CANON",
        "СокрЛП(ФактическийКодПосле)",
        "СокрЛП(СтрокаПлана.ЦелевойКод)",
        "expected_length=",
        "actual_length=",
        "STOP_ROLLBACK",
        "POSTCONTROL_STABLE",
    ):
        if fragment not in fix:
            fail(f"required [23.6] safety fragment is missing: {fragment}")

    if fix.count("ЗафиксироватьТранзакцию()") != 1:
        fail("[23.6] must have exactly one atomic commit")
    if fix.count(preview_name + "(") < 4:
        fail("[23.6] must have two preflights and two postcontrols")
    for forbidden in (
        "УдалитьОбъект(",
        "ЗаменитьСсылки(",
        "ВыполнитьПакет(",
        "УстановитьПометкуУдаления(",
        "РежимЗаписиДокумента",
    ):
        if forbidden in fix:
            fail(f"forbidden [23.6] operation/source is present: {forbidden}")
    source_alias_pattern = "x" + "1_" + r"\d{2}"
    if re.search(source_alias_pattern, fix):
        fail("[23.6] must not contain a local source-database alias")

    source_audit = SOURCE_AUDIT.read_text(encoding="utf-8-sig")
    expected_audit = (
        "targets=119|resolved=119|ambiguous=0|not_found=0|"
        "query_errors=0|connection_errors=0"
    )
    if expected_audit not in source_audit:
        fail("17-source ReadOnly audit is absent or not PASS")

    for wrapper in (
        "PreviewФинальнойДедупликацииКодовСправочниковНаСервере",
        "ИсправитьФинальнуюДедупликациюКодовСправочниковНаСервере",
    ):
        if wrapper not in form_text:
            fail(f"form server wrapper is missing: {wrapper}")
        if f'КодОперации =\n\t\t"{wrapper}" Тогда' not in object_text:
            fail(f"background dispatcher branch is missing: {wrapper}")

    for name in (
        "PreviewФинальнойДедупликацииКодовСправочников",
        "ИсправитьФинальнуюДедупликациюКодовСправочников",
    ):
        command = find_named(form_root, "Command", name)
        action = next(
            (child.text for child in command if local_name(child) == "Action"),
            None,
        )
        if action != name:
            fail(f"command action is wrong: {name}")

    final_group = find_named(form_root, "UsualGroup", "ГруппаЭтап23ФинальнаяПартия")
    if sum(1 for item in final_group.iter() if local_name(item) == "Button") != 2:
        fail("[23.5]-[23.6] must be grouped in one compact two-button row")
    parent_group = find_named(form_root, "UsualGroup", "ГруппаЭтап23УникальныеПоля")
    group_mode = next(
        (child.text for child in parent_group if local_name(child) == "Group"),
        None,
    )
    if group_mode != "Vertical":
        fail("[23] parent group must be vertical to prevent an off-screen row")

    print(
        f"PASS: {version}; [23.5]=readonly exact plan 39/6529/6520; "
        "[23.6]=single-transaction code-only fix+double postcontrol; "
        "sources=119/119 readonly; target36.14=27; compact_form=OK"
    )


if __name__ == "__main__":
    main()
