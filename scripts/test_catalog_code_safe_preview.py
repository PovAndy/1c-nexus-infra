#!/usr/bin/env python3
"""Static safety contract for [23.1] catalog-code ReadOnly preview."""

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
    form_xml_text = FORM_XML.read_text(encoding="utf-8-sig")
    form_root = ET.fromstring(form_xml_text)

    if version_return_marker(version) not in object_text:
        fail("unexpected processing version")

    preview_name = "Адапт_СформироватьPreviewБезопаснойПартииКодовСправочников"
    helper_name = "Адапт_ТаблицаБезопасныхПомеченныхКандидатовКодовСправочника"
    preview = function_body(object_text, preview_name)
    helper = function_body(object_text, helper_name)

    serializable_contract = re.search(
        r"Если\s+ВозвращатьТаблицуПлана\s+Тогда\s+"
        r"Результат\.Вставить\(\"ТаблицаПлана\",\s*ТаблицаПлана\);\s+"
        r"КонецЕсли;",
        preview,
        flags=re.DOTALL,
    )
    if serializable_contract is None:
        fail("[23.1] must not return ValueTable without an explicit internal flag")
    if "ВозвращатьТаблицуПлана = Ложь" not in object_text:
        fail("[23.1] public serialization-safe default is missing")

    for forbidden in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "УстановитьНовыйКод(",
        "НайтиПоСсылкам(",
        "ВыполнитьПакет(",
    ):
        if forbidden in preview or forbidden in helper:
            fail(f"write/risky operation is present in [23.1]: {forbidden}")

    required_fragments = (
        "CODE_SAFE_MARKED_TAIL_V1",
        "ЭлементыСправочника.ПометкаУдаления",
        "И НЕ ЭлементыСправочника.Предопределенный",
        "КОГДА НЕ ЭлементыГруппы.ПометкаУдаления",
        "КОНЕЦ) = 1",
        "ПомеченоПредопределенных",
        "MD5 точного плана UUID",
        "CODE_SAFE_EXACT_TARGET_V1",
        "EXACT_UUID_PREFIX_V1",
        "EXACT_NO_AUTO_UUID_V1",
        "EXACT_NO_AUTO_ZHEX_V1",
        "Адапт_ТехническийКодДубляРаскрытияПоUUID",
        "Адапт_ЗанятыеКодыПоОбластямСправочника",
        "Адапт_ЭтоLegacyСправочникБезАвтонумерации",
        "УдалитьПараметрыИсчисляемогоСтраховогоСтажа2014",
        "УдалитьТерриториальныеУсловия",
        "УдалитьТерриториальныеУсловияПФР",
        "Адапт_ТехническийКороткийКодПоНомеру",
        "Адапт_СледующийСвободныйКороткийТехническийКод",
        "Адапт_ЭтоСправочникШтатногоХвостаКодов",
        "Z\" + Лев(UUIDБезРазделителей, 8)",
        "СтрДлина(ЦелевойКод) <> 9",
        'КлючОбласти + "|" + НРег(ЦелевойКод)',
        "ЗанятыеКодыТочногоРежима.Получить(",
        "КонтрольнаяСуммаЦелей",
        "КоличествоАдресныхЦелей",
        "активные коллизии и полностью помеченные группы".capitalize(),
    )
    combined = preview + helper + object_text
    for fragment in required_fragments:
        if fragment not in combined:
            fail(f"required [23.1] safety fragment is missing: {fragment}")
    if "ЭтоКорневаяОбласть" in preview:
        fail("[23.1] exact UUID targets must cover subordinate items too")
    if "Кандидат.ЭтоГруппа" in preview:
        fail("[23.1] must cover both root folders and root items")

    wrapper = "PreviewБезопаснойПартииКодовСправочниковНаСервере"
    if wrapper not in form_text:
        fail("server wrapper is missing")
    if f'КодОперации =\n\t\t"{wrapper}" Тогда' not in object_text:
        fail("long-operation dispatcher branch is missing")
    if preview_name not in form_text:
        fail("form wrapper does not call the object preview")

    button = find_named(
        form_root,
        "Button",
        "PreviewБезопаснойПартииКодовСправочниковТесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.PreviewБезопаснойПартииКодовСправочников":
        fail("[23.1] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "PreviewБезопаснойПартииКодовСправочников",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "PreviewБезопаснойПартииКодовСправочников":
        fail("[23.1] command action is wrong")

    print(
        f"PASS: {version}; [23.1]=readonly+XDTO-safe; exact_uuid_md5=present; "
        "scoped_uuid8_and_zhex_targets=present; active_and_predefined=protected; "
        "background_dispatch=closed; form_wiring=OK"
    )


if __name__ == "__main__":
    main()
