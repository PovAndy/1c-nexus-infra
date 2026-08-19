#!/usr/bin/env python3
"""Static fail-closed checks for stages [24.2]-[24.3]."""

from __future__ import annotations

import re
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


def function_body(text: str, name: str) -> str:
    pattern = re.compile(
        rf"^Функция\s+{re.escape(name)}\([\s\S]*?^КонецФункции\s*$",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"function not found: {name}")
    return match.group(0)


def main() -> None:
    object_text = OBJECT_MODULE.read_text(encoding="utf-8-sig")
    form_text = FORM_MODULE.read_text(encoding="utf-8-sig")
    form_xml = FORM_XML.read_text(encoding="utf-8-sig")

    assert re.search(r'Возврат "v25-(?:122\.(?:11[7-9]|1[2-9][0-9]|[2-9][0-9]{2,})|(?:12[3-9]|1[3-9][0-9]|[2-9][0-9]{2,})\.\d+)";', object_text)
    name = "Адапт_СформироватьPreviewКонсолидацииРегламентированныхОтчетов36_14"
    body = function_body(object_text, name)

    required = (
        "24BC3B2A94742F59C4605D46CDB2F339",
        "EB857B2DD617A852AFF8FFFFA6DF4EB8A0B5AEE673BD74BB471632DDBFC798C9",
        "Канонов <> 300",
        "Операций <> 4800",
        "РодительскихПерепривязок <> 4608",
        "REGREPORTS_QUARANTINE_PLAN_V2",
        "ПланКарантина.Сортировать(\"UUID Возр\")",
        "Адапт_СледующийСвободныйТехническийКодBase36",
        "НесовпаденийКодов = НесовпаденийКодов + 1",
        "СсылокВсего <> 5153",
        "СсылокФормСтатистики <> 544",
        "СсылокСкрытыхОтчетов <> 1",
        "СтрокаСсылки.Данные",
        "PASS_QUARANTINE_PLAN",
        "НайтиПоСсылкам(НеканоническиеСсылки)",
        "MD5 адресного плана",
        "Адапт_ЭтоКонтурПодготовкиОбновленияТолькоЧтение",
        "ПланКарантина",
        "UUIDРодителя",
    )
    for marker in required:
        assert marker in body, marker

    forbidden_calls = (
        r"\bНачатьТранзакцию\s*\(",
        r"\bЗафиксироватьТранзакцию\s*\(",
        r"\bОтменитьТранзакцию\s*\(",
        r"\.Записать\s*\(",
        r"\.УстановитьПометкуУдаления\s*\(",
        r"\.Удалить\s*\(",
    )
    for pattern in forbidden_calls:
        assert not re.search(pattern, body, re.IGNORECASE), pattern

    operation = "PreviewКонсолидацииРегламентированныхОтчетов36_14НаСервере"
    assert operation in object_text
    assert operation in form_text
    assert "PreviewКонсолидацииРегламентированныхОтчетов36_14" in form_text
    assert "Form.Command.PreviewКонсолидацииРегламентированныхОтчетов36_14" in form_xml
    assert "[24.2] Preview консолидации отчетов" in form_xml

    write_name = (
        "Адапт_ИсправитьКарантинРегламентированныхОтчетов36_14"
    )
    write_body = function_body(object_text, write_name)
    post_name = (
        "Адапт_СформироватьПостконтрольКарантина"
        "РегламентированныхОтчетов36_14"
    )
    post_body = function_body(object_text, post_name)

    write_required = (
        "36E0CD90D8AF2881A5641A2E3FD57EE1",
        "НачатьТранзакцию()",
        "ЗафиксироватьТранзакцию()",
        "ОтменитьТранзакцию()",
        "ОбъектОтчета.ПометкаУдаления = Истина",
        "ОбъектОтчета.Наименование =",
        "ОбъектОтчета.ИсточникОтчета =",
        "POSTCONTROL_STABLE",
        "ПостконтрольВТранзакции",
        "ПостконтрольПослеCommit",
    )
    for marker in write_required:
        assert marker in write_body, marker
    assert "ТранзакцияНачата И ТранзакцияАктивна()" in write_body
    assert not re.search(r"\bТранзакцияНача\b", object_text)
    assert "PASS_ALREADY_APPLIED" in write_body
    assert (
        "Адапт_СформироватьПостконтрольКарантина"
        "РегламентированныхОтчетов36_14()"
    ) in write_body
    assert 'Preflight1.Свойство("КонтрольнаяСуммаПлана"' in write_body
    assert 'Preflight2.Свойство("КонтрольнаяСуммаПлана"' in write_body
    assert "Preflight1.КонтрольнаяСуммаПлана" not in write_body
    assert "Preflight2.КонтрольнаяСуммаПлана" not in write_body
    preview_contract_position = body.index(
        'Результат.Вставить("КонтрольнаяСуммаПлана", "")'
    )
    preview_first_early_return = body.index("Возврат Результат;")
    assert preview_contract_position < preview_first_early_return

    post_required = (
        "REGREPORTS_QUARANTINE_POST_V1",
        "Коды.Количество() = 5100",
        "СемантическиеКлючи.Количество() = 5100",
        "Дублей = 4800",
        "СсылокВсего = 5153",
        "СсылокФорм = 544",
        "СсылокСкрытых = 1",
    )
    for marker in post_required:
        assert marker in post_body, marker
    assert (
        "Отчеты.ИмяПредопределенныхДанных КАК "
        "ИмяПредопределенныхДанных"
    ) in post_body
    assert "ИмяПределенныхДанных" not in object_text

    forbidden_write = (
        r"\.\s*Удалить\s*\(",
        r"ЗаменитьСсылки\s*\(",
        r"ВыполнитьПрямойSQL\s*\(",
    )
    for pattern in forbidden_write:
        assert not re.search(pattern, write_body, re.IGNORECASE), pattern

    write_operation = (
        "ИсправитьКарантинРегламентированныхОтчетов36_14V120НаСервере"
    )
    assert write_operation in object_text
    assert write_operation in form_text
    assert (
        '"ИсправитьКарантинРегламентированныхОтчетов36_14НаСервере" Тогда'
        not in object_text
    )
    assert "Form.Command.ИсправитьКарантинРегламентированныхОтчетов36_14" in form_xml
    assert "[24.3] Исправить карантин отчетов" in form_xml
    assert re.search(r"v25-(?:122\.(?:11[7-9]|1[2-9][0-9]|[2-9][0-9]{2,})|(?:12[3-9]|1[3-9][0-9]|[2-9][0-9]{2,})\.\d+)", form_xml)

    print(
        "PASS: [24.2]-[24.3] wired; exact plan, one transaction, rollback and "
        "double postcontrol gates present"
    )


if __name__ == "__main__":
    main()
