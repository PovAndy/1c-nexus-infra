#!/usr/bin/env python3
"""Статический контракт адресного исправления [24.7]."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from epf_test_utils import current_processing_version, require_form_version


ROOT = Path(__file__).resolve().parents[1]
OBJECT_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Ext/ObjectModule.bsl"
FORM_MODULE = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form/Module.bsl"
FORM_XML = ROOT / "src/ВыгрузкаЗагрузкаДанныхXMLАдаптивная/Forms/Форма/Ext/Form.xml"
TARGET_MODULE = (
    ROOT
    / "context/config-dumps/target_1_0_36_14_full"
    / "CommonModules/КадровыйУчет/Ext/Module.bsl"
)
TARGET_TEMPLATE = (
    ROOT
    / "context/config-dumps/target_1_0_36_14_full"
    / "Catalogs/ОснованияУвольнения/Templates/ОснованияУвольненияПоТКРФ/Ext/Template.txt"
)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


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
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_xml_text = FORM_XML.read_text(encoding="utf-8-sig")
    form_root = ET.fromstring(form_xml_text)
    target_module = TARGET_MODULE.read_text(encoding="utf-8-sig")
    template_text = TARGET_TEMPLATE.read_text(encoding="utf-8-sig")

    version = current_processing_version(object_text, 127)
    require_form_version(form_xml_text, version)

    plan = function_body(
        object_text,
        "Адапт_СобратьПланКарантинаОснованийУвольнения36_14",
    )
    postcontrol = function_body(
        object_text,
        "Адапт_СформироватьПостконтрольКарантинаОснованийУвольнения36_14",
    )
    fix = function_body(
        object_text,
        "Адапт_ИсправитьКарантинОснованийУвольнения36_14",
    )

    for required in (
        "6A9EDD288D3D2E31E3D121A634979529",
        "Результат.ВсегоЭлементов = 1835",
        "Результат.АктивныхЭлементов = 1760",
        "Результат.АктивныхUUIDИсточника01 = 103",
        "Результат.ЦелевыхГрупп = 103",
        "Результат.LegacyГрупп = 2",
        "Результат.Операций = 1648",
        "Результат.АктивныхОпераций = 1648",
        "Результат.СемантическихРасхождений = 560",
        "Результат.СсылокВсего = 0",
        "КандидатыПредопределенные.Количество() = 1",
        "КандидатыИсточника01.Количество() = 1",
        "Если Активные.Количество() <= 1 Тогда",
        "Для Каждого Элемент Из Активные Цикл",
        "Адапт_ЭтоLegacyГруппаОснованийУвольнения36_14(Ключ)",
        "DISMISSAL_BASES_36_14_PREVIEW_V1",
    ):
        if required not in plan:
            fail(f"[24.7] plan invariant is missing: {required}")

    for required in (
        'ВРег("СТ. 336.3")',
        'ВРег("СТ. 337")',
    ):
        if required not in object_text:
            fail(f"[24.7] legacy exclusion is missing: {required}")

    for required in (
        "ОжидаетсяОпераций = 1648",
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "Адапт_ЭтоКонтурMergedBaseДляПодготовкиОбновления()",
        "ОбъектОснования.ДополнительныеСвойства.Вставить(",
        '"ЗаписьОбщихДанных", Истина)',
        "ОбъектОснования.ПометкаУдаления = Истина",
        "ОбновлениеИнформационнойБазы.ЗаписатьОбъект(ОбъектОснования)",
        "STOP_OBJECT_STATE",
        "STOP_POST_WRITE",
        "STOP_ROLLBACK",
        "PASS_ALREADY_APPLIED",
        "ПостконтрольВТранзакции",
        "ПостконтрольПослеCommit",
        "POSTCONTROL_STABLE",
    ):
        if required not in fix:
            fail(f"[24.7] safety fragment is missing: {required}")

    if fix.count("НачатьТранзакцию()") != 1:
        fail("[24.7] must start exactly one transaction")
    if fix.count("ОбновлениеИнформационнойБазы.ЗаписатьОбъект(") != 1:
        fail("[24.7] must have exactly one guarded object-write call")
    flag_pos = fix.find("ОбъектОснования.ДополнительныеСвойства.Вставить(")
    mark_pos = fix.find("ОбъектОснования.ПометкаУдаления = Истина")
    write_pos = fix.find(
        "ОбновлениеИнформационнойБазы.ЗаписатьОбъект(ОбъектОснования)"
    )
    if not (flag_pos < mark_pos < write_pos):
        fail("[24.7] common-data flag must precede mark and object write")

    for forbidden in (
        "ОбъектОснования.Код =",
        "ОбъектОснования.Наименование =",
        "ОбъектОснования.ТекстОснования =",
        "ОбъектОснования.Статья =",
        "ОбъектОснования.Часть =",
        "ОбъектОснования.Пункт =",
        "ОбъектОснования.Подпункт =",
        "ОбъектОснования.Абзац =",
        "ОбъектОснования.ДокументОснование =",
        "ОбъектОснования.СрокДействия =",
        "ОбъектОснования.ПричинаУвольненияПФР =",
        "ОбъектОснования.ИмяПредопределенныхДанных =",
        "ОбъектОснования.ОбменДанными.Загрузка",
        "ОбъектОснования.Записать()",
        "ОбщегоНазначения.ЗаменитьСсылки",
        "ВыполнитьПрямойSQL",
        ".Удалить(",
    ):
        if forbidden in fix:
            fail(f"[24.7] forbidden mutation found: {forbidden}")

    for required in (
        "Результат.ВсегоЭлементов = 1835",
        "Результат.АктивныхЭлементов = 112",
        "Результат.АктивныхUUIDИсточника01 = 103",
        "Результат.ПровереноОпераций = План.Количество()",
        "Результат.АктивныхОпераций = 0",
        "Результат.АктивныхЦелевыхГрупп = 0",
        "Результат.LegacyГрупп = 2",
        "Результат.СсылокВсего = 0",
    ):
        if required not in postcontrol:
            fail(f"[24.7] postcontrol invariant is missing: {required}")

    if plan.find("Если Не Элемент.ПометкаУдаления Тогда") > plan.find(
        "КандидатыПредопределенные.Добавить(Элемент)"
    ):
        fail("[24.7] canonical candidates must be collected only inside active gate")
    target_loop = plan[plan.find("Результат.ЦелевыхГрупп =") :]
    if "Для Каждого Элемент Из Активные Цикл" not in target_loop:
        fail("[24.7] plan must exclude previously marked physical duplicates")
    for required in (
        "И Результат.ЦелевыхГрупп = 0",
        "И Результат.Операций = 0",
        "И Результат.СемантическихРасхождений = 0",
    ):
        if required not in plan:
            fail(f"[24.7] idempotent-state invariant is missing: {required}")
    if "Результат.ПровереноОпераций = План.Количество()" not in postcontrol:
        fail("[24.7] postcontrol must accept exact current plan size")

    operation = "ИсправитьКарантинОснованийУвольнения36_14V127НаСервере"
    if operation not in object_text or operation not in form_text:
        fail("[24.7] unique long-operation route is missing")
    if "Процедура ИсправитьКарантинОснованийУвольнения36_14(Команда)" not in form_text:
        fail("[24.7] client handler is missing")
    if "Функция ИсправитьКарантинОснованийУвольнения36_14НаСервере()" not in form_text:
        fail("[24.7] server wrapper is missing")
    if form_text.count('ИмяСценария = "fix-dismissal-bases-36-14"') != 2:
        fail("[24.7] client/server autorun routes are missing")

    button = find_named(
        form_root,
        "Button",
        "ИсправитьКарантинОснованийУвольнения36_14Тесты",
    )
    command_name = next(
        (child.text for child in button if local_name(child) == "CommandName"),
        None,
    )
    if command_name != "Form.Command.ИсправитьКарантинОснованийУвольнения36_14":
        fail("[24.7] button is wired to the wrong command")
    command = find_named(
        form_root,
        "Command",
        "ИсправитьКарантинОснованийУвольнения36_14",
    )
    action = next(
        (child.text for child in command if local_name(child) == "Action"),
        None,
    )
    if action != "ИсправитьКарантинОснованийУвольнения36_14":
        fail("[24.7] command action is incorrect")

    if "НЕ ОснованияУвольнения.ПометкаУдаления" not in target_module:
        fail("target 36.14 loader must ignore marked duplicates")
    root = ET.fromstring(template_text)
    titles = {item.attrib.get("Title", "").casefold() for item in root}
    if "ст. 336.3".casefold() in titles or "ст. 337".casefold() in titles:
        fail("legacy exclusions unexpectedly occur in target 36.14 template")

    print(
        f"PASS: {version}; [24.7]=one-transaction-mark-only; "
        "plan=1648; canonical-groups=103; legacy-keep=2; "
        "postcontrol=double; target-loader=active-only"
    )


if __name__ == "__main__":
    main()
