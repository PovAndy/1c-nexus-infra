#!/usr/bin/env python3
"""Static regression checks for deterministic ReadOnly document numbering."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
)
FORM_XML = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"
)
FORM_MODULE = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
)


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


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


def actual_call_arities(source: str, name: str) -> list[int]:
    calls = re.findall(
        rf"(?<!Функция ){re.escape(name)}\((?P<arguments>[^()]*)\)",
        source,
        flags=re.DOTALL,
    )
    return [
        0 if not arguments.strip() else arguments.count(",") + 1
        for arguments in calls
    ]


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def find_named_element(
    root: ET.Element,
    element_name: str,
    name_attribute: str,
) -> ET.Element:
    for element in root.iter():
        if (
            local_name(element) == element_name
            and element.get("name") == name_attribute
        ):
            return element
    fail(f"form element is missing: {element_name}.{name_attribute}")


def direct_child(element: ET.Element, element_name: str) -> ET.Element:
    for child in element:
        if local_name(child) == element_name:
            return child
    fail(f"direct child is missing: {element_name}")


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8")
    version = current_processing_version(object_text, 111)
    form_xml = FORM_XML.read_text(encoding="utf-8")
    form_module = FORM_MODULE.read_text(encoding="utf-8")
    form_root = ET.fromstring(form_xml)

    if version_return_marker(version) not in object_text:
        fail("unexpected processing version")

    numbering_call_arities = actual_call_arities(
        object_text,
        "Адапт_СформироватьНомерДокументаСПрефиксомРайонаДляPreview",
    )
    if numbering_call_arities != [3, 3, 3, 3]:
        fail(
            "unexpected argument count in numbering function calls: "
            f"{numbering_call_arities}"
        )

    long_operation_dispatcher = function_body(
        object_text,
        "Адапт_ВыполнитьДолгуюОперациюПоКоду",
    )
    second_pilot_operation = (
        '"PreviewВторогоПилотаПеренумерацииДокументовНаСервере"'
    )
    if long_operation_dispatcher.count(second_pilot_operation) != 1:
        fail("second pilot long operation is not registered exactly once")
    if (
        "Адапт_СформироватьPreviewВторогоПилотаПеренумерацииДокументов()"
        not in long_operation_dispatcher
    ):
        fail("second pilot long operation target is missing")
    second_pilot_fix_operation = (
        '"ИсправитьВторойПилотПеренумерацииДокументовНаСервере"'
    )
    if long_operation_dispatcher.count(second_pilot_fix_operation) != 1:
        fail("second pilot fix long operation is not registered exactly once")
    if (
        "Адапт_ИсправитьВторойПилотПеренумерацииДокументов()"
        not in long_operation_dispatcher
    ):
        fail("second pilot fix long operation target is missing")
    final_preview_operation = (
        '"PreviewФинальногоОстаткаНумерацииДокументовНаСервере"'
    )
    if long_operation_dispatcher.count(final_preview_operation) != 1:
        fail("final numbering preview long operation is not registered exactly once")
    if (
        "Адапт_СформироватьPreviewФинальногоОстаткаНумерацииДокументов()"
        not in long_operation_dispatcher
    ):
        fail("final numbering preview target is missing")
    final_fix_operation = (
        '"ИсправитьФинальныйОстатокНумерацииДокументовНаСервере"'
    )
    if long_operation_dispatcher.count(final_fix_operation) != 1:
        fail("final numbering fix long operation is not registered exactly once")
    if (
        "Адапт_ИсправитьФинальныйОстатокНумерацииДокументов()"
        not in long_operation_dispatcher
    ):
        fail("final numbering fix target is missing")

    numbering_group = find_named_element(
        form_root,
        "UsualGroup",
        "ГруппаЭтап18ДублиНомеровДокументов",
    )
    if (direct_child(numbering_group, "Group").text or "").strip() != "Vertical":
        fail("numbering command block must use vertical row layout")
    numbering_rows = direct_child(numbering_group, "ChildItems")
    expected_rows = {
        "ГруппаЭтап18ReadOnly": (
            "КомплексныйReadOnlyКонтрольНумерацииДокументовТесты",
            "ДиагностикаДублейНомеровДокументовТесты",
            "ДиагностикаЕдинственностиРайоновДокументовТесты",
            "PreviewПеренумерацииДокументовТесты",
        ),
        "ГруппаЭтап18Запись": (
            "PreviewПилотнойПеренумерацииДокументовТесты",
            "ИсправитьПилотнуюПеренумерациюДокументовТесты",
            "КонтрольПилотнойПеренумерацииДокументовТесты",
        ),
        "ГруппаЭтап18ВторойПилот": (
            "PreviewВторогоПилотаПеренумерацииДокументовТесты",
            "ИсправитьВторойПилотПеренумерацииДокументовТесты",
        ),
        "ГруппаЭтап18ПакетноеЛечение": (),
    }
    actual_row_names = tuple(
        row.get("name")
        for row in numbering_rows
        if local_name(row) == "UsualGroup"
    )
    if actual_row_names != tuple(expected_rows):
        fail(f"unexpected numbering rows: {actual_row_names}")
    for row_name, expected_buttons in expected_rows.items():
        row = find_named_element(form_root, "UsualGroup", row_name)
        expected_orientation = (
            "Vertical"
            if row_name == "ГруппаЭтап18ПакетноеЛечение"
            else "Horizontal"
        )
        if (
            direct_child(row, "Group").text or ""
        ).strip() != expected_orientation:
            fail(f"numbering row must be horizontal: {row_name}")
        row_items = direct_child(row, "ChildItems")
        actual_buttons = tuple(
            button.get("name")
            for button in row_items
            if local_name(button) == "Button"
        )
        if row_name == "ГруппаЭтап18ПакетноеЛечение":
            expected_buttons = ("ИсправитьПеренумерациюДокументовТесты",)
        if actual_buttons != expected_buttons:
            fail(f"unexpected buttons in numbering row {row_name}: {actual_buttons}")
    final_row = find_named_element(
        form_root,
        "UsualGroup",
        "ГруппаЭтап18ФинальныйОстаток",
    )
    if (direct_child(final_row, "Group").text or "").strip() != "Horizontal":
        fail("final numbering row must be horizontal")
    final_row_items = direct_child(final_row, "ChildItems")
    final_buttons = tuple(
        button.get("name")
        for button in final_row_items
        if local_name(button) == "Button"
    )
    if final_buttons != (
        "PreviewФинальногоОстаткаНумерацииДокументовТесты",
        "ИсправитьФинальныйОстатокНумерацииДокументовТесты",
    ):
        fail(f"unexpected final numbering buttons: {final_buttons}")

    periodicity = function_body(
        object_text,
        "Адапт_КодПериодичностиНомераДокумента",
    )
    for fragment in (
        "ПериодичностьНомераДокумента",
        "Непериодический",
        '"WHOLE"',
        '"YEAR"',
        '"QUARTER"',
        '"MONTH"',
        '"DAY"',
        '"UNKNOWN"',
    ):
        if fragment not in periodicity:
            fail(f"number periodicity fragment is missing: {fragment}")

    period_key = function_body(
        object_text,
        "Адапт_КлючПериодаНумерацииДокумента",
    )
    for fragment in (
        'Тип("Дата")',
        "Дата(1, 1, 1)",
        '"ДФ=yyyy"',
        '"ДФ=yyyyMM"',
        '"ДФ=yyyyMMdd"',
        "НомерКвартала",
    ):
        if fragment not in period_key:
            fail(f"number period key fragment is missing: {fragment}")

    occupied_key = function_body(
        object_text,
        "Адапт_КлючНомераДокументаВПериоде",
    )
    if occupied_key.count("Адапт_ПолеСтрокиПланаНумерации") != 2:
        fail("number/period occupancy key must length-prefix both components")

    preview = function_body(
        object_text,
        "Адапт_СформироватьАдресныйPreviewНумерацииДокументов",
    )
    required_preview_fragments = (
        "[18.2] Детерминированный адресный Preview нумерации документов",
        "УПОРЯДОЧИТЬ ПО",
        "Т.Номер,",
        "Т.Дата,",
        "Т.Ссылка",
        "Для ИндексДокумента = 0 По",
        "ДокументыГруппы.Количество() - 1 Цикл",
        "READY_EXACT_PREFIX",
        "KEEP_ALREADY_CORRECT_PREFIX",
        "KEEP_BUSINESS_LS_NUMBER",
        "Номер документа открытия ЛС является бизнес-номером лицевого счета",
        "REVIEW_TARGET_COLLISION",
        "REVIEW_NO_DISTRICT_EVIDENCE",
        "REVIEW_BAD_NUMBER_FORMAT",
        "STOP_MULTI_DISTRICT",
        "STOP_DISTRICT_READ_ERROR",
        "STOP_UUID_ERROR",
        "NUMPLAN_V3",
        "Адапт_КодПериодичностиНомераДокумента",
        "Адапт_КлючПериодаНумерацииДокумента",
        "Адапт_КлючНомераДокументаВПериоде",
        "ПериодичностьНомера",
        "КлючПериодаНумерации",
        "REVIEW_GLOBAL_NUMBERING_POLICY_REQUIRED",
        "STOP_UNSUPPORTED_NUMBER_PERIODICITY",
        "STOP_INVALID_NUMBER_PERIOD",
        "Номер+период нумерации",
        "КлючОрганизации",
        "ПроведенКлюч",
        "Адапт_КонтрольнаяСуммаСтрокой",
        "MD5 полного адресного плана",
        '"КонтрольнаяСумма"',
        "Следующий свободный числовой хвост не подбирается",
        "БылиИзменения",
        "Ложь",
    )
    for fragment in required_preview_fragments:
        if fragment not in preview:
            fail(f"deterministic preview fragment is missing: {fragment}")

    forbidden_preview_fragments = (
        "ДокументыГруппы[0]",
        "Адапт_ПодобратьСвободныйНомерДокументаСПрефиксом(",
        "OK_NEXT_FREE",
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "ВыполнитьПакет(",
        "Адапт_КлючДубляНомераДокумента(",
    )
    for fragment in forbidden_preview_fragments:
        if fragment in preview:
            fail(f"deterministic preview contains forbidden fragment: {fragment}")
    if (
        'ПолноеИмяДокумента =\n\t\t\t\t\t"Документ.икОткрытиеЛицевогоСчета"'
        not in preview
    ):
        fail("opening-LS document type is not protected explicitly")

    legacy = function_body(
        object_text,
        "Адапт_ВыполнитьСценарийДублейНомеровДокументов",
    )
    if 'Если РежимСценария = "fix" Тогда' not in legacy:
        fail("legacy fix route is not blocked before scan")
    if "Адапт_ИсправитьПеренумерациюДокументов()" not in legacy:
        fail("legacy fix route does not return the blocking result")
    if ".Записать(" in legacy:
        fail("legacy numbering scenario still contains document writes")

    exported_preview = function_body(
        object_text,
        "Адапт_СформироватьPreviewПеренумерацииДокументов",
    )
    if (
        "Адапт_СформироватьАдресныйPreviewНумерацииДокументов()"
        not in exported_preview
    ):
        fail("[18.2] export is not routed to deterministic preview")

    readonly_cycle = function_body(
        object_text,
        "Адапт_КомплексныйReadOnlyКонтрольНумерацииДокументов",
    )
    if readonly_cycle.count(
        "Адапт_СформироватьАдресныйPreviewНумерацииДокументов()"
    ) != 2:
        fail("[18.0] must execute exactly two end-to-end previews")
    for fragment in (
        "КонтрольнаяСуммаПервогоПрохода",
        "КонтрольнаяСуммаВторогоПрохода",
        "STOP_MD5_UNSTABLE",
        "MD5_STABLE=PASS",
        "Длительность прохода 1/2",
        "Длительность прохода 2/2",
    ):
        if fragment not in readonly_cycle:
            fail(f"[18.0] MD5 stability fragment is missing: {fragment}")
    for fragment in (
        "Адапт_ВыполнитьСценарийДублейНомеровДокументов(",
        ".Записать(",
        "НачатьТранзакцию(",
    ):
        if fragment in readonly_cycle:
            fail(f"[18.0] contains forbidden fragment: {fragment}")

    pilot_preview = function_body(
        object_text,
        "Адапт_СформироватьPreviewПилотнойПеренумерацииДокументов",
    )
    required_pilot_fragments = (
        "[18.3] Preview адресного пилота перенумерации документов",
        "53143cdc-885b-11ea-e689-000c29ecaafa",
        "03f551a2-a658-11ea-2191-000c29a58bb5",
        "00-00000001",
        "03-00000001",
        "08-00000001",
        "20200331120000",
        "20200604000000",
        "Адапт_ЭтоКонтурЗагрузка1ДляПилотаНумерации",
        "Адапт_КодПериодичностиНомераДокумента",
        "Адапт_КлючПериодаНумерацииДокумента",
        "Адапт_ОпределитьПрефиксРайонаДокументаДляПеренумерации",
        "Адапт_СформироватьНомерДокументаСПрефиксомРайонаДляPreview",
        "STOP_GROUP_COUNT",
        "STOP_TARGET_OCCUPIED",
        "NUMPILOT_V1",
        "A7C63F83CCECD85E1F70B536B5661C6B",
        "Длительность",
        "БылиИзменения",
        "Ложь",
    )
    for fragment in required_pilot_fragments:
        if fragment not in pilot_preview:
            fail(f"pilot preview fragment is missing: {fragment}")
    for fragment in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "ДокументыГруппы[0]",
        "Адапт_ПодобратьСвободныйНомерДокументаСПрефиксом(",
    ):
        if fragment in pilot_preview:
            fail(f"pilot preview contains forbidden fragment: {fragment}")

    pilot_snapshot = function_body(
        object_text,
        "Адапт_СнимокИнвариантовПилотногоДокументаНумерации",
    )
    for fragment in (
        "Ответственный",
        "Комментарий",
        "ПоказанияПриборовУчета.Выгрузить()",
        "ОбъектДокумента.Движения",
        "НаборДвижений.Прочитать()",
        "НаборДвижений.Выгрузить()",
        "NUMPILOT_INVARIANTS_V1",
        "ХешШапки",
        "ХешТабличнойЧасти",
        "ХешДвижений",
    ):
        if fragment not in pilot_snapshot:
            fail(f"pilot invariant snapshot fragment is missing: {fragment}")
    if "ОбъектДокумента.Номер" in pilot_snapshot:
        fail("pilot invariant snapshot must exclude the only mutable field Number")

    pilot_fix = function_body(
        object_text,
        "Адапт_ИсправитьПилотнуюПеренумерациюДокументов",
    )
    for fragment in (
        "[18.4] Исправление адресного пилота перенумерации документов",
        "0DD4D836F6AF7EF691F7307E48B4E0AA",
        "Адапт_СформироватьPreviewПилотнойПеренумерацииДокументов()",
        "НачатьТранзакцию()",
        "ОбъектДокумента.ОбменДанными.Загрузка",
        "ОбъектДокумента.Записать(",
        "РежимЗаписиДокумента.Запись",
        "Адапт_СнимокИнвариантовПилотногоДокументаНумерации",
        "СнимокДо.Хеш <> СнимокПосле.Хеш",
        "Адапт_ПроверитьПостСостояниеПилотнойПеренумерацииДокументов",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "STOP_ROLLBACK",
        "Частичные изменения отсутствуют",
        'Вставить("ПолныйОтчет", "")',
    ):
        if fragment not in pilot_fix:
            fail(f"pilot fix fragment is missing: {fragment}")
    for fragment in (
        "ДокументыГруппы[0]",
        "Адапт_ПодобратьСвободныйНомерДокументаСПрефиксом(",
        "ВыполнитьПакет(",
        "ПрямойSQL",
    ):
        if fragment in pilot_fix:
            fail(f"pilot fix contains forbidden fragment: {fragment}")

    pilot_post_control = function_body(
        object_text,
        "Адапт_СформироватьКонтрольПилотнойПеренумерацииДокументов",
    )
    for fragment in (
        "[18.5] ReadOnly-контроль адресного пилота перенумерации",
        "Адапт_ЭтоКонтурЗагрузка1ДляПилотаНумерации",
        "Адапт_ПроверитьПостСостояниеПилотнойПеренумерацииДокументов",
        "MD5 постсостояния",
        "Следующий обязательный шаг: [18.0]",
        "БылиИзменения",
        "Ложь",
        'Вставить("ПолныйОтчет", "")',
    ):
        if fragment not in pilot_post_control:
            fail(f"pilot post-control fragment is missing: {fragment}")
    for fragment in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "ВыполнитьПакет(",
    ):
        if fragment in pilot_post_control:
            fail(f"pilot post-control contains forbidden fragment: {fragment}")

    second_pilot_preview = function_body(
        object_text,
        "Адапт_СформироватьPreviewВторогоПилотаПеренумерацииДокументов",
    )
    second_pilot_plan = function_body(
        object_text,
        "Адапт_ПланВторогоПилотаПеренумерацииДокументов",
    )
    for fragment in (
        "cb8b7bee-95a8-11ea-329d-000c29ecaafa",
        "cb143470-aa08-11ea-889b-000c29a58bb5",
        "00-00000002",
        "03-00000002",
        "08-00000002",
        "20200331120001",
        "20200609000000",
        "E6E3AFA6929E5E3E9A93ED7AF689E114",
        "F8F50EB6EE0C7374E0049A5FD0A30B1E",
        'План.Сортировать("UUID")',
    ):
        if fragment not in second_pilot_plan:
            fail(f"second pilot plan fragment is missing: {fragment}")
    required_second_pilot_fragments = (
        "[18.6] Preview второго адресного пилота перенумерации документов",
        "00-00000002",
        "03-00000002",
        "08-00000002",
        "3D8A64C9D85AA915F1BABFB599337808",
        "2291D806E0DEE95C519160F4F8384FDA",
        "Адапт_ПроверитьПостСостояниеПилотнойПеренумерацииДокументов",
        "Адапт_СнимокИнвариантовПилотногоДокументаНумерации",
        "STOP_FIRST_PILOT_STATE",
        "STOP_GROUP_COUNT",
        "STOP_TARGET_OCCUPIED",
        "NUMPILOT2_V1",
        "Успешных снимков инвариантов",
        "Длительность",
        "БылиИзменения",
        "Ложь",
    )
    for fragment in required_second_pilot_fragments:
        if fragment not in second_pilot_preview:
            fail(f"second pilot preview fragment is missing: {fragment}")
    for fragment in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
        "ВыполнитьПакет(",
        "ДокументыГруппы[0]",
        "Адапт_ПодобратьСвободныйНомерДокументаСПрефиксом(",
    ):
        if fragment in second_pilot_preview:
            fail(f"second pilot preview contains forbidden fragment: {fragment}")

    second_pilot_fix = function_body(
        object_text,
        "Адапт_ИсправитьВторойПилотПеренумерацииДокументов",
    )
    for fragment in (
        "[18.7] Исправление второго адресного пилота",
        "5B3C69C531FD6C1A80594235F1E7AE5D",
        "107976EA9956B96547463461CC5CCD06",
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "ОбъектДокумента.Номер",
        "РежимЗаписиДокумента.Запись",
        "Адапт_СформироватьPreviewВторогоПилотаПеренумерацииДокументов",
        "Адапт_ПроверитьПостСостояниеВторогоПилотаПеренумерацииДокументов",
        "ВыполненныеОперации.Количество() <> 2",
        "Следующий обязательный шаг: [18.0]",
    ):
        if fragment not in second_pilot_fix:
            fail(f"second pilot fix fragment is missing: {fragment}")
    for fragment in (
        "РежимЗаписиДокумента.Проведение",
        "ВыполнитьПакет(",
        "ДокументыГруппы[0]",
    ):
        if fragment in second_pilot_fix:
            fail(f"second pilot fix contains forbidden fragment: {fragment}")

    ready_fix = function_body(
        object_text,
        "Адапт_ИсправитьПеренумерациюДокументов",
    )
    for fragment in (
        "[18.9] Исправление нумерации по исходным базам",
        "CFF588255055E6788E10312EE62DFAF7",
        "ОжидаетсяДокументовПлана = 1132",
        "ОжидаетсяREADY = 1066",
        "ОжидаетсяREVIEW = 53",
        "ОжидаетсяSTOP = 13",
        "ОжидаетсяДокументовПосле = 56",
        "ОжидаетсяREVIEWПосле = 43",
        "ОжидаетсяSTOPПосле = 13",
        "Адапт_ДанныеКартыИсходныхРайоновОстаткаНумерации",
        "7664BF780891550535DC32D8C5D7E997",
        "Адапт_ОпределитьПрефиксРайонаДокументаДляПеренумерацииСКартой",
        "РазмерПакета = 500",
        "READY_EXACT_PREFIX",
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "РежимЗаписиДокумента.Запись",
        "ОбъектДокумента.ОбменДанными.Загрузка",
        "Адапт_СформироватьАдресныйPreviewНумерацииДокументов",
        "READYПосле1 = 0",
        "READYПосле2 = 0",
        "Полный ReadOnly-реестр финального остатка",
        "ПостКонтроль2.ПолныйОтчет",
        "MD5_STABLE=PASS",
    ):
        if fragment not in ready_fix:
            fail(f"READY fix fragment is missing: {fragment}")
    for fragment in (
        "ДокументыГруппы[0]",
        "OK_NEXT_FREE",
        "Адапт_ПодобратьСвободныйНомерДокументаСПрефиксом(",
        "РежимЗаписиДокумента.Проведение",
        "ВыполнитьПакет(",
    ):
        if fragment in ready_fix:
            fail(f"READY fix contains forbidden fragment: {fragment}")

    final_plan_text = function_body(
        object_text,
        "Адапт_ТекстФинальногоПланаНумерацииДокументов",
    )
    final_plan = function_body(
        object_text,
        "Адапт_ФинальныйПланНумерацииДокументов",
    )
    if "икОткрытиеЛицевогоСчета" in final_plan_text + final_plan:
        fail("opening-LS document is present in final write plan")
    if final_plan_text.count("|") != 17 * 6:
        fail("final static write plan must contain exactly 17 seven-field rows")
    for document_type in (
        "икГрупповойВводОплатыУслуг",
        "икИзменениеСтатусовПриборовУчета",
        "икИзменениеИнформацииОГражданине",
    ):
        if document_type not in final_plan_text:
            fail(f"final write plan document type is missing: {document_type}")

    final_preflight = function_body(
        object_text,
        "Адапт_ПроверитьФинальныйПланНумерацииДокументов",
    )
    for fragment in (
        "Результат.План.Количество() <> 17",
        "STOP_OPEN_LS_NUMBER",
        "KEEP_BUSINESS_LS_NUMBER",
        "КоличествоKEEP <> 22",
        "Счетчики.REVIEW <> 21",
        "Счетчики.STOP <> 13",
        "Счетчики.REVIEW <> 0",
        "Счетчики.STOP <> 0",
        "Адапт_ПроверитьСтрокуФинальногоПланаНумерации",
    ):
        if fragment not in final_preflight:
            fail(f"final preflight fragment is missing: {fragment}")

    final_preview = function_body(
        object_text,
        "Адапт_СформироватьPreviewФинальногоОстаткаНумерацииДокументов",
    )
    for fragment in (
        "[18.10] Preview финального остатка нумерации документов",
        "номера документов `икОткрытиеЛицевогоСчета`",
        "Защищено от изменения документов открытия ЛС: 22",
        "Адапт_ПроверитьФинальныйПланНумерацииДокументов",
        "Следующий шаг: [18.11]",
        "БылиИзменения",
        "Ложь",
    ):
        if fragment not in final_preview:
            fail(f"final preview fragment is missing: {fragment}")
    for fragment in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
    ):
        if fragment in final_preview:
            fail(f"final preview contains forbidden fragment: {fragment}")

    final_fix = function_body(
        object_text,
        "Адапт_ИсправитьФинальныйОстатокНумерацииДокументов",
    )
    for fragment in (
        "[18.11] Исправление финального остатка нумерации документов",
        "Номера документов открытия ЛС не входят в план и не изменяются",
        "НачатьТранзакцию()",
        "ОбъектДокумента.ОбменДанными.Загрузка",
        "ОбъектДокумента.Номер",
        "ОбъектДокумента.Записать(",
        "РежимЗаписиДокумента.Запись",
        "Адапт_СнимокИнвариантовДокументаБезНомера",
        "СнимокДо.Хеш",
        "СнимокПосле.Хеш",
        "ВыполненныеОперации.Количество() <> 17",
        "ПостКонтроль1",
        "ПостКонтроль2",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "STOP_ROLLBACK",
        "Документов открытия ЛС изменено: 0",
        "MD5_STABLE=PASS",
    ):
        if fragment not in final_fix:
            fail(f"final fix fragment is missing: {fragment}")
    for fragment in (
        "РежимЗаписиДокумента.Проведение",
        "ВыполнитьПакет(",
        "ДокументыГруппы[0]",
        "икОткрытиеЛицевогоСчета",
    ):
        if fragment in final_fix and fragment != "икОткрытиеЛицевогоСчета":
            fail(f"final fix contains forbidden fragment: {fragment}")
    if "Номера документов открытия ЛС не входят" not in final_fix:
        fail("final fix does not state the opening-LS protection")

    required_form_titles = (
        "[18] Узкие дубли",
        "[18.1] Единственность района",
        "[18.2] Номер+период",
        "[18.0] Все ReadOnly ×2",
        "[18.3] Preview пилота",
        "[18.4] Исправить (~00:10)",
        "[18.5] Контроль (~00:05)",
        "[18.6] Preview 2 (~00:10)",
        "[18.7] Исправить 2 + контроль (~00:10)",
        "[18.9] Источники + контроль (~00:25:00–00:45:00)",
        "[18.10] Preview 17 (~00:30–01:00)",
        "[18.11] Исправить 17 (~02:00–04:00)",
    )
    for title in required_form_titles:
        if title not in form_xml:
            fail(f"form title is missing: {title}")

    for fragment in (
        "ИсправитьПилотнуюПеренумерациюДокументовЗавершение",
        "ИсправитьПилотнуюПеренумерациюДокументовНаСервере",
        "КонтрольПилотнойПеренумерацииДокументовНаСервере",
        "PreviewВторогоПилотаПеренумерацииДокументовНаСервере",
        "ИсправитьВторойПилотПеренумерацииДокументовЗавершение",
        "ИсправитьВторойПилотПеренумерацииДокументовНаСервере",
        "ИсправитьПеренумерациюДокументовЗавершение",
        "ИсправитьПеренумерациюДокументовНаСервере",
        "PreviewФинальногоОстаткаНумерацииДокументовНаСервере",
        "ИсправитьФинальныйОстатокНумерацииДокументовЗавершение",
        "ИсправитьФинальныйОстатокНумерацииДокументовНаСервере",
        "ровно у 17 документов",
        "Документы открытия лицевого счета в план не входят",
        "ПоказатьВопрос",
    ):
        if fragment not in form_module:
            fail(f"pilot form handler fragment is missing: {fragment}")

    print(
        f"PASS: {version}; numbering_preview=readonly_deterministic; "
        "canon=none; candidates=all_documents; next_free=review; "
        "number_scope=metadata_period; plan_hash=MD5_V3; "
        "readonly_cycle=double_pass; pilot_preview=two_document_group; "
        "pilot_fix=atomic_two_documents; post_control=readonly; "
        "second_pilot_preview=readonly_with_invariants; "
        "second_pilot_background=allowed; second_pilot_fix=atomic_with_postcontrol; "
        "source_fix=batched_with_double_postcontrol; "
        "source_map=1066_uuid_md5_guarded; opening_ls_number=immutable; "
        "final_fix=17_exact_atomic_with_double_postcontrol; "
        "ui_layout=four_compact_rows_with_nested_final_row"
    )


if __name__ == "__main__":
    main()
