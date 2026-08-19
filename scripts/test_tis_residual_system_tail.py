#!/usr/bin/env python3
from epf_test_utils import current_processing_version, version_return_marker
"""Static safety checks for the six-record TiS system tail."""

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


def require(condition: bool, message: str) -> None:
    assert condition, message


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
        '"AFTER_SYSTEM_TAIL_FIX"',
        '"D41D8CD98F00B204E9800998ECF8427E"',
        "Функция Адапт_ТиСПостроитьПланСистемногоХвоста(",
        "Функция Адапт_PreviewСистемногоХвостаТиС() Экспорт",
        "Функция Адапт_ИсправитьСистемныйХвостТиС() Экспорт",
        "Адапт_ТиСУдалитьЕдинственнуюЗаписьСистемногоРегистра(",
        'Таблица.Колонки.Добавить("ЗначениеЦели");',
        "СтрокаОстатка.ЗначениеЦели = ЗначениеЦели;",
        "UUIDПроверяемогоЗначения = НРег(",
        "РежимЗаписиДокумента.Проведение",
        "План.КоличествоОпераций <> 6",
        'ФазаПосле.Код <> "AFTER_SYSTEM_TAIL_FIX"',
        "ОстаткиПосле.Количество() <> 0",
        "РодителиПосле.Количество() <> 0",
        "ЗафиксироватьТранзакцию();",
        "ОтменитьТранзакцию();",
        "STOP_ROLLBACK",
    )
    for fragment in required:
        require(fragment in object_text, f"missing object fragment: {fragment}")

    strict_evidence = (
        "4c63955e-e3f1-11ef-93d7-5ce42a229ae2",
        "00407f22-6296-11ec-8c61-000c29792c49",
        "cf043298-2249-4c15-9ffd-b3e2cb119792",
        "8759a478-9c71-11ed-92f2-c018505cf1e0",
        "8672578a-188a-11f1-aba0-e89c257e84aa",
        "2dfa55bf-4474-11e8-a26c-6c626d5c193b",
        "53234a02-e3f1-11ef-93d7-5ce42a229ae2",
    )
    plan = function_block(
        object_text, "Адапт_ТиСПостроитьПланСистемногоХвоста"
    )
    for fragment in (
        "ТолькоЧтение = Ложь",
        "Адапт_ТиСЭтоРазрешенныйКонтурТолькоЧтение()",
        "Адапт_ТиСЭтоРазрешенныйКонтур();",
    ):
        require(fragment in plan, f"system-plan contour separation is missing: {fragment}")
    require(
        'Адапт_ТиСПостроитьПланСистемногоХвоста("[22.18]", Истина)'
        in object_text,
        "system Preview is not explicitly read-only",
    )
    require(
        'Адапт_ТиСПостроитьПланСистемногоХвоста("[22.19]")'
        in object_text,
        "system Fix is not protected by the strict default contour",
    )
    for value in strict_evidence:
        require(value in plan, f"strict evidence is missing: {value}")
    require(
        plan.count("И UUIDПроверяемогоЗначения = UUIDЦели Тогда") == 4,
        "four register-dimension rows are not tied to the exact raw target",
    )
    require(
        "И UUIDИсточника = UUIDЦели Тогда" not in plan,
        "obsolete register classifier still relies on a record-source UUID",
    )
    for field in (
        "ВладелецБезопасногоХранилища",
        "КорреспондентТранспорта",
        "УзелОбщихНастроек",
        "СписокОбновленияКлючей",
    ):
        assignment = (
            f"План.{field} =\n"
            "\t\t\t\tСтрокаОстатка.ЗначениеЦели;"
        )
        require(
            assignment in plan,
            f"{field} does not retain the exact register-dimension value",
        )

    preview = function_block(
        object_text, "Адапт_PreviewСистемногоХвостаТиС"
    )
    for fragment in (
        ".Записать(",
        "НачатьТранзакцию(",
        "ЗафиксироватьТранзакцию(",
        "ОтменитьТранзакцию(",
    ):
        require(
            fragment not in preview,
            f"read-only system preview contains mutation: {fragment}",
        )

    fix = function_block(
        object_text, "Адапт_ИсправитьСистемныйХвостТиС"
    )
    require(
        fix.find("ЗафиксироватьТранзакцию();")
        > fix.find('ФазаПосле.Код <> "AFTER_SYSTEM_TAIL_FIX"'),
        "system tail commits before exact 0+0 phase control",
    )
    require(
        "ОбщегоНазначения.ЗаменитьСсылки" not in fix,
        "system tail contains global reference replacement",
    )

    for fragment in (
        "Процедура PreviewСистемногоХвостаТиС(Команда)",
        '"tis_residual_system_preview"',
        "Процедура ИсправитьСистемныйХвостТиС(Команда)",
        '"tis_residual_system_fix"',
    ):
        require(fragment in form_text, f"missing form route: {fragment}")

    for fragment in (
        "Системный хвост [22.18–22.19]",
        "[22.18] Preview системного хвоста (~00:15)",
        "[22.19] Исправить системный хвост (~00:25)",
        "[22.12–22.18] Все ReadOnly (~01:35)",
    ):
        require(fragment in form_xml, f"missing form presentation: {fragment}")

    print(
        "PASS: system tail=6 operations; standard record sets/reposting=ON; "
        "atomic post-control=0+0/D41D8C; read-only preview=ON"
    )


if __name__ == "__main__":
    main()
