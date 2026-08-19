#!/usr/bin/env python3
"""Статический и модельный контракт оптимизации сценария [7]."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = (
    ROOT
    / "src"
    / "ВыгрузкаЗагрузкаДанныхXMLАдаптивная"
    / "Ext"
    / "ObjectModule.bsl"
)
FORM_MODULE = (
    ROOT
    / "src"
    / "ВыгрузкаЗагрузкаДанныхXMLАдаптивная"
    / "Forms"
    / "Форма"
    / "Ext"
    / "Form"
    / "Module.bsl"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def function_body(text: str, name: str) -> str:
    match = re.search(
        rf"(?m)^Функция {re.escape(name)}\(.*?^КонецФункции",
        text,
        re.S,
    )
    require(match is not None, f"function is absent: {name}")
    return match.group(0)


def old_association(
    ls_rows: list[tuple[str, str]],
    services: list[tuple[str, str]],
    meters: list[tuple[str, str, str]],
) -> dict[str, tuple[list[str], list[str]]]:
    result: dict[str, tuple[list[str], list[str]]] = {}
    for ls_ref, object_ref in ls_rows:
        ls_services = [
            service_ref
            for service_ls, service_ref in services
            if service_ls == ls_ref
        ]
        ls_meters = [
            meter_ref
            for owner_ref, meter_object_ref, meter_ref in meters
            if owner_ref == object_ref or meter_object_ref == object_ref
        ]
        result[ls_ref] = (ls_services, ls_meters)
    return result


def mapped_association(
    ls_rows: list[tuple[str, str]],
    services: list[tuple[str, str]],
    meters: list[tuple[str, str, str]],
) -> dict[str, tuple[list[str], list[str]]]:
    services_by_ls: dict[str, list[str]] = {}
    for ls_ref, service_ref in services:
        services_by_ls.setdefault(ls_ref, []).append(service_ref)

    meters_by_object: dict[str, list[str]] = {}
    for owner_ref, object_ref, meter_ref in meters:
        if owner_ref:
            meters_by_object.setdefault(owner_ref, []).append(meter_ref)
        if object_ref and object_ref != owner_ref:
            meters_by_object.setdefault(object_ref, []).append(meter_ref)

    return {
        ls_ref: (
            services_by_ls.get(ls_ref, []),
            meters_by_object.get(object_ref, []),
        )
        for ls_ref, object_ref in ls_rows
    }


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8-sig")
    version = current_processing_version(object_text, 84)
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")

    require(
        version_return_marker(version) in object_text,
        "version is not v25-122.84",
    )

    candidate_body = function_body(
        object_text,
        "Адапт_СобратьКандидатыИсправленияНовыхСчетчиков",
    )
    for fragment in (
        "ЗагружатьОбъемыДляДиагностики = Ложь",
        "Адапт_ПостроитьКартуАктивныхУслугПоЛС(ТаблицаАктивныхУслуг)",
        "Адапт_ПостроитьКартуПриборовПоОбъектамУчета(ТаблицаПриборов)",
        "КартаАктивныхУслугПоЛС.Получить(КлючЛС)",
        "КартаПриборовПоОбъектамУчета.Получить(КлючОбъектаЛС)",
        "Для Каждого СтрокаПрибора Из МассивПриборовЛС Цикл",
        "КлючВладельца <> КлючОбъектаЛС И КлючОбъектаПрибора <> КлючОбъектаЛС",
        "Адапт_ПолучитьНастройкиУслугиДляНовогоСчетчикаСКешем(",
        "Адапт_ПолучитьСтатистикуИспользованияВидаПрибораСКешем(",
        "Если ЗагружатьОбъемыДляДиагностики Тогда",
        "расчет объемов не требуется для Preview/Fix",
    ):
        require(fragment in candidate_body, f"candidate optimization is absent: {fragment}")

    require(
        "Для Каждого СтрокаУслуги Из ТаблицаАктивныхУслуг Цикл"
        not in candidate_body,
        "candidate builder still scans all active services for every LS",
    )
    require(
        "Для Каждого СтрокаПрибора Из ТаблицаПриборов Цикл"
        not in candidate_body,
        "candidate builder still scans all meters for every LS",
    )
    require(
        "Адапт_ПолучитьСтатистикуИспользованияВидаПрибора(СтрокаПрибора.ВидПрибора)"
        not in candidate_body,
        "current meter-kind statistics still bypass the cache",
    )

    diagnostic_body = function_body(
        object_text,
        "Адапт_СформироватьОтчетДиагностикиНовыхСчетчиков",
    )
    require(
        re.search(
            r"Адапт_СобратьКандидатыИсправленияНовыхСчетчиков\(\s*"
            r"ФильтрЛС,\s*ФильтрДокумента,\s*Истина\)",
            diagnostic_body,
        )
        is not None,
        "detailed diagnostic no longer requests monthly volumes",
    )

    for function_name in (
        "Адапт_СформироватьPreviewИсправленияНовыхСчетчиков",
        "Адапт_ИсправитьНовыеСчетчики",
    ):
        body = function_body(object_text, function_name)
        require(
            "ЗагружатьОбъемыДляДиагностики" not in body
            and re.search(
                r"Адапт_СобратьКандидатыИсправленияНовыхСчетчиков\(\s*"
                r"ФильтрЛС,\s*ФильтрДокумента\)",
                body,
            )
            is not None,
            f"{function_name} unexpectedly requests diagnostic volumes",
        )

    revalidation_body = function_body(
        object_text,
        "Адапт_ПроверитьАктуальностьКандидатаИсправленияНовогоСчетчика",
    )
    for fragment in (
        "Адапт_ПолучитьТаблицуПоследнихСтатусовПриборов(",
        "После построения preview прибор перестал быть подключенным",
        'Если СтрокаКандидата.РежимИсправления = "CREATE_CLONE" Тогда',
        "создание клона заблокировано",
        'Если СтрокаКандидата.РежимИсправления = "RELINK" Тогда',
        "ВидДляПроверкиНастройками = СтрокаКандидата.КаноническийВидПрибора",
        'Если СтрокаКандидата.РежимИсправления = "UPDATE_CURRENT_KIND"',
        'Или СтрокаКандидата.РежимИсправления = "CREATE_CLONE" Тогда',
    ):
        require(fragment in revalidation_body, f"revalidation guard is absent: {fragment}")

    require(
        "Если номер ЛС и документа не заполнены, обработка проверит все непомеченные лицевые счета."
        in form_text,
        "global Fix confirmation text is stale",
    )
    require(
        "перейдет в пакетный режим" not in form_text,
        "obsolete batch-mode promise remains in the form",
    )

    ls_rows = [
        ("ls-1", "object-a"),
        ("ls-2", "object-b"),
        ("ls-3", "object-a"),
    ]
    services = [
        ("ls-1", "service-2"),
        ("ls-1", "service-1"),
        ("ls-2", "service-3"),
    ]
    meters = [
        ("object-a", "object-a", "meter-1"),
        ("object-a", "object-b", "meter-2"),
        ("object-c", "object-b", "meter-3"),
        ("", "object-a", "meter-4"),
    ]
    require(
        mapped_association(ls_rows, services, meters)
        == old_association(ls_rows, services, meters),
        "one-pass maps changed row membership, duplicate handling, or source order",
    )

    ls_count = 4230
    active_service_count = 3595
    connected_meter_count = 3714
    old_comparisons = ls_count * (active_service_count + connected_meter_count)
    mapped_operations = (
        active_service_count + connected_meter_count + 2 * ls_count
    )
    require(
        old_comparisons > mapped_operations * 1000,
        "measured global contour does not justify the map optimization",
    )

    print(
        f"PASS: {version}; [7] association maps preserve membership/order; "
        f"conservative comparisons {old_comparisons:,} -> "
        f"{mapped_operations:,}; revalidation guards=ON"
    )


if __name__ == "__main__":
    main()
