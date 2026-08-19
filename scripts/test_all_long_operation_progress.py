#!/usr/bin/env python3
"""Статический контракт фонового прогресса длительных операций восстановления x17."""

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
FORM_XML = FORM_MODULE.parents[1] / "Form.xml"

CLIENT_PROCEDURE_RE = re.compile(
    r"(?m)^&НаКлиенте\s*\n"
    r"(?:Асинх\s+)?Процедура\s+([А-Яа-яA-Za-z0-9_]+)\s*"
    r"\([^\n]*\)(?:\s+Экспорт)?\s*\n"
    r"(.*?)^КонецПроцедуры",
    re.S | re.M,
)
SERVER_FUNCTION_RE = re.compile(
    r"(?m)^&НаСервере(?:БезКонтекста)?\s*\n"
    r"Функция\s+([А-Яа-яA-Za-z0-9_]+)\s*\([^)]*\)\s*\n"
    r"(.*?)^КонецФункции",
    re.S | re.M,
)
TIS_WRAPPER = "Адапт_ВыполнитьЭтапЦелостностиТиСНаСервере"
SPECIAL_BACKGROUND_MARKERS = (
    "Адапт_ВыполнитьНовыеСчетчикиВФоновомРежиме",
    'КодОперации = "ДиагностикаРазрывовУслугНачисленияНаСервере"',
    "Адапт_СформироватьОтчетПотребителей2025ExcelВФоновомРежиме",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8-sig")
    version = current_processing_version(object_text, 111)
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_xml_text = FORM_XML.read_text(encoding="utf-8-sig")

    require(version_return_marker(version) in object_text, "version is not v25-122.111")
    require(
        version in form_xml_text,
        f"main form title is not {version}",
    )
    for module_name, module_text in (
        ("ObjectModule", object_text),
        ("FormModule", form_text),
    ):
        require(
            "Функция Адапт_ФорматДлительности(КоличествоСекунд)"
            in module_text,
            f"{module_name} has no centralized duration formatter",
        )
        require(
            'Возврат ТекстДней + ":" + ТекстЧасов + ":"'
            in module_text,
            f"{module_name} has no DD:HH:MM:SS branch",
        )
        require(
            "Строка(ТекущаяДата() -" not in module_text,
            f"{module_name} still reports raw seconds from date subtraction",
        )
    require(
        not re.search(
            r'Строка\((?:Длительность|ДлительностьЭтапа|ОбщаяДлительность)\)'
            r'\s*\+\s*" сек\."',
            form_text,
        ),
        "FormModule still reports a measured duration as raw seconds",
    )

    def format_duration(total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days > 0:
            return f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    expected_durations = {
        23: "00:23",
        71: "01:11",
        3661: "01:01:01",
        90061: "01:01:01:01",
    }
    for seconds, expected in expected_durations.items():
        require(
            format_duration(seconds) == expected,
            f"duration format mismatch for {seconds} seconds",
        )
    require(
        "Процедура Адапт_ВыполнитьДолгуюОперациюВФоне(" in object_text,
        "object background entrypoint is absent",
    )
    require(
        "Функция Адапт_ВыполнитьДолгуюОперациюПоКоду(" in object_text,
        "object whitelist dispatcher is absent",
    )
    require(
        "Функция Адапт_ЗапуститьДолгуюОперациюВФоновомРежиме(" in form_text,
        "client universal launcher is absent",
    )
    require(
        "ПараметрыОжидания.ВыводитьПрогрессВыполнения = Истина;"
        in form_text,
        "BSP progress output is disabled",
    )
    require(
        '"Длительная операция не разрешена: "' in object_text,
        "unknown operation does not fail closed",
    )

    server_functions = dict(SERVER_FUNCTION_RE.findall(form_text))
    standard_procedures = 0
    tis_procedures = 0
    specialized_procedures = 0
    guarded_wrappers: set[str] = set()

    for procedure_name, body in CLIENT_PROCEDURE_RE.findall(form_text):
        if "Состояние(" not in body or "ОжидатьЗавершение" in body:
            continue
        wrappers = [
            wrapper
            for wrapper in re.findall(
                r"([А-Яа-яA-Za-z0-9_]+НаСервере)\s*\(",
                body,
            )
            if wrapper in server_functions
        ]
        if not wrappers:
            continue
        if any(marker in body for marker in SPECIAL_BACKGROUND_MARKERS):
            specialized_procedures += 1
            continue
        if TIS_WRAPPER in wrappers:
            require(
                "Адапт_ЗапуститьДолгуюОперациюВФоновомРежиме(" in body,
                f"TIS procedure has no background guard: {procedure_name}",
            )
            tis_procedures += 1
            continue

        for wrapper in dict.fromkeys(wrappers):
            require(
                re.search(
                    r"Адапт_ЗапуститьДолгуюОперациюВФоновомРежиме\s*\(\s*"
                    rf'"{re.escape(wrapper)}"\s*\)',
                    body,
                )
                is not None,
                f"background guard is absent: {procedure_name} -> {wrapper}",
            )
            guarded_wrappers.add(wrapper)
        standard_procedures += 1

    require(
        standard_procedures >= 90,
        f"expected at least 90 standard guarded procedures, got {standard_procedures}",
    )
    require(
        tis_procedures == 12,
        f"expected 12 TIS guarded procedures, got {tis_procedures}",
    )
    require(
        specialized_procedures == 5,
        "expected 5 specialized background procedures "
        f"([7] x3, [7.1] x1 and Excel x1), got {specialized_procedures}",
    )
    require(
        len(guarded_wrappers) >= 88,
        f"expected at least 88 unique standard wrappers, got {len(guarded_wrappers)}",
    )

    dispatcher_match = re.search(
        r"Функция Адапт_ВыполнитьДолгуюОперациюПоКоду\(.*?"
        r"\nКонецФункции",
        object_text,
        re.S,
    )
    require(dispatcher_match is not None, "dispatcher body is absent")
    dispatcher = dispatcher_match.group(0)

    for wrapper in sorted(guarded_wrappers):
        branch_match = re.search(
            rf'КодОперации\s*=\s*"{re.escape(wrapper)}"\s+Тогда'
            rf"(?P<body>.*?)(?=\n\s*Иначе(?:Если)?\b)",
            dispatcher,
            re.S,
        )
        require(
            branch_match is not None,
            f"wrapper is not whitelisted in dispatcher: {wrapper}",
        )
        branch_body = branch_match.group("body")
        wrapper_body = server_functions[wrapper]
        method_match = re.search(
            r"Возврат\s+ОбработкаОбъект\."
            r"(?P<call>Адапт_[А-Яа-яA-Za-z0-9_]+\s*\(.*?\))\s*;",
            wrapper_body,
            re.S,
        )
        require(
            method_match is not None,
            f"cannot resolve object method for wrapper: {wrapper}",
        )
        expected_call = method_match.group("call")
        replacements = {
            "АдаптНомерЛСДляАдреснойДиагностики": "ФильтрЛС",
            "АдаптНомерДокументаДляАдреснойДиагностики": "ФильтрДокумента",
            "АдаптПутьККартеВосстановленияПрочихХарактеристик": "ПутьККарте",
            "АдаптПутьКЭталонуСтруктурыПомещений": "ПутьКЭталону",
        }
        for source_name, parameter_name in replacements.items():
            expected_call = expected_call.replace(source_name, parameter_name)
        expected_call = re.sub(r"\s+", "", expected_call)
        normalized_branch = re.sub(r"\s+", "", branch_body)
        require(
            expected_call in normalized_branch,
            f"dispatcher call differs from form wrapper for {wrapper}: "
            f"{expected_call}",
        )

    for tis_mode in (
        "diagnostic",
        "preview",
        "predefined",
        "pvh",
        "accounting",
        "pipeline_preflight",
        "stabilization_control",
        "pipeline",
        "final",
        "null_preview",
        "null_pilot",
        "null_fix_preflight",
        "null_fix_package",
        "null_fix",
        "null_control",
        "tis_residuals",
        "tis_residual_donor_preview",
        "tis_residual_ready_preview",
        "tis_residual_readonly_cycle",
        "tis_residual_ready_fix",
        "tis_residual_second_preview",
        "tis_residual_second_fix",
        "tis_residual_system_preview",
        "tis_residual_system_fix",
    ):
        require(
            f'РежимЭтапа = "{tis_mode}"' in dispatcher,
            f"TIS mode is absent in dispatcher: {tis_mode}",
        )

    tis_callback_match = re.search(
        r"Процедура Адапт_ИзменениеЦелостностиТиСЗавершение\(.*?"
        r"\nКонецПроцедуры",
        form_text,
        re.S,
    )
    require(tis_callback_match is not None, "TIS confirmation callback is absent")
    tis_callback = tis_callback_match.group(0)
    answer_check = tis_callback.find(
        "РезультатВопроса <> КодВозвратаДиалога.Да"
    )
    background_start = tis_callback.find(
        "Адапт_ЗапуститьДолгуюОперациюВФоновомРежиме("
    )
    require(
        0 <= answer_check < background_start,
        "TIS background mutation can start before Yes confirmation",
    )

    require(
        "Процедура УдалитьДублиЗавершение" in form_text,
        "legacy duplicate command unexpectedly disappeared",
    )
    duplicate_callback = re.search(
        r"Процедура УдалитьДублиЗавершение\(.*?\nКонецПроцедуры",
        form_text,
        re.S,
    )
    require(duplicate_callback is not None, "legacy duplicate callback is absent")
    require(
        "Адапт_ЗапуститьДолгуюОперациюВФоновомРежиме"
        not in duplicate_callback.group(0),
        "quarantined legacy duplicate merge must not enter the new dispatcher",
    )

    require(
        object_text.count("[22.6] Этап ") >= 8,
        "TIS pipeline has no stage progress",
    )
    require(
        "ПроцентПакета = Мин(" in object_text,
        "NULL package loop has no bounded progress",
    )

    print(
        f"PASS: {version}; guarded procedures={standard_procedures}; "
        f"unique wrappers={len(guarded_wrappers)}; "
        "TIS=12; second/system batches=4; specialized background=5; "
        "whitelist=closed"
    )


if __name__ == "__main__":
    main()
