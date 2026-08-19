#!/usr/bin/env python3
"""Static safety contract for [23.3] catalog-code REVIEW classification."""

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

    function_name = "Адапт_СформироватьКлассификациюReviewКодовСправочников"
    classification = function_body(object_text, function_name)
    helper = function_body(
        object_text,
        "Адапт_ТаблицаДублейКодовСправочникаДляАудита",
    )

    for forbidden in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "УстановитьНовыйКод(",
        "УдалитьОбъект(",
        "НайтиПоСсылкам(",
        "ВыполнитьПакет(",
    ):
        if forbidden in classification or forbidden in helper:
            fail(f"write/risky operation is present in [23.3]: {forbidden}")

    required = (
        "CATALOG_CODE_REVIEW_CLASSIFICATION_V1",
        "ACTIVE_BUSINESS_REVIEW",
        "ACTIVE_WITH_PREDEFINED_REVIEW",
        "ALL_MARKED_NONPREDEFINED_REVIEW",
        "STOP_ALL_MARKED_WITH_PREDEFINED",
        "STOP_MARKED_PREDEFINED",
        "READY_TAIL_UNEXPECTED",
        "PASS_CLASSIFIED",
        "STOP_UPDATE_GATE",
        "ВсегоАктивныхСПредопределенными = 0",
        "ВсегоПолностьюПомеченныхСПредопределенными = 0",
        "ВсегоREADY = 0",
        "Массовая перенумерация",
        "Адапт_ДобавитьДлительностьВОтчет",
        "Адапт_СообщитьПрогресс",
    )
    for fragment in required:
        if fragment not in classification:
            fail(f"required [23.3] safety fragment is missing: {fragment}")
    if "КАК Предопределенных" not in helper:
        fail("[23.3] cannot classify active predefined collisions")
    if 'Результат.Вставить("Таблица' in classification:
        fail("[23.3] must not return ValueTable through XDTO")

    wrapper = "КлассификацияReviewКодовСправочниковНаСервере"
    if wrapper not in form_text:
        fail("[23.3] server wrapper is missing")
    if f'КодОперации =\n\t\t"{wrapper}" Тогда' not in object_text:
        fail("[23.3] long-operation dispatcher branch is missing")
    if function_name not in form_text:
        fail("[23.3] form wrapper does not call the object method")

    button = find_named(
        form_root,
        "Button",
        "КлассификацияReviewКодовСправочниковТесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.КлассификацияReviewКодовСправочников":
        fail("[23.3] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "КлассификацияReviewКодовСправочников",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "КлассификацияReviewКодовСправочников":
        fail("[23.3] command action is wrong")

    group = find_named(form_root, "UsualGroup", "ГруппаЭтап23УникальныеПоля")
    if not any(child is button for child in group.iter()):
        fail("[23.3] button is outside the compact [23] group")

    print(
        f"PASS: {version}; [23.3]=readonly+full-group-md5; "
        "active/predefined/all-marked=classified; XDTO-safe; "
        "background_dispatch=closed; compact_form_wiring=OK"
    )


if __name__ == "__main__":
    main()
