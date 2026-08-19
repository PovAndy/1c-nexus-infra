#!/usr/bin/env python3
"""Статический контракт ReadOnly Preview [24.6]."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from epf_test_utils import current_processing_version, require_form_version


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"
TARGET_MANAGER = (
    ROOT
    / "context/config-dumps/target_1_0_36_14_full"
    / "Catalogs/ОснованияУвольнения/Ext/ManagerModule.bsl"
)
TARGET_TEMPLATE = (
    ROOT
    / "context/config-dumps/target_1_0_36_14_full"
    / "Catalogs/ОснованияУвольнения/Templates/ОснованияУвольненияПоТКРФ/Ext/Template.txt"
)


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
    manager_text = TARGET_MANAGER.read_text(encoding="utf-8-sig")
    template_text = TARGET_TEMPLATE.read_text(encoding="utf-8-sig")

    version = current_processing_version(object_text, 125)
    require_form_version(form_xml_text, version)

    fingerprint = function_body(
        object_text,
        "Адапт_ЭтоUUIDИсточника01ОснованийУвольнения",
    )
    preview = function_body(
        object_text,
        "Адапт_СформироватьPreviewДублейОснованийУвольнения36_14",
    )
    combined = fingerprint + preview

    for forbidden in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "УстановитьНовыйКод(",
        "ОбщегоНазначения.ЗаменитьСсылки",
        "ОбновлениеИнформационнойБазы.ЗаписатьОбъект",
        "ВыполнитьПрямойSQL",
        ".Удалить(",
    ):
        if forbidden in combined:
            fail(f"[24.6] contains a mutation: {forbidden}")

    for required in (
        "Справочник.ОснованияУвольнения",
        "Основания.Наименование КАК Наименование",
        "Основания.Предопределенный КАК Предопределенный",
        "Основания.ТекстОснования КАК ТекстОснования",
        "Основания.ПричинаУвольненияПФР КАК ПричинаУвольненияПФР",
        "PREDEFINED_EXACT",
        "SOURCE_X1_01_UUID_FINGERPRINT",
        "9a7b-11ee-9374-c018505cf1e0",
        "КандидатыПредопределенные.Количество() = 1",
        "КандидатыИсточника01.Количество() = 1",
        "НайтиПоСсылкам(НеканоническиеСсылки)",
        "Адапт_ЭтоКонтурПодготовкиОбновленияТолькоЧтение()",
        "DISMISSAL_BASES_36_14_PREVIEW_V1",
        "п. 2 ч. 1 ст. 77",
        "Адапт_ДобавитьДлительностьВОтчет",
        "Адапт_СообщитьПрогресс(100",
    ):
        if required not in combined:
            fail(f"[24.6] safety fragment is missing: {required}")

    if "КандидатыПредопределенные[0]" not in preview:
        fail("predefined canon is not selected after the exact-one gate")
    if "КандидатыИсточника01[0]" not in preview:
        fail("source canon is not selected after the exact-one gate")
    if 'Результат.Вставить("План"' in preview:
        fail("preview must not return ValueTable through XDTO/temp storage")

    operation = "PreviewДублейОснованийУвольнения36_14V125НаСервере"
    if operation not in object_text or operation not in form_text:
        fail("[24.6] unique long-operation route is missing")
    if "Процедура PreviewДублейОснованийУвольнения36_14(Команда)" not in form_text:
        fail("[24.6] client handler is missing")
    if "Функция PreviewДублейОснованийУвольнения36_14НаСервере()" not in form_text:
        fail("[24.6] server wrapper is missing")
    if form_text.count('ИмяСценария = "preview-dismissal-bases-36-14"') != 2:
        fail("[24.6] client/server autorun routes are missing")

    button = find_named(
        form_root,
        "Button",
        "PreviewДублейОснованийУвольнения36_14Тесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.PreviewДублейОснованийУвольнения36_14":
        fail("[24.6] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "PreviewДублейОснованийУвольнения36_14",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "PreviewДублейОснованийУвольнения36_14":
        fail("[24.6] command action is incorrect")

    if 'Результат.Добавить("Наименование")' not in manager_text:
        fail("target 36.14 natural-key evidence is missing")
    root = ET.fromstring(template_text)
    titles = [item.attrib.get("Title", "") for item in root]
    if len(titles) != 108 or len({title.casefold() for title in titles}) != 108:
        fail("target 36.14 template must contain 108 unique titles")
    if titles.count("п. 2 ч. 1 ст. 77") != 1:
        fail("failing title must occur exactly once in target template")

    print(
        f"PASS: {version}; [24.6]=readonly-MergedBase+MergedBase; "
        "natural-key=active-name; canon=predefined|exact-x1_01; "
        "reference_titles=108; xdto=value-table-not-returned"
    )


if __name__ == "__main__":
    main()
