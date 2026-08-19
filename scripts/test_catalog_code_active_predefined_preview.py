#!/usr/bin/env python3
"""Static safety contract for [23.4] active predefined-code groups."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"


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


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8-sig")
    version = current_processing_version(object_text, 111)
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_root = ET.fromstring(FORM_XML.read_text(encoding="utf-8-sig"))

    if version_return_marker(version) not in object_text:
        fail("unexpected processing version")

    function_name = (
        "Адапт_СформироватьPreviewАктивныхПредопределенныхКодовСправочников"
    )
    preview = function_body(object_text, function_name)
    group_query = function_body(
        object_text,
        "Адапт_ТаблицаЭлементовГруппыДублейКодовСправочникаДляАудита",
    )

    for forbidden in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "УстановитьНовыйКод(",
        "УдалитьОбъект(",
        "НайтиПоСсылкам(",
        "ВыполнитьПакет(",
        "ДокументыГруппы[0]",
    ):
        if forbidden in preview or forbidden in group_query:
            fail(f"write/arbitrary/risky operation is present in [23.4]: {forbidden}")

    required = (
        'ОжидаетсяГрупп = 19',
        'MD5Классификации23_3 = "1CFF9261DAE11203F60F658785679850"',
        "ПредопределенноеЗначение(",
        "CANON_PLATFORM_ACTIVE",
        "STOP_CANON_MISMATCH",
        "STOP_CANON_RESOLVE_ERROR",
        "STOP_MARKED_PREDEFINED",
        "REVIEW_ONE_CANON_WITH_ACTIVE_COPIES",
        "REVIEW_MULTIPLE_ACTIVE_PREDEFINED",
        "CATALOG_ACTIVE_PREDEFINED_CODE_GROUPS_V1",
        "PASS_PREVIEW",
        "STOP_UPDATE_GATE",
        "исходными x1_XX",
        "Адапт_ДобавитьДлительностьВОтчет",
        "Адапт_СообщитьПрогресс",
    )
    for fragment in required:
        if fragment not in preview:
            fail(f"required [23.4] safety fragment is missing: {fragment}")
    for field in (
        "Ссылка КАК Ссылка",
        "Код КАК Код",
        "ПометкаУдаления КАК ПометкаУдаления",
        "Предопределенный КАК Предопределенный",
        "ИмяПредопределенныхДанных",
    ):
        if field not in group_query:
            fail(f"exact group query field is missing: {field}")
    if "ПРЕДСТАВЛЕНИЕ(" in group_query:
        fail("exact group query must not calculate a nonessential presentation")
    if 'Символы.ПС + "|' in group_query or '+ "| ЭлементыСправочника.' in group_query:
        fail("dynamic query fragments must not contain literal continuation bars")
    for query_fragment in (
        'Символы.ПС + "ИЗ"',
        'Символы.ПС + "ГДЕ"',
        'Символы.ПС + "УПОРЯДОЧИТЬ ПО"',
        'Символы.ПС + " И ЭлементыСправочника."',
    ):
        if query_fragment not in group_query:
            fail(f"safe dynamic query fragment is missing: {query_fragment}")
    for diagnostic_fragment in (
        "ОшибкиЗапросовПодробно",
        "ОписаниеОшибки()",
        '" Ошибки запросов"',
        "Строка(ЭлементГруппы.Ссылка)",
    ):
        if diagnostic_fragment not in preview:
            fail(f"query diagnostics fragment is missing: {diagnostic_fragment}")
    if 'Результат.Вставить("Таблица' in preview:
        fail("[23.4] must not return ValueTable through XDTO")

    wrapper = "PreviewАктивныхПредопределенныхКодовСправочниковНаСервере"
    if wrapper not in form_text:
        fail("[23.4] server wrapper is missing")
    if f'КодОперации =\n\t\t"{wrapper}" Тогда' not in object_text:
        fail("[23.4] long-operation dispatcher branch is missing")
    if function_name not in form_text:
        fail("[23.4] form wrapper does not call the object method")

    button = find_named(
        form_root,
        "Button",
        "PreviewАктивныхПредопределенныхКодовСправочниковТесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    expected_command = (
        "Form.Command.PreviewАктивныхПредопределенныхКодовСправочников"
    )
    if command_name != expected_command:
        fail("[23.4] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "PreviewАктивныхПредопределенныхКодовСправочников",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "PreviewАктивныхПредопределенныхКодовСправочников":
        fail("[23.4] command action is wrong")

    group = find_named(form_root, "UsualGroup", "ГруппаЭтап23УникальныеПоля")
    if not any(child is button for child in group.iter()):
        fail("[23.4] button is outside the compact [23] group")

    print(
        f"PASS: {version}; [23.4]=readonly+exact-members+platform-canon; "
        "stable-md5; XDTO-safe; background_dispatch=closed; compact_form_wiring=OK"
    )


if __name__ == "__main__":
    main()
