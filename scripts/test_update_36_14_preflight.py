#!/usr/bin/env python3
"""Статический контракт ReadOnly-предконтроля обновления 36.14."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from epf_test_utils import current_processing_version, require_form_version


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"
UPDATE_MODULE = (
    ROOT
    / "context/config-dumps/target_1_0_36_14_full"
    / "DataProcessors/ОбновлениеРегламентированнойОтчетности/Ext/ObjectModule.bsl"
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


def procedure_body(source: str, name: str) -> str:
    match = re.search(
        rf"Процедура\s+{re.escape(name)}\([^)]*\)(?:\s+Экспорт)?"
        rf"(?P<body>.*?)КонецПроцедуры",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        fail(f"procedure is missing: {name}")
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
    update_text = UPDATE_MODULE.read_text(encoding="utf-8-sig")

    version = current_processing_version(object_text, 112)
    require_form_version(form_xml_text, version)

    preflight = function_body(
        object_text,
        "Адапт_СформироватьПредконтрольОбновления36_14",
    )
    for forbidden in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "УстановитьНовыйКод(",
        "ВыполнитьПакет(",
        "ОбщегоНазначения.ЗаменитьСсылки",
    ):
        if forbidden in preflight:
            fail(f"[24.1] contains a mutation: {forbidden}")

    for required in (
        "Адапт_ЭтоКонтурПодготовкиОбновленияТолькоЧтение()",
        "UPDATE_36_14_REGREPORTS_PREFLIGHT_V2",
        "Отчеты.Предопределенный КАК Предопределенный",
        "Отчеты.ИмяПредопределенныхДанных КАК ИмяПредопределенныхДанных",
        "Отчеты.ИсточникОтчета КАК ИсточникОтчета",
        "DUP_CODE|",
        "DUP_SOURCE|",
        "DUP_GROUP|",
        "EMPTY_SOURCE|",
        "Адапт_UUIDСтрокаИзСсылки(",
        "Адапт_КонтрольнаяСуммаСтрокой(",
        "Адапт_ДобавитьДлительностьВОтчет",
        "Адапт_СообщитьПрогресс(100",
        "STOP_QUERY_REGISTRY",
        "STOP_QUERY_CODE",
        "STOP_QUERY_SOURCE",
        "STOP_QUERY_GROUP",
        "STOP_QUERY_EMPTY_SOURCE",
    ):
        if required not in preflight:
            fail(f"[24.1] safety fragment is missing: {required}")
    if "НЕ Отчеты.ПометкаУдаления\n\t|СГРУППИРОВАТЬ ПО\n\t| Отчеты.Код" in preflight:
        fail("code collision query must cover the whole catalog, including marked items")
    if 'Строки.Добавить("##' in preflight or r'\"' in preflight:
        fail("[24.1] contains a known BSL parser hazard")

    guard = function_body(
        object_text,
        "Адапт_ЭтоКонтурMergedBaseДляПодготовкиОбновления",
    )
    for token in (';ref=""MergedBase"";', ";ref=MergedBase;"):
        if token not in guard:
            fail(f"MergedBase contour token is missing: {token}")

    readonly_guard = function_body(
        object_text,
        "Адапт_ЭтоКонтурПодготовкиОбновленияТолькоЧтение",
    )
    for required in (
        "Адапт_ЭтоКонтурMergedBaseДляПодготовкиОбновления()",
        "Адапт_ЭтоКонтурMergedBaseДляСвежейКопииТолькоЧтение()",
    ):
        if required not in readonly_guard:
            fail(f"read-only update contour fragment is missing: {required}")

    for write_name in (
        "Адапт_ИсправитьКарантинРегламентированныхОтчетов36_14",
        "Адапт_ИсправитьКарантинПричинУвольненияПФР36_14",
        "Адапт_ИсправитьКарантинОснованийУвольнения36_14",
    ):
        write_body = function_body(object_text, write_name)
        if "Адапт_ЭтоКонтурMergedBaseДляПодготовкиОбновления()" not in write_body:
            fail(f"write contour was weakened: {write_name}")
        if "Адапт_ЭтоКонтурПодготовкиОбновленияТолькоЧтение()" in write_body:
            fail(f"MergedBase read-only contour leaked into write: {write_name}")

    if "Процедура ПредконтрольОбновления36_14(Команда)" not in form_text:
        fail("[24.1] client handler is missing")
    if "Функция ПредконтрольОбновления36_14НаСервере()" not in form_text:
        fail("[24.1] server wrapper is missing")
    if '"ПредконтрольОбновления36_14НаСервере" Тогда' not in object_text:
        fail("[24.1] long-operation dispatcher branch is missing")

    button = find_named(form_root, "Button", "ПредконтрольОбновления36_14Тесты")
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.ПредконтрольОбновления36_14":
        fail("[24.1] button is wired to the wrong command")
    command = find_named(form_root, "Command", "ПредконтрольОбновления36_14")
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "ПредконтрольОбновления36_14":
        fail("[24.1] command action is incorrect")

    update_handler = procedure_body(update_text, "ЗаполнитьСписокОтчетов")
    for evidence in (
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ИсточникОтчета",
    ):
        if evidence not in update_handler:
            fail(f"36.14 update-handler evidence is missing: {evidence}")

    print(
        f"PASS: {version}; [24.1]=readonly-MergedBase+MergedBase; "
        "registry=full; blockers=code+source+group+empty-source; form=connected"
    )


if __name__ == "__main__":
    main()
