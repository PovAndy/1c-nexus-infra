#!/usr/bin/env python3
"""Static safety checks for TiS residual second address batch."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = (
    ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
)
FORM_MODULE = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
)
FORM_XML = (
    ROOT
    / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"
)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def function_block(text: str, name: str) -> str:
    start = text.index(f"Функция {name}(")
    end = text.index("\nКонецФункции", start)
    return text[start:end]


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8")
    version = current_processing_version(object_text, 84)
    form_text = FORM_MODULE.read_text(encoding="utf-8")
    form_xml = FORM_XML.read_text(encoding="utf-8")

    required = (
        version_return_marker(version),
        "Функция Адапт_ТиСПостроитьПланВторойПартии(",
        "Функция Адапт_PreviewВторойПартииОстатковТиС() Экспорт",
        "Функция Адапт_ИсправитьВторуюПартиюОстатковТиС() Экспорт",
        "План.Строки.Количество() = 81",
        "План.КоличествоОчисток = 42",
        "План.КоличествоКанонов = 39",
        "План.КоличествоТабличныхСтрок = 38",
        "План.КоличествоОбъектов = 50",
        "План.КоличествоОстатка = 6",
        '"C99D2FC28B3BFBFF71A95C29C515FB07"',
        '"AFTER_SECOND_READY_FIX"',
        "ОстаткиПосле.Сортировать(",
        "ЗафиксироватьТранзакцию();",
        "ОтменитьТранзакцию();",
        "STOP_ROLLBACK",
        "РежимЗаписиДокумента.Запись",
        "КонтрольныйОбъект.Проведен <> ПроведенДо",
        "Метаданные.ПланыСчетов.Содержит(",
        "ПланыСчетов[",
        "Глобальная замена ссылок, БСП-слияние и прямой SQL запрещены",
    )
    for fragment in required:
        if fragment not in object_text:
            fail(f"missing object-module fragment: {fragment}")

    preview = function_block(
        object_text, "Адапт_PreviewВторойПартииОстатковТиС"
    )
    for fragment in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
    ):
        if fragment in preview:
            fail(f"read-only second preview contains mutation: {fragment}")

    fix = function_block(
        object_text, "Адапт_ИсправитьВторуюПартиюОстатковТиС"
    )
    if fix.find("ЗафиксироватьТранзакцию();") < fix.find(
        'ФазаПосле.Код <> "AFTER_SECOND_READY_FIX"'
    ):
        fail("second batch commits before strict post-write phase control")
    if "ОбщегоНазначения.ЗаменитьСсылки" in fix:
        fail("second batch contains global BSP reference replacement")

    plan = function_block(
        object_text, "Адапт_ТиСПостроитьПланВторойПартии"
    )
    for fragment in (
        "ТолькоЧтение = Ложь",
        "Адапт_ТиСЭтоРазрешенныйКонтурТолькоЧтение()",
        "Адапт_ТиСЭтоРазрешенныйКонтур();",
    ):
        if fragment not in plan:
            fail(f"second-plan contour separation is missing: {fragment}")
    if 'Адапт_ТиСПостроитьПланВторойПартии("[22.16]", Истина)' not in object_text:
        fail("second Preview is not explicitly read-only")
    if 'Адапт_ТиСПостроитьПланВторойПартии("[22.17]")' not in object_text:
        fail("second Fix is not protected by the strict default contour")
    expected_uuids = (
        "a9631f3e-f8db-11ef-93db-5ce42a229ae2",
        "59821c64-82c7-11ee-936d-5ce42a229ae2",
        "e2020caa-9c71-11ed-92f2-c018505cf1e0",
        "e80d1c1d-9c71-11ed-92f2-c018505cf1e0",
        "47ee586b-757e-11ef-93b4-5ce42a229ae2",
        "59821c65-82c7-11ee-936d-5ce42a229ae2",
        "2aaaf4e6-a939-11ed-9302-c018505cf1e0",
        "8759a474-9c71-11ed-92f2-c018505cf1e0",
        "8759a478-9c71-11ed-92f2-c018505cf1e0",
    )
    for uuid in expected_uuids:
        if uuid not in plan and uuid not in object_text[
            object_text.index("Функция Адапт_ТиСПроверитьКанонОсновной"):
            object_text.index("Функция Адапт_ТиСПостроитьПланВторойПартии")
        ]:
            fail(f"strict UUID evidence is missing: {uuid}")

    for fragment in (
        "Процедура PreviewВторойПартииОстатковТиС(Команда)",
        '"tis_residual_second_preview"',
        "Процедура ИсправитьВторуюПартиюОстатковТиС(Команда)",
        '"tis_residual_second_fix"',
    ):
        if fragment not in form_text:
            fail(f"missing form route: {fragment}")

    for fragment in (
        "Вторая адресная партия [22.16–22.17]",
        "[22.16] Preview партии 2 (~00:25)",
        "[22.17] Исправить партию 2 (~01:00)",
    ):
        if fragment not in form_xml:
            fail(f"missing form presentation: {fragment}")

    route_count = len(
        re.findall(r'"tis_residual_second_(?:preview|fix)"', object_text)
    )
    if route_count < 2:
        fail("background dispatcher routes are incomplete")

    print(
        "PASS: second batch=81 operations/50 objects; "
        "clear=42; rebind=39; tabular=38; "
        "atomic post-control=6+0/C99D2F; read-only preview=ON"
    )


if __name__ == "__main__":
    main()
