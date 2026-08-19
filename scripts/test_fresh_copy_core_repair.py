#!/usr/bin/env python3
"""Статический контракт первого массового этапа свежей копии [25.1]."""

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
    require_form_version(form_xml_text, version)
    body = function_body(
        object_text,
        "Адапт_ПервыйМассовыйЭтапВосстановленияСвежейКопии",
    )

    required = (
        "Адапт_ЭтоКонтурMergedBaseДляСвежейКопии()",
        "Адапт_PreflightАвтоконвейераТиС()",
        "Адапт_АвтоконвейерИсправленияТиС(ПутьККарте)",
        "Адапт_ДиагностикаОстатковТиС()",
        "Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников()",
        "ТранзакцияАктивна()",
        "STOP_PREFLIGHT",
        "STOP_CORE",
        "PASS_CORE",
        "ОстаткиТребуютПродолжения",
        "Адапт_ДобавитьДлительностьВОтчет",
    )
    for token in required:
        if token not in body:
            fail(f"[25.1] contract fragment is missing: {token}")

    for forbidden in (
        "Адапт_ИсправитьПеренумерациюДокументов",
        "Адапт_ИсправитьБезопаснуюПартиюКодовСправочников",
        "Адапт_ИсправитьФинальнуюДедупликациюКодовСправочников",
        "Адапт_ИсправитьКарантинРегламентированныхОтчетов36_14",
        "Адапт_ИсправитьКарантинПричинУвольненияСФР36_14",
        "Адапт_ИсправитьКарантинОснованийУвольнения36_14",
        "Адапт_ИсправитьНовыеСчетчики",
        "Адапт_СоздатьПерерасчеты",
        "ВыполнитьПрямойSQL",
    ):
        if forbidden in body:
            fail(f"[25.1] scope expanded outside core TIS: {forbidden}")

    for owner, text in (("object", object_text), ("form", form_text)):
        if '"fresh_copy_core_repair"' not in text:
            fail(f"[25.1] long-operation route is missing: {owner}")
    if "Процедура ПервыйМассовыйЭтапВосстановленияСвежейКопии(Команда)" not in form_text:
        fail("[25.1] client handler is missing")
    if "Исходные x1_XX остаются только для чтения" not in form_text:
        fail("[25.1] confirmation must state the donor read-only boundary")

    button = find_named(
        form_root,
        "Button",
        "ПервыйМассовыйЭтапВосстановленияСвежейКопииТесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.ПервыйМассовыйЭтапВосстановленияСвежейКопии":
        fail("[25.1] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "ПервыйМассовыйЭтапВосстановленияСвежейКопии",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "ПервыйМассовыйЭтапВосстановленияСвежейКопии":
        fail("[25.1] command action is incorrect")

    print(
        f"PASS: {version}; [25.1]=MergedBase-core-only; "
        "preflight+pipeline+residual+catalog-preview; form=connected"
    )


if __name__ == "__main__":
    main()
