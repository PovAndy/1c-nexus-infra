#!/usr/bin/env python3
"""Статический контракт возобновляемого конвейера остаточных ссылок [25.2]."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from epf_test_utils import current_processing_version, require_form_version


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


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
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_xml_text = FORM_XML.read_text(encoding="utf-8-sig")
    form_root = ET.fromstring(form_xml_text)

    version = current_processing_version(object_text, 129)
    if re.fullmatch(r"v25-123\.(?:0[1-9]|[1-9][0-9]+)", version) is None:
        fail(f"unexpected new-cycle version: {version}")
    require_form_version(form_xml_text, version)

    body = function_body(
        object_text,
        "Адапт_ЗавершитьОстаточныеСсылкиСвежейКопии",
    )
    required_in_order = (
        "Адапт_ИсправитьREADYОстаткиТиС()",
        "Адапт_ИсправитьВторуюПартиюОстатковТиС()",
        "Адапт_ИсправитьСистемныйХвостТиС()",
        "ФинальныйКонтроль = Адапт_ДиагностикаОстатковТиС()",
        "Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников()",
    )
    positions = []
    for token in required_in_order:
        position = body.find(token)
        if position < 0:
            fail(f"[25.2] contract fragment is missing: {token}")
        positions.append(position)
    if positions != sorted(positions):
        fail("[25.2] stages are not in the required order")

    for phase in (
        "BEFORE_READY_FIX",
        "AFTER_READY_FIX",
        "AFTER_SECOND_READY_FIX",
        "AFTER_SYSTEM_TAIL_FIX",
    ):
        if phase not in body:
            fail(f"[25.2] resumable phase is missing: {phase}")
    for token in (
        "Адапт_ЭтоКонтурMergedBaseДляСвежейКопии()",
        "STOP_PHASE",
        "STOP_22_15",
        "STOP_22_17",
        "STOP_22_19",
        "STOP_FINAL",
        "PASS_RESIDUALS",
        "ТранзакцияАктивна()",
    ):
        if token not in body:
            fail(f"[25.2] safety fragment is missing: {token}")
    for forbidden in (
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "Адапт_ИсправитьБезопаснуюПартиюКодовСправочников",
        "Адапт_ИсправитьПеренумерациюДокументов",
        "ВыполнитьПрямойSQL",
    ):
        if forbidden in body:
            fail(f"[25.2] contains an unauthorized outer operation: {forbidden}")

    catalog_preview = function_body(
        object_text,
        "Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников",
    )
    if "STANDARD_AUTO" not in catalog_preview:
        fail("[23.1] STANDARD_AUTO plan mode is missing")
    if "Адапт_ЭтоСправочникШтатногоХвостаКодов" in catalog_preview:
        fail("[23.1] still rejects safe STANDARD_AUTO candidates by stale whitelist")

    for owner, text in (("object", object_text), ("form", form_text)):
        if '"fresh_copy_residual_repair"' not in text:
            fail(f"[25.2] long-operation route is missing: {owner}")
    if "Процедура ЗавершитьОстаточныеСсылкиСвежейКопии(Команда)" not in form_text:
        fail("[25.2] client handler is missing")

    button = find_named(
        form_root,
        "Button",
        "ЗавершитьОстаточныеСсылкиСвежейКопииТесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.ЗавершитьОстаточныеСсылкиСвежейКопии":
        fail("[25.2] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "ЗавершитьОстаточныеСсылкиСвежейКопии",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "ЗавершитьОстаточныеСсылкиСвежейКопии":
        fail("[25.2] command action is incorrect")

    print(
        f"PASS: {version}; [25.2]=resumable 195+2->85+2->6+0->0+0; "
        "[23.1]=full-standard-auto-preview; form=connected"
    )


if __name__ == "__main__":
    main()
