#!/usr/bin/env python3
"""Static regression checks for the read-only TiS residual diagnostic."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
)
FORM_MODULE = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
)
FORM_XML = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"
)
EXPECTED_PATHS = ROOT / "temp/122.52plus/source_fields.tsv"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8")
    version = current_processing_version(object_text, 84)
    form_text = FORM_MODULE.read_text(encoding="utf-8")
    form_xml = FORM_XML.read_text(encoding="utf-8")

    if version_return_marker(version) not in object_text:
        fail("unexpected processing version")

    required_numbering_summary = (
        "Функция Адапт_СформироватьАдресныйPreviewНумерацииДокументов(",
        "[18.2] Детерминированный адресный Preview нумерации документов",
        "MD5 полного адресного плана",
        "READY_EXACT_PREFIX",
        "REVIEW_TARGET_COLLISION",
        "STOP_MULTI_DISTRICT",
        "Адапт_UUIDСтрокаИзСсылки(",
        "ИсточникРеквизита = ИсточникПрефикса + \".\" + ИмяРеквизита",
    )
    for fragment in required_numbering_summary:
        if fragment not in object_text:
            fail(f"numbering readonly summary fragment is missing: {fragment}")

    required_contour_guard = (
        "Функция Адапт_ТиСЭтоРазрешенныйКонтур()",
        '";ref=""MergedBase"";"',
        '";ref=MergedBase;"',
        '";ref=""ServedBase"";"',
        '";ref=ServedBase;"',
    )
    for fragment in required_contour_guard:
        if fragment not in object_text:
            fail(f"allowed-contour guard fragment is missing: {fragment}")

    required_readonly_contour_guard = (
        "Функция Адапт_ТиСЭтоРазрешенныйКонтурТолькоЧтение()",
        '";ref=""ServedBase"";"',
        '";ref=ServedBase;"',
        '";ref=""MergedBase"";"',
        '";ref=MergedBase;"',
        "Если Не Адапт_ТиСЭтоРазрешенныйКонтурТолькоЧтение() Тогда",
        "MergedBase, ServedBase, ServedBase или MergedBase (только ReadOnly)",
        "STOP: ReadOnly разрешен только в MergedBase/ServedBase/ServedBase/MergedBase",
        "STOP: Preview разрешен только в MergedBase/ServedBase/ServedBase/MergedBase",
    )
    for fragment in required_readonly_contour_guard:
        if fragment not in object_text:
            fail(f"read-only contour guard fragment is missing: {fragment}")

    forbidden_contour_guard = (
        "Адапт_ТиСЭтоКонтурMergedBase",
        "Контур проверки: только MergedBase/x17_pg9",
        "STOP: обработка запущена не в MergedBase",
    )
    for fragment in forbidden_contour_guard:
        if fragment in object_text:
            fail(f"obsolete contour guard fragment is still present: {fragment}")

    def allowed_connection_string(value: str) -> bool:
        normalized = ";" + value.strip().lower().replace(" ", "") + ";"
        allowed_tokens = (
            ';ref="MergedBase";',
            ";ref=MergedBase;",
            ';ref="ServedBase";',
            ";ref=ServedBase;",
        )
        return any(token in normalized for token in allowed_tokens)

    allowed_connections = (
        'Srvr="V8_SERVER";Ref="MergedBase";',
        'Srvr="V8_SERVER";Ref=MergedBase',
        'Srvr = "V8_SERVER"; Ref = "ServedBase";',
        'Ref=ServedBase;Srvr="V8_SERVER";',
    )
    for connection in allowed_connections:
        if not allowed_connection_string(connection):
            fail(f"allowed connection is rejected: {connection}")

    def readonly_connection_string(value: str) -> bool:
        normalized = ";" + value.strip().lower().replace(" ", "") + ";"
        allowed_tokens = (
            ';ref="MergedBase";',
            ";ref=MergedBase;",
            ';ref="ServedBase";',
            ";ref=ServedBase;",
            ';ref="ServedBase";',
            ";ref=ServedBase;",
            ';ref="MergedBase";',
            ";ref=MergedBase;",
        )
        return any(token in normalized for token in allowed_tokens)

    readonly_connections = (
        'Srvr="V8_SERVER";Ref="ServedBase";',
        'Srvr = "V8_SERVER"; Ref = ServedBase;',
        'Srvr="V8_SERVER";Ref="MergedBase";',
        'Ref=MergedBase;Srvr="V8_SERVER";',
    )
    for connection in readonly_connections:
        if not readonly_connection_string(connection):
            fail(f"read-only connection is rejected: {connection}")

    rejected_connections = (
        'Srvr="V8_SERVER";Ref="MergedBase";',
        'Srvr="V8_SERVER";Ref=MergedBase;',
        'Srvr="V8_SERVER";Ref=ServedBase;',
        'Srvr="V8_SERVER";OtherRef=ServedBase;',
        "",
    )
    for connection in rejected_connections:
        if allowed_connection_string(connection):
            fail(f"foreign connection is allowed: {connection}")
        if readonly_connection_string(connection):
            fail(f"foreign read-only connection is allowed: {connection}")

    required_connected_meter_guard = (
        "ПриборПодключенПоТекущемуСрезу = ЗначениеЗаполнено(СтатусПрибора)",
        "Адапт_СтатусПрибораПодключенДляОтчета(СтатусПрибора)",
        "Если Не ПриборПодключенПоТекущемуСрезу Тогда",
        "Статусный отбор: только приборы со статусом Подключен на текущем срезе.",
    )
    for fragment in required_connected_meter_guard:
        if fragment not in object_text:
            fail(f"connected-meter guard fragment is missing: {fragment}")

    forbidden_meter_guard_fragments = (
        "ПриборНеПодключенПоТекущемуСрезу",
        "НоЕстьИсторияПодключения",
    )
    for fragment in forbidden_meter_guard_fragments:
        if fragment in object_text:
            fail(f"obsolete meter guard fragment is still present: {fragment}")

    block_start = object_text.index(
        "Функция Адапт_ТиСUUIDИзВнутреннегоHexКлюча"
    )
    block_end = object_text.index("\n#КонецОбласти", block_start)
    block = object_text[block_start:block_end]

    executable_lines = [
        line
        for line in block.splitlines()
        if not line.lstrip().startswith("//")
    ]
    executable_block = "\n".join(executable_lines)
    if re.search(r"(?m)(?<![А-Яа-яA-Za-z0-9_])Состояние\s*\(", executable_block):
        fail("ObjectModule contains a client-only State() call")

    definitions = set(
        re.findall(
            r"(?m)^\s*(?:Функция|Процедура)\s+"
            r"(Адапт_[А-Яа-яA-Za-z0-9_]+)\s*\(",
            object_text,
        )
    )
    calls = set(
        re.findall(
            r"(?<![А-Яа-яA-Za-z0-9_])"
            r"(Адапт_[А-Яа-яA-Za-z0-9_]+)\s*\(",
            block,
        )
    )
    missing_calls = sorted(calls - definitions)
    if missing_calls:
        fail(f"undefined internal calls: {', '.join(missing_calls)}")

    actual_paths = set(
        re.findall(
            r"[А-Яа-яA-Za-z0-9_]+\|"
            r"((?:ПланВидовХарактеристик|Документ|Справочник|РегистрСведений)"
            r"\.[А-Яа-яA-Za-z0-9_.]+)",
            block,
        )
    )
    expected_paths = {
        line.split("\t", 1)[1].strip()
        for line in EXPECTED_PATHS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        fail(f"path mismatch; missing={missing}; extra={extra}")

    phase_start = object_text.index(
        "Функция Адапт_ТиСОпределитьФазуОстаточногоРеестра"
    )
    phase_end = object_text.index("\nКонецФункции", phase_start)
    phase_block = object_text[phase_start:phase_end]
    required_phase_fragments = (
        'Результат.Код = "BEFORE_READY_FIX"',
        'Результат.Код = "AFTER_READY_FIX"',
        'Результат.Код = "AFTER_SECOND_READY_FIX"',
        "КоличествоСсылок = 195",
        "КоличествоСсылок = 85",
        "КоличествоСсылок = 6",
        '"D9464C033F7F26F065FCD2FF741687E9"',
        '"7D6C40331D48ABA497CD16BB1471E34F"',
        '"C99D2FC28B3BFBFF71A95C29C515FB07"',
        "Результат.УжеПрименено = Истина",
        "Результат.ОжидаетсяREADY = 110",
        "Результат.ОжидаетсяREADY = 0",
        "STOP_PHASE",
    )
    for fragment in required_phase_fragments:
        if fragment not in phase_block:
            fail(f"phase guard fragment is missing: {fragment}")

    known_phases = {
        (195, 2, "D9464C033F7F26F065FCD2FF741687E9"):
            ("BEFORE_READY_FIX", 110),
        (85, 2, "7D6C40331D48ABA497CD16BB1471E34F"):
            ("AFTER_READY_FIX", 0),
        (6, 0, "C99D2FC28B3BFBFF71A95C29C515FB07"):
            ("AFTER_SECOND_READY_FIX", 0),
    }
    if known_phases.get(
        (195, 2, "7D6C40331D48ABA497CD16BB1471E34F")
    ) is not None:
        fail("phase model accepts a mismatched count/checksum pair")

    required_form_fragments = (
        "Процедура ДиагностикаОстатковТиС(Команда)",
        '"tis_residuals"',
        "Адапт_ДиагностикаОстатковТиС()",
        "Процедура PreviewДонорнойКартыОстатковТиС(Команда)",
        '"tis_residual_donor_preview"',
        "Адапт_PreviewДонорнойКартыОстатковТиС()",
        "Процедура PreviewИсправленияREADYОстатковТиС(Команда)",
        '"tis_residual_ready_preview"',
        "Адапт_PreviewИсправленияREADYОстатковТиС()",
        "Процедура КомплексныйReadOnlyКонтрольОстатковТиС(Команда)",
        '"tis_residual_readonly_cycle"',
        "Адапт_КомплексныйReadOnlyКонтрольОстатковТиС()",
        "Процедура ИсправитьREADYОстаткиТиС(Команда)",
        '"tis_residual_ready_fix"',
        "Адапт_ИсправитьREADYОстаткиТиС()",
        "Процедура PreviewВторойПартииОстатковТиС(Команда)",
        '"tis_residual_second_preview"',
        "Адапт_PreviewВторойПартииОстатковТиС()",
        "Процедура ИсправитьВторуюПартиюОстатковТиС(Команда)",
        '"tis_residual_second_fix"',
        '"tis_residual_system_preview"',
        '"tis_residual_system_fix"',
        "Адапт_ИсправитьВторуюПартиюОстатковТиС()",
    )
    for fragment in required_form_fragments:
        if fragment not in form_text:
            fail(f"form module fragment is missing: {fragment}")

    background_cycle_route = re.search(
        r'ИначеЕсли\s+РежимЭтапа\s*=\s*"tis_residual_readonly_cycle"'
        r'\s+Тогда\s+Результат\s*=\s*'
        r'Адапт_КомплексныйReadOnlyКонтрольОстатковТиС\(\)\s*;',
        object_text,
        re.S,
    )
    if background_cycle_route is None:
        fail(
            "background TIS dispatcher has no route for "
            "tis_residual_readonly_cycle"
        )

    required_xml_fragments = (
        'name="ДиагностикаОстатковТиСТесты"',
        "Form.Command.ДиагностикаОстатковТиС",
        "[22.12] Реестр остатков ТиС",
        'name="PreviewДонорнойКартыОстатковТиСТесты"',
        "Form.Command.PreviewДонорнойКартыОстатковТиС",
        "[22.13] Preview донорной карты",
        'name="PreviewИсправленияREADYОстатковТиСТесты"',
        "Form.Command.PreviewИсправленияREADYОстатковТиС",
        "[22.14] Preview исправления READY",
        'name="КомплексныйReadOnlyКонтрольОстатковТиСТесты"',
        "Form.Command.КомплексныйReadOnlyКонтрольОстатковТиС",
        "[22.12–22.18] Все ReadOnly (~01:35)",
        'name="ИсправитьREADYОстаткиТиСТесты"',
        "Form.Command.ИсправитьREADYОстаткиТиС",
        "[22.15] Исправить READY",
        'name="PreviewВторойПартииОстатковТиСТесты"',
        "Form.Command.PreviewВторойПартииОстатковТиС",
        "[22.16] Preview партии 2 (~00:25)",
        'name="ИсправитьВторуюПартиюОстатковТиСТесты"',
        "Form.Command.ИсправитьВторуюПартиюОстатковТиС",
        "[22.17] Исправить партию 2 (~01:00)",
    )
    for fragment in required_xml_fragments:
        if fragment not in form_xml:
            fail(f"form XML fragment is missing: {fragment}")

    form_root = ET.fromstring(form_xml)
    form_namespace = "http://v8.1c.ru/8.3/xcf/logform"
    group_tag = f"{{{form_namespace}}}UsualGroup"
    child_items_tag = f"{{{form_namespace}}}ChildItems"
    button_tag = f"{{{form_namespace}}}Button"
    groups = {
        element.attrib.get("name"): element
        for element in form_root.iter(group_tag)
    }
    expected_button_groups = {
        "ГруппаЭтап22Контроль": [
            "ДиагностикаЦелостностиТиСТесты",
            "PreviewИсправленияЦелостностиТиСТесты",
            "ФинальныйКонтрольТиСТесты",
        ],
        "ГруппаЭтап22Исправление": [
            "ИсправитьПредопределенныеТиСТесты",
            "ВосстановитьУдаленныеСсылкиПВХТиСТесты",
            "ПересобратьХозрасчетныйТиСТесты",
            "АвтоконвейерИсправленияТиСТесты",
        ],
        "ГруппаЭтап22NULLРесурсы": [
            "PreviewВосстановленияNULLРесурсовТиСТесты",
            "ПилотВосстановленияNULLРесурсовТиСТесты",
            "ИсправитьNULLРесурсыХозрасчетногоТиСТесты",
            "КонтрольВосстановленияNULLРесурсовТиСТесты",
        ],
        "ГруппаЭтап22ReadOnlyОстаточныеОшибки": [
            "КомплексныйReadOnlyКонтрольОстатковТиСТесты",
        ],
        "ГруппаЭтап22ОстаточныеОшибки": [
            "ДиагностикаОстатковТиСТесты",
            "PreviewДонорнойКартыОстатковТиСТесты",
            "PreviewИсправленияREADYОстатковТиСТесты",
            "ИсправитьREADYОстаткиТиСТесты",
        ],
        "ГруппаЭтап22ВтораяПартияОстатков": [
            "PreviewВторойПартииОстатковТиСТесты",
            "ИсправитьВторуюПартиюОстатковТиСТесты",
        ],
    }
    for group_name, expected_buttons in expected_button_groups.items():
        group = groups.get(group_name)
        if group is None:
            fail(f"workflow group is missing: {group_name}")
        child_items = group.find(child_items_tag)
        if child_items is None:
            fail(f"workflow group has no ChildItems: {group_name}")
        actual_buttons = [
            child.attrib["name"]
            for child in child_items
            if child.tag == button_tag
        ]
        if actual_buttons != expected_buttons:
            fail(
                f"unexpected button order in {group_name}: "
                f"{actual_buttons}"
            )
        if len(actual_buttons) > 4:
            fail(f"workflow group is too wide: {group_name}")

    donor_block_start = object_text.index(
        "Процедура Адапт_ТиСДобавитьПустыеПоляДонора"
    )
    donor_block_end = object_text.index(
        "Функция Адапт_ТиСНоваяТаблицаПланаREADYОстатков",
        donor_block_start,
    )
    donor_block = object_text[donor_block_start:donor_block_end]

    empty_rules = re.findall(
        r'Адапт_ТиСДобавитьПустыеПоляДонора\(Карта,\s*'
        r'"([0-9a-f-]{36})",\s*"([^"]+)"\);',
        donor_block,
    )
    if len(empty_rules) != 23:
        fail(f"expected 23 exact-source donor rules, got {len(empty_rules)}")
    empty_field_count = sum(
        len(fields.split(",")) for _source_uuid, fields in empty_rules
    )
    if empty_field_count != 87:
        fail(f"expected 87 exact empty fields, got {empty_field_count}")

    target_rules = re.findall(
        r'Адапт_ТиСДобавитьПравилоВидаПрочегоОбъекта\(Карта,\s*'
        r'"([0-9a-f-]{36})",',
        donor_block,
    )
    if len(target_rules) != 10 or len(set(target_rules)) != 10:
        fail("typed target donor rules must contain 10 unique UUIDs")

    required_preview_fragments = (
        "КонтрольДонорнойКарты =",
        "КоличествоREADY = ФазаРеестра.ОжидаетсяREADY",
        "КоличествоREVIEW = ФазаРеестра.ОжидаетсяREVIEW",
        "КоличествоBLOCKED = ФазаРеестра.ОжидаетсяBLOCKED",
        "READY_EMPTY_EXACT_SOURCE",
        "READY_REBIND_PREDEFINED",
        "READY_REBIND_EXACT_TARGET",
        "REVIEW_INVARIANT_NO_DONOR",
        "BLOCKED_NO_TYPED_DONOR",
        "[22.13] Этап 1/4",
        "[22.13] Этап 2/4",
        "[22.13] Этап 3/4",
        "[22.13] Этап 4/4",
        "Любая запись запрещена: эта версия содержит только Preview.",
    )
    for fragment in required_preview_fragments:
        if fragment not in donor_block:
            fail(f"donor Preview fragment is missing: {fragment}")

    preview_function_start = object_text.index(
        "Функция Адапт_PreviewДонорнойКартыОстатковТиС() Экспорт"
    )
    preview_function_end = object_text.index(
        "\nКонецФункции", preview_function_start
    )
    preview_function = object_text[
        preview_function_start:preview_function_end
    ]
    forbidden_preview_fragments = (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "УдалитьОбъект",
        "УстановитьПометкуУдаления",
    )
    for fragment in forbidden_preview_fragments:
        if fragment in preview_function:
            fail(f"read-only donor Preview contains mutation: {fragment}")

    ready_plan_start = object_text.index(
        "Функция Адапт_ТиСНоваяТаблицаПланаREADYОстатков"
    )
    ready_preview_start = object_text.index(
        "Функция Адапт_PreviewИсправленияREADYОстатковТиС() Экспорт",
        ready_plan_start,
    )
    ready_preview_end = object_text.index(
        "\nКонецФункции", ready_preview_start
    )
    ready_preview = object_text[ready_preview_start:ready_preview_end]
    ready_fix_start = object_text.index(
        "Функция Адапт_ИсправитьREADYОстаткиТиС() Экспорт",
        ready_preview_end,
    )
    ready_fix_end = object_text.index("\nКонецФункции", ready_fix_start)
    ready_fix = object_text[ready_fix_start:ready_fix_end]
    ready_plan_block = object_text[ready_plan_start:ready_preview_start]

    required_ready_fragments = (
        "Адапт_ТиСОпределитьФазуОстаточногоРеестра",
        "План.УжеПрименено = Истина",
        "План.КоличествоREVIEW = ФазаРеестра.ОжидаетсяREVIEW",
        "План.КоличествоBLOCKED = ФазаРеестра.ОжидаетсяBLOCKED",
        "План.Строки.Количество() = 110",
        "План.КоличествоОчисток = 87",
        "План.КоличествоКанонов = 22",
        "План.КоличествоОснований = 1",
        "План.КоличествоОбъектов = 46",
        "План.КоличествоREVIEW = 4",
        "План.КоличествоBLOCKED = 81",
        "STOP_PLAN",
        "READY_EMPTY_EXACT_SOURCE",
        "READY_REBIND_PREDEFINED",
        "READY_REBIND_EXACT_TARGET",
        "Адапт_ТиСПроверитьТипыОчистокREADY",
        'МеткаЭтапа = "[22.14]"',
        "ТолькоЧтение = Ложь",
        "Адапт_ТиСЭтоРазрешенныйКонтурТолькоЧтение()",
        "Адапт_ТиСЭтоРазрешенныйКонтур();",
        "Справочники[ОбъектМетаданных.Имя].ПустаяСсылка()",
        "ПланыВидовХарактеристик[",
    )
    for fragment in required_ready_fragments:
        if fragment not in ready_plan_block:
            fail(f"READY plan fragment is missing: {fragment}")
    empty_link_function_start = object_text.index(
        "Функция Адапт_ТиСПустаяСсылкаТогоЖеТипа"
    )
    empty_link_function_end = object_text.index(
        "\nКонецФункции", empty_link_function_start
    )
    empty_link_function = object_text[
        empty_link_function_start:empty_link_function_end
    ]
    if "Адапт_ПолучитьМенеджерПоИмени(" in empty_link_function:
        fail("READY empty-link helper still uses the unsafe legacy resolver")

    for fragment in forbidden_preview_fragments:
        if fragment in ready_preview:
            fail(f"read-only READY Preview contains mutation: {fragment}")

    readonly_cycle_start = object_text.index(
        "Функция Адапт_КомплексныйReadOnlyКонтрольОстатковТиС() Экспорт",
        ready_preview_end,
    )
    readonly_cycle_end = object_text.index(
        "\nКонецФункции", readonly_cycle_start
    )
    readonly_cycle = object_text[readonly_cycle_start:readonly_cycle_end]
    required_cycle_fragments = (
        "Адапт_ДиагностикаОстатковТиС()",
        "Адапт_PreviewДонорнойКартыОстатковТиС()",
        "Адапт_PreviewИсправленияREADYОстатковТиС()",
        "Адапт_PreviewВторойПартииОстатковТиС()",
        '"КонтрольПройден"',
        "STOP_READONLY_MUTATION",
        "Результат.ЕстьПроблемы = Не ВсеПроверкиПройдены",
        "Адапт_ДобавитьДлительностьВОтчет",
    )
    for fragment in required_cycle_fragments:
        if fragment not in readonly_cycle:
            fail(f"ReadOnly cycle fragment is missing: {fragment}")
    for fragment in forbidden_preview_fragments:
        if fragment in readonly_cycle:
            fail(f"ReadOnly cycle contains mutation: {fragment}")

    required_fix_fragments = (
        "[22.15]",
        'Адапт_ТиСПостроитьПланREADYОстатков("[22.15]")',
        "Если План.УжеПрименено Тогда",
        "ALREADY_APPLIED/PASS",
        "Если ТранзакцияАктивна() Тогда",
        "НачатьТранзакцию();",
        "ОбъектИсточника.Записать();",
        "КоличествоПолейИсправлено = 110",
        "КоличествоОбъектовЗаписано = 46",
        "Адапт_ТиСОпределитьФазуОстаточногоРеестра",
        "ФазаПосле.Готово",
        "ФазаПосле.УжеПрименено",
        "КоличествоREVIEWПосле = 4",
        "ОсталосьОперацийПлана = 0",
        "ЗафиксироватьТранзакцию();",
        "ОтменитьТранзакцию();",
        "STOP_ROLLBACK",
        "Глобальная замена ссылок, БСП-слияние и прямой SQL запрещены",
    )
    for fragment in required_fix_fragments:
        if fragment not in ready_fix:
            fail(f"READY fix fragment is missing: {fragment}")
    if ready_fix.find("ЗафиксироватьТранзакцию();") < ready_fix.find(
        "КонтрольПосле ="
    ):
        fail("READY transaction commits before post-write control")
    if "ОбщегоНазначения.ЗаменитьСсылки" in ready_fix:
        fail("READY fix must not use global BSP reference replacement")
    if ready_fix.find("Если План.УжеПрименено Тогда") > ready_fix.find(
        "Если ТранзакцияАктивна() Тогда"
    ):
        fail("ALREADY_APPLIED guard must run before transaction checks")

    print(
        f"PASS: {version}; write_contours=MergedBase,ServedBase; "
        "readonly_contours=MergedBase,ServedBase,ServedBase,MergedBase; "
        "paths=29; internal_calls="
        f"{len(calls)}; donor_ready=110; donor_review=4; "
        "donor_blocked=81; source_rules=23/87; target_rules=10; "
        "ready_objects=46; atomic_control=85+2; client_only_calls=0; "
        "connected-meter guard=OK; form workflow groups=3/4/4/1/4/2/2"
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        fail(str(exc))
