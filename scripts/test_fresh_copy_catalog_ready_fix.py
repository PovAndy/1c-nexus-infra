#!/usr/bin/env python3
"""Static fail-closed checks for fresh-copy catalog READY stage [25.3]."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"


def function_body(text: str, name: str) -> str:
    match = re.search(
        rf"^Функция\s+{re.escape(name)}\([^\n]*\)(?:\s+Экспорт)?\s*$[\s\S]*?^КонецФункции\s*$",
        text,
        re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"function not found: {name}")
    return match.group(0)


def main() -> None:
    object_text = OBJECT.read_text(encoding="utf-8-sig")
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_xml = FORM_XML.read_text(encoding="utf-8-sig")

    assert 'Возврат "v25-123.04";' in object_text
    wrapper = function_body(object_text, "Адапт_ИсправитьREADYКодыСвежейКопии")
    assert "Адапт_ЭтоКонтурMergedBaseДляСвежейКопии()" in wrapper
    assert "STOP_CONTOUR: [25.3] разрешен только в MergedBase" in wrapper
    assert "Адапт_ИсправитьБезопаснуюПартиюКодовСправочников()" in wrapper
    body = function_body(
        object_text, "Адапт_ИсправитьБезопаснуюПартиюКодовСправочников"
    )

    required = (
        "Адапт_ЭтоКонтурMergedBaseДляСвежейКопии()",
        "ОжидаетсяREADY = 25149",
        "ОжидаетсяREVIEWАктивных = 20993",
        "ОжидаетсяREVIEWПолностьюПомеченных = 5",
        "ОжидаетсяREVIEW =\n\t\t\tОжидаетсяREVIEWАктивных",
        "+ ОжидаетсяREVIEWПолностьюПомеченных",
        "ОжидаетсяREVIEWАктивныхПосле = 20993",
        "ОжидаетсяREVIEWПолностьюПомеченныхПосле = 20",
        "ОжидаетсяREVIEWПосле =",
        "ОжидаетсяАдресныхЦелей = 6510",
        "EDD2FDD901EDF45F9DC9129A7C7B8F99",
        "A4D42EE943D18380AFECA17AE2E4886B",
        'КодЭтапа = "25.3"',
        "РазмерПакета = 500",
        "PREFLIGHT_STABLE=PASS",
        "EXACT_UUID_PREFIX_V1",
        "EXACT_NO_AUTO_UUID_V1",
        "EXACT_NO_AUTO_ZHEX_V1",
        'СтрокаПлана.РежимНазначенияКода\n\t\t\t\t\t= "STANDARD_AUTO"',
        "Если Не РежимСвежейКопии",
        "ОбъектСправочника.УстановитьНовыйКод()",
        "ОбъектСправочника.Записать()",
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "ПостКонтроль1",
        "ПостКонтроль2",
        "КоличествоREVIEWАктивных",
        "КоличествоREVIEWПолностьюПомеченных",
        "MD5_STABLE=PASS",
    )
    for marker in required:
        assert marker in body, marker

    assert "ОжидаетсяREVIEW = 20993" not in body

    preview_predefined = function_body(
        object_text, "Адапт_СформироватьPreviewАктивныхПредопределенныхКодовСправочников"
    )
    assert "993D3C777B41DFFDE5DEA49764D50A99" in preview_predefined

    forbidden = (
        r"\.\s*Удалить\s*\(",
        r"ЗаменитьСсылки\s*\(",
        r"ВыполнитьПрямойSQL\s*\(",
        r"ПометкаУдаления\s*=",
        r"Наименование\s*=",
    )
    for pattern in forbidden:
        assert not re.search(pattern, body, re.IGNORECASE), pattern

    route = "fresh_copy_catalog_ready_fix"
    assert route in object_text
    assert route in form_text
    assert "Адапт_ИсправитьREADYКодыСвежейКопии()" in object_text
    assert "Адапт_ИсправитьREADYКодыСвежейКопии()" in form_text
    assert "ИсправитьREADYКодыСвежейКопии" in form_text
    assert "Form.Command.ИсправитьREADYКодыСвежейКопии" in form_xml
    assert "[25.3] Исправить READY-коды" in form_xml

    print(
        "PASS: v25-123.04; [25.3]=MergedBase-only catalog READY; "
        "pre=25149/(20993+5)/6510; post=20993+20; batch=500; "
        "double pre/post control; "
        "form=connected"
    )


if __name__ == "__main__":
    main()
