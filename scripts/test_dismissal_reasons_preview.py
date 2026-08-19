#!/usr/bin/env python3
"""Статический контракт Preview [24.4] и исправления [24.5]."""

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
    / "Catalogs/ПричиныУвольненияПФР/Ext/ManagerModule.bsl"
)
TARGET_TEMPLATE = (
    ROOT
    / "context/config-dumps/target_1_0_36_14_full"
    / "Catalogs/ПричиныУвольненияПФР/Templates/ПричиныУвольненияПФР/Ext/Template.txt"
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

    version = current_processing_version(object_text, 118)
    require_form_version(form_xml_text, version)

    fingerprint = function_body(
        object_text,
        "Адапт_ЭтоUUIDИсточника01ПричинУвольненияПФР",
    )
    helper = function_body(
        object_text,
        "Адапт_СобратьПланДублейПричинУвольненияПФР36_14",
    )
    preview = function_body(
        object_text,
        "Адапт_СформироватьPreviewДублейПричинУвольненияПФР36_14",
    )
    combined = fingerprint + helper + preview

    for forbidden in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "УстановитьНовыйКод(",
        "ОбщегоНазначения.ЗаменитьСсылки",
        "ВыполнитьПакет(",
    ):
        if forbidden in combined:
            fail(f"[24.4] contains a mutation: {forbidden}")

    for required in (
        "Справочник.ПричиныУвольненияПФР",
        "Причины.Основание КАК Основание",
        "Причины.Предопределенный КАК Предопределенный",
        "PREDEFINED_EXACT",
        "SOURCE_X1_01_UUID_FINGERPRINT",
        "9a7b-11ee-9374-c018505cf1e0",
        "СтрокИсточника01 <> 425",
        "Адапт_СледующийСвободныйТехническийКодBase36(",
        "DISMISSAL_REASONS_36_14_QUARANTINE_V1",
        "НайтиПоСсылкам(План.НеканоническиеСсылки)",
        "Адапт_ЭтоКонтурПодготовкиОбновленияТолькоЧтение()",
        "Адапт_ДобавитьДлительностьВОтчет",
        "Адапт_СообщитьПрогресс(100",
        "ч1с71тк",
    ):
        if required not in combined:
            fail(f"[24.4] safety fragment is missing: {required}")

    if "КандидатыИсточника01[0]" not in helper:
        fail("source canon must be selected only after exact candidate-count gate")
    if "КандидатыИсточника01.Количество() = 1" not in helper:
        fail("source canon has no positive exact-one gate")
    if "КандидатыПредопределенные.Количество() = 1" not in helper:
        fail("predefined canon has no positive exact-one gate")
    if 'Результат.Вставить("План"' in preview:
        fail("preview must not return ValueTable through XDTO/temp storage")

    if "Процедура PreviewДублейПричинУвольненияПФР36_14(Команда)" not in form_text:
        fail("[24.4] client handler is missing")
    if "Функция PreviewДублейПричинУвольненияПФР36_14НаСервере()" not in form_text:
        fail("[24.4] server wrapper is missing")
    if '"PreviewДублейПричинУвольненияПФР36_14НаСервере" Тогда' not in object_text:
        fail("[24.4] long-operation dispatcher branch is missing")

    button = find_named(
        form_root,
        "Button",
        "PreviewДублейПричинУвольненияПФР36_14Тесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.PreviewДублейПричинУвольненияПФР36_14":
        fail("[24.4] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "PreviewДублейПричинУвольненияПФР36_14",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "PreviewДублейПричинУвольненияПФР36_14":
        fail("[24.4] command action is incorrect")

    postcontrol = function_body(
        object_text,
        "Адапт_СформироватьПостконтрольКарантинаПричинУвольненияПФР36_14",
    )
    fix = function_body(
        object_text,
        "Адапт_ИсправитьКарантинПричинУвольненияПФР36_14",
    )
    for required in (
        "03A464C36F92E5D77C1F17B06A99D98E",
        "ОжидаетсяОпераций = 6784",
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "ОбъектПричины.Код = СтрокаПлана.ЦелевойКод",
        "ОбъектПричины.ПометкаУдаления = Истина",
        "ОбъектПричины.ДополнительныеСвойства.Вставить(",
        '"ЗаписьОбщихДанных", Истина)',
        "ОбновлениеИнформационнойБазы.ЗаписатьОбъект(ОбъектПричины)",
        "STOP_OBJECT_STATE",
        "STOP_POST_WRITE",
        "STOP_ROLLBACK",
        "PASS_ALREADY_APPLIED",
        "POSTCONTROL_STABLE",
        "ПостконтрольВТранзакции",
        "ПостконтрольПослеCommit",
    ):
        if required not in fix:
            fail(f"[24.5] safety fragment is missing: {required}")
    if fix.count("НачатьТранзакцию()") != 1:
        fail("[24.5] must start exactly one transaction")
    common_data_flag_pos = fix.find(
        "ОбъектПричины.ДополнительныеСвойства.Вставить("
    )
    code_write_pos = fix.find("ОбъектПричины.Код = СтрокаПлана.ЦелевойКод")
    mark_write_pos = fix.find("ОбъектПричины.ПометкаУдаления = Истина")
    object_write_pos = fix.find(
        "ОбновлениеИнформационнойБазы.ЗаписатьОбъект(ОбъектПричины)"
    )
    if not (
        common_data_flag_pos < code_write_pos < mark_write_pos < object_write_pos
    ):
        fail("[24.5] common-data flag must precede all object mutations and write")
    for forbidden in (
        "ОбъектПричины.Наименование =",
        "ОбъектПричины.Основание =",
        "ОбъектПричины.ОбменДанными.Загрузка",
        "ОбъектПричины.Записать()",
        "ОбщегоНазначения.ЗаменитьСсылки",
        "ВыполнитьПрямойSQL",
        ".Удалить(",
    ):
        if forbidden in fix:
            fail(f"[24.5] forbidden mutation found: {forbidden}")

    for required in (
        'Результат.Вставить("ПомеченныхСтрокИсточника01", 0)',
        "Результат.ВсегоЭлементов = 7224",
        "Результат.УникальныхКодов = 7224",
        "Результат.СтрокИсточника01 = 425",
        "Результат.ПомеченныхСтрокИсточника01 = 1",
        '"a73d949e-9a7b-11ee-9374-c018505cf1e0"',
        "Если ОжидаемыйПлан = Неопределено Тогда",
        "Результат.ТехническихКодов >= 6784",
        "Результат.АктивныхТехнических = 0",
        "ОжидаемыйПлан.Количество() = 6784",
        "Результат.ПровереноОпераций = 6784",
        "Результат.СсылокВсего = 605",
        "DISMISSAL_REASONS_36_14_POST_V1",
        "НайтиПоСсылкам(СсылкиДляКонтроля)",
    ):
        if required not in postcontrol:
            fail(f"[24.5] postcontrol fragment is missing: {required}")

    operation = "ИсправитьКарантинПричинУвольненияПФР36_14V124НаСервере"
    if operation not in object_text or operation not in form_text:
        fail("[24.5] unique long-operation route is missing")
    if "Процедура ИсправитьКарантинПричинУвольненияПФР36_14(Команда)" not in form_text:
        fail("[24.5] client handler is missing")
    if "Функция ИсправитьКарантинПричинУвольненияПФР36_14НаСервере()" not in form_text:
        fail("[24.5] server wrapper is missing")

    fix_button = find_named(
        form_root,
        "Button",
        "ИсправитьКарантинПричинУвольненияПФР36_14Тесты",
    )
    fix_command_name = next(
        (child.text for child in fix_button if local_name(child) == "CommandName"),
        None,
    )
    if fix_command_name != "Form.Command.ИсправитьКарантинПричинУвольненияПФР36_14":
        fail("[24.5] button is wired to the wrong command")
    fix_command = find_named(
        form_root,
        "Command",
        "ИсправитьКарантинПричинУвольненияПФР36_14",
    )
    fix_action = next(
        (child.text for child in fix_command if local_name(child) == "Action"),
        None,
    )
    if fix_action != "ИсправитьКарантинПричинУвольненияПФР36_14":
        fail("[24.5] command action is incorrect")

    if 'ИзвестныеПричины.Найти(ЭлементКлассификатора.Code, "Код")' not in manager_text:
        fail("target 36.14 lookup evidence is missing")
    codes = re.findall(r'<Item\s+Code="([^"]+)"', template_text)
    if len(codes) != 425 or len({code.casefold() for code in codes}) != 425:
        fail("target 36.14 template must contain exactly 425 unique codes")
    if "ч1с71тк" not in {code.casefold() for code in codes}:
        fail("failing code is absent in target template")

    print(
        f"PASS: {version}; [24.4]=readonly-MergedBase+MergedBase; "
        "[24.5]=one-transaction-update-helper+code+mark-only; reference_codes=425; "
        "canon=predefined|x1_01; xdto=value-table-not-returned"
    )


if __name__ == "__main__":
    main()
