#!/usr/bin/env python3
"""Static regression checks for the [7.1] service-period gap contour."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

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


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def function_body(text: str, name: str) -> str:
    marker = f"Функция {name}("
    start = text.find(marker)
    require(start >= 0, f"function is missing: {name}")
    end = text.find("КонецФункции", start)
    require(end >= 0, f"function is not closed: {name}")
    return text[start : end + len("КонецФункции")]


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8-sig")
    version = current_processing_version(object_text, 84)
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_xml = FORM_XML.read_text(encoding="utf-8-sig")

    require(
        version_return_marker(version) in object_text,
        "version is not v25-122.84",
    )
    for fragment in (
        "АдаптПериодРазрывовУслугНачисления",
        "АдаптРазрешитьАдресноеИсправлениеРазрываУслуги",
        "Form.Command.ДиагностикаРазрывовУслугНачисления",
        "Form.Command.PreviewРазрывовУслугНачисления",
        "Form.Command.ИсправитьРазрывыУслугНачисления",
        "[7.1] Начисления до подключения услуги",
    ):
        require(fragment in form_xml, f"form XML fragment is missing: {fragment}")

    collector = function_body(
        object_text,
        "Адапт_СобратьКандидатыРазрывовУслугНачисления",
    )
    for fragment in (
        "Документ.икНачислениеЗаУслуги КАК Начисления",
        "икОпределениеПредоставляемыхУслугЛицевыхСчетов.СрезПоследних",
        "УслугиНачалаПериода.ЛицевойСчет ЕСТЬ NULL",
        "СледующиеУслуги.Период = &НачалоСледующегоМесяца",
        "Адапт_ПолучитьТаблицуПоследнихСтатусовПриборов",
        "Адапт_ПолучитьКартуПоказанийПриборовЗаПериод",
        "READING_BEFORE_SERVICE_START_REQUIRES_REVIEW",
        "EXPLICIT_BUSINESS_CONFIRMATION",
        "SERVICE_STARTS_NEXT_MONTH_REQUIRES_REVIEW",
        "MULTIPLE_NEXT_MONTH_SERVICES",
        "EXISTING_PERIOD_RECORD",
        "NO_CONNECTED_MATCHING_METER",
    ):
        require(fragment in collector, f"collector guard is missing: {fragment}")
    require(
        "СтатусПодключения = ЗНАЧЕНИЕ" not in collector.split(
            "КАК УслугиНачалаПериода", 1
        )[0],
        "service status must not be pushed into SrezPoslednih parameters",
    )
    require(
        "РазрешитьАдресноеИсправление И ПустаяСтрока(ФильтрЛС)"
        in collector,
        "global address override is not blocked",
    )
    require(
        collector.count("Адапт_СообщитьПрогресс(") >= 6,
        "collector has no staged progress",
    )
    require(
        "МожноИсправитьАвтоматически = Истина" not in collector,
        "meter reading must not authorize automatic service backdating",
    )

    fixer = function_body(
        object_text,
        "Адапт_ИсправитьРазрывыУслугНачисления",
    )
    for fragment in (
        "Документы.икИзменениеУслугЛицевыхСчетов.СоздатьДокумент()",
        "Перечисления.икСтатусыПодключенияУслуг.Подключена",
        "НоваяСтрока.ДатаИзменения = Кандидаты.НачалоПериода",
        "НачатьТранзакцию();",
        "Записать(РежимЗаписиДокумента.Проведение)",
        "Адапт_ПолучитьТаблицуАктивныхУслугДляЛС",
        "ЗафиксироватьТранзакцию();",
        "ОтменитьТранзакцию();",
        "Исправление запрещено: укажите один ЛС",
    ):
        require(fragment in fixer, f"fix safety fragment is missing: {fragment}")
    for forbidden in (
        "СоздатьНаборЗаписей",
        "Удалить(",
        "УстановитьАктивность",
        "ПолучитьОбъект().Дата",
    ):
        require(forbidden not in fixer, f"forbidden direct mutation found: {forbidden}")
    require(
        fixer.count("Адапт_СообщитьПрогресс(") >= 4,
        "fixer has no staged progress",
    )

    for fragment in (
        "Процедура ДиагностикаРазрывовУслугНачисления(Команда)",
        "Процедура PreviewРазрывовУслугНачисления(Команда)",
        "Процедура ИсправитьРазрывыУслугНачисления(Команда)",
        '"ПериодНачисления"',
        '"РазрешитьАдресноеИсправление"',
        "ДиагностикаРазрывовУслугНачисленияНаСервере",
        "PreviewРазрывовУслугНачисленияНаСервере",
        "ИсправитьРазрывыУслугНачисленияНаСервере",
    ):
        require(fragment in form_text, f"form module fragment is missing: {fragment}")

    print(
        f"PASS: {version}; [7.1] pre-service accruals=fail-closed; "
        "global fix=OFF; explicit business override=ON; "
        "direct register writes=OFF; progress=ON"
    )


if __name__ == "__main__":
    main()
