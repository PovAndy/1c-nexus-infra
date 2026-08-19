#!/usr/bin/env python3
"""Статический контракт массового ReadOnly-аудита свежей копии [25.0]."""

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

    strict_guard = function_body(
        object_text,
        "Адапт_ЭтоКонтурMergedBaseДляСвежейКопии",
    )
    for token in (';ref=""MergedBase"";', ";ref=MergedBase;"):
        if token not in strict_guard:
            fail(f"MergedBase token is missing: {token}")
    for forbidden in ("MergedBase", "ServedBase", "НачатьТранзакцию", ".Записать("):
        if forbidden in strict_guard:
            fail(f"fresh-copy guard is not isolated: {forbidden}")
    readonly_guard = function_body(
        object_text,
        "Адапт_ЭтоКонтурMergedBaseДляСвежейКопииТолькоЧтение",
    )
    if "Адапт_ЭтоКонтурMergedBaseДляСвежейКопии()" not in readonly_guard:
        fail("ReadOnly guard must delegate to the strict MergedBase identity guard")

    dispatcher = function_body(
        object_text,
        "Адапт_ВыполнитьЭтапПолногоReadOnlyАудитаСвежейКопии",
    )
    audit = function_body(
        object_text,
        "Адапт_ПолныйReadOnlyАудитСвежейКопии",
    )
    combined = dispatcher + audit

    required_calls = (
        "Адапт_СформироватьPreviewИсправленияНовыхСчетчиков()",
        "Адапт_СформироватьАвтоконтрольДокументныхПакетовПерерасчетовИПУ()",
        "Адапт_PreflightАвтоконвейераТиС()",
        "Адапт_ДиагностикаОстатковТиС()",
        "Адапт_КомплексныйReadOnlyКонтрольНумерацииДокументов()",
        "Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников()",
        "Адапт_СформироватьПредконтрольОбновления36_14()",
        "Адапт_СформироватьPreviewКонсолидацииРегламентированныхОтчетов36_14()",
        "Адапт_СформироватьPreviewДублейПричинУвольненияПФР36_14()",
        "Адапт_СформироватьPreviewДублейОснованийУвольнения36_14()",
    )
    for call in required_calls:
        if dispatcher.count(call) != 1:
            fail(f"ReadOnly stage call must occur exactly once: {call}")

    for forbidden in (
        "Адапт_Исправить",
        "Адапт_АвтоконвейерИсправленияТиС",
        "Адапт_Создать",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        ".Записать(",
        "УстановитьНовыйКод(",
        "ОбщегоНазначения.ЗаменитьСсылки",
        "ВыполнитьПрямойSQL",
    ):
        if forbidden in combined:
            fail(f"[25.0] contains a mutation path: {forbidden}")

    for required in (
        "Адапт_ЭтоКонтурMergedBaseДляСвежейКопииТолькоЧтение()",
        "Результат.БылиИзменения = Ложь",
        "ТехническихОшибок",
        "ЭтаповСНаходками",
        "AUDIT_COMPLETE",
        "STOP_AUDIT",
        "динамический план массового исправления [25.1]",
        "Адапт_ДобавитьДлительностьВОтчет",
        "Адапт_СообщитьПрогресс(100",
    ):
        if required not in audit:
            fail(f"[25.0] contract fragment is missing: {required}")
    if audit.count("Этапы.Добавить(") != 10:
        fail("[25.0] must contain exactly ten independent stages")

    for route_owner, route_text in (
        ("object dispatcher", object_text),
        ("form server dispatcher", form_text),
    ):
        if '"fresh_copy_readonly_audit"' not in route_text:
            fail(f"fresh-copy long-operation route is missing: {route_owner}")
    if "Процедура ПолныйReadOnlyАудитСвежейКопии(Команда)" not in form_text:
        fail("[25.0] client handler is missing")

    button = find_named(form_root, "Button", "ПолныйReadOnlyАудитСвежейКопииТесты")
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.ПолныйReadOnlyАудитСвежейКопии":
        fail("[25.0] button is wired to the wrong command")
    command = find_named(form_root, "Command", "ПолныйReadOnlyАудитСвежейКопии")
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "ПолныйReadOnlyАудитСвежейКопии":
        fail("[25.0] command action is incorrect")
    group = find_named(form_root, "UsualGroup", "ГруппаЭтап25СвежаяКопия")
    group_mode = next(
        (child.text for child in group if local_name(child) == "Group"),
        None,
    )
    if group_mode != "AlwaysHorizontal":
        fail("[25] mass-pipeline group must remain compact and horizontal")

    print(
        f"PASS: {version}; [25.0]=MergedBase-only-readonly; stages=10; "
        "writes=0; background-route=connected; form=connected"
    )


if __name__ == "__main__":
    main()
