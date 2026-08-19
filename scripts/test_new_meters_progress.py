#!/usr/bin/env python3
from epf_test_utils import current_processing_version, version_return_marker
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


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def require(text: str, fragments: tuple[str, ...], source: str) -> None:
    for fragment in fragments:
        if fragment not in text:
            fail(f"{source}: missing fragment: {fragment}")


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8")
    version = current_processing_version(object_text, 92)
    form_text = FORM_MODULE.read_text(encoding="utf-8")

    require(
        object_text,
        (
            version_return_marker(version),
            "[7] Этап 1/4: подготовка отбора лицевых счетов",
            "[7] Этап 2/4: загрузка индивидуальных приборов учета",
            "[7] Этап 3/4: анализ ЛС ",
            "ПоследнийПроцентАнализаЛС",
            "[7] Этап 4/4: формирование Preview безопасных исправлений",
            "[7] Этап 4/4: проверка и исправление строки ",
            "ПоследнийПроцентИсправления",
            "Процедура Адапт_ВыполнитьСценарийНовыхСчетчиковВФоне",
            "ПоместитьВоВременноеХранилище(РезультатСценария, АдресРезультата)",
            "Адапт_СообщитьПрогресс(100, ТекстЗавершения)",
        ),
        "ObjectModule.bsl",
    )

    require(
        form_text,
        (
            'Адапт_ВыполнитьНовыеСчетчикиВФоновомРежиме("diagnostic")',
            'Адапт_ВыполнитьНовыеСчетчикиВФоновомРежиме("preview")',
            'Адапт_ВыполнитьНовыеСчетчикиВФоновомРежиме("fix")',
            "Процедура Адапт_ВыполнитьНовыеСчетчикиВФоновомРежиме(Режим)",
            'ИмяМетода = "Адапт_ВыполнитьСценарийНовыхСчетчиковВФоне"',
            "ПараметрыОжидания.ВыводитьПрогрессВыполнения = Истина",
            "МодульДлительныеОперацииКлиент.ОжидатьЗавершение",
            "Процедура Адапт_ВыполнитьНовыеСчетчикиВФоновомРежимеЗавершение",
            "ПолучитьИзВременногоХранилища(Результат.АдресРезультата)",
        ),
        "Form/Module.bsl",
    )

    if form_text.count("Адапт_ВыполнитьНовыеСчетчикиВФоновомРежиме(") < 4:
        fail("Form/Module.bsl: all three [7] commands must use the background launcher")

    print(
        f"PASS: {version}; [7] background progress=ON; "
        "stages=4; per-LS and per-row progress=guarded"
    )


if __name__ == "__main__":
    main()
