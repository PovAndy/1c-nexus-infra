#!/usr/bin/env python3
"""Static safety contract for [23.2] catalog-code safe batch fix."""

from __future__ import annotations
from epf_test_utils import current_processing_version, version_return_marker

import re
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"


def fail(message: str) -> None:
    raise AssertionError(message)


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
    version = current_processing_version(object_text, 111)
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_root = ET.fromstring(FORM_XML.read_text(encoding="utf-8-sig"))

    if version_return_marker(version) not in object_text:
        fail("unexpected processing version")

    fix_name = "Адапт_ИсправитьБезопаснуюПартиюКодовСправочников"
    fix = function_body(object_text, fix_name)
    required = (
        "ОжидаетсяREADY = 807",
        "ОжидаетсяREVIEW = 21009",
        "ОжидаетсяАдресныхЦелей = 477",
        'ОжидаетсяMD5Плана = "5EC21A011A03D61537AB89370E552D6D"',
        'ОжидаетсяMD5Целей = "B7E98A960CDBCAF552BD8466128796B6"',
        "РазмерПакета = 500",
        "Адапт_ЭтоКонтурЗагрузка1ДляПилотаНумерации()",
        "Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников(",
        "6,\n\t\t\t\tИстина);",
        "Preflight1.КонтрольнаяСумма",
        "Preflight2.КонтрольнаяСумма",
        "Preflight1.КонтрольнаяСуммаЦелей",
        "Preflight2.КонтрольнаяСуммаЦелей",
        "PREFLIGHT_STABLE=PASS",
        "ОбъектСправочника.Метаданные().ПолноеИмя()",
        "Не ОбъектСправочника.ПометкаУдаления",
        "ОбъектСправочника.Предопределенный",
        "ОбъектСправочника.ОбменДанными.Загрузка = Истина",
        "ОбъектСправочника.УстановитьНовыйКод()",
        'СтрокаПлана.РежимНазначенияКода\n\t\t\t\t\t\t= "EXACT_UUID_PREFIX_V1"',
        "Адапт_ТехническийКодДубляРаскрытияПоUUID(",
        "СтрДлина(ОжидаемыйТехническийКод) <> 9",
        "STOP_EXACT_TARGET_OCCUPIED",
        "КлючОбластиОбъекта <> СтрокаПлана.КлючОбласти",
        "НайтиПоКоду(",
        "ОбъектСправочника.Родитель);",
        "ОбъектСправочника.Код = ОжидаемыйТехническийКод",
        "EXACT_NO_AUTO_UUID_V1",
        "EXACT_NO_AUTO_ZHEX_V1",
        "Адапт_ЭтоLegacyСправочникБезАвтонумерации(",
        "Адапт_ЭтоТехническийКороткийКод(",
        "Справочники[ИмяСправочника].НайтиПоКоду(",
        "Адапт_ЭтоАдресныйРежимНазначенияКода(",
        "Адапт_ЭтоСправочникШтатногоХвостаКодов(",
        "STOP_STANDARD_AUTO_TYPE",
        "ЗафиксированоАдресныхЦелей",
        "АдресныхЦелейВПакете",
        "ОбъектСправочника.Записать()",
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "ПостКонтроль1.КоличествоREADY = 0",
        "ПостКонтроль2.КоличествоREADY = 0",
        "ПостКонтроль1.КонтрольнаяСумма",
        "= ПостКонтроль2.КонтрольнаяСумма",
        "PASS_SAFE_BATCH",
    )
    for fragment in required:
        if fragment not in fix:
            fail(f"required [23.2] safety fragment is missing: {fragment}")
    if fix.count("= ОжидаетсяMD5Плана") != 2:
        fail("both preflight plan MD5 values must equal the fixed [23.1] baseline")
    if fix.count("= ОжидаетсяMD5Целей") != 2:
        fail("both preflight target MD5 values must equal the fixed [23.1] baseline")
    if "ОбъектСправочника.ЭтоГруппа" in fix:
        fail("[23.2] must cover both root folders and root items")

    forbidden = (
        "УдалитьОбъект",
        "УстановитьПометкуУдаления",
        "НайтиПоСсылкам",
        "ЗаменитьСсылки",
        "ЗаписатьXML",
        "ВыполнитьПакет",
        "ПрямойSQL",
    )
    for fragment in forbidden:
        if fragment in fix:
            fail(f"forbidden [23.2] operation is present: {fragment}")

    contour = fix.find("Адапт_ЭтоКонтурЗагрузка1ДляПилотаНумерации()")
    preflight = fix.find("Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников(")
    transaction = fix.find("НачатьТранзакцию()")
    if not (0 <= contour < preflight < transaction):
        fail("contour/preflight gates do not precede the first transaction")
    if fix.count("Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников(") < 4:
        fail("[23.2] must run two preflights and two postcontrols")

    wrapper = "ИсправитьБезопаснуюПартиюКодовСправочниковНаСервере"
    if f'КодОперации =\n\t\t"{wrapper}" Тогда' not in object_text:
        fail("long-operation dispatcher branch is missing")
    if wrapper not in form_text or fix_name not in form_text:
        fail("server wrapper is missing or calls the wrong object function")

    command_handler = procedure_body(
        form_text,
        "ИсправитьБезопаснуюПартиюКодовСправочников",
    )
    callback = procedure_body(
        form_text,
        "ИсправитьБезопаснуюПартиюКодовСправочниковЗавершение",
    )
    if "ПоказатьВопрос(" not in command_handler:
        fail("[23.2] has no explicit confirmation")
    answer_check = callback.find("РезультатВопроса <> КодВозвратаДиалога.Да")
    background_start = callback.find("Адапт_ЗапуститьДолгуюОперациюВФоновомРежиме(")
    if not (0 <= answer_check < background_start):
        fail("[23.2] can start before Yes confirmation")

    button = find_named(
        form_root,
        "Button",
        "ИсправитьБезопаснуюПартиюКодовСправочниковТесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.ИсправитьБезопаснуюПартиюКодовСправочников":
        fail("[23.2] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "ИсправитьБезопаснуюПартиюКодовСправочников",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "ИсправитьБезопаснуюПартиюКодовСправочников":
        fail("[23.2] command action is wrong")

    print(
        f"PASS: {version}; [23.2]=fixed-md5+double-stable-preflight+500-batches; "
        "legacy-exact-targets=477; only-marked-nonpredefined-codes; "
        "rollback+double-postcontrol; form=OK"
    )


if __name__ == "__main__":
    main()
