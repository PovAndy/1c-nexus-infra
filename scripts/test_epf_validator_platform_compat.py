#!/usr/bin/env python3
"""Регрессия валидаторов для канонического XML платформы 1С 8.3.27."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lxml import etree


ROOT = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
OBJECT_NAME = "ВыгрузкаЗагрузкаДанныхXMLАдаптивная"
ROOT_XML = ROOT / "src" / f"{OBJECT_NAME}.xml"
OBJECT_DIR = ROOT / "src" / OBJECT_NAME
FORM_XML = OBJECT_DIR / "Forms/Форма/Ext/Form.xml"
EPF_VALIDATOR = ROOT / ".gemini/skills/epf-validate/scripts/epf-validate.py"
FORM_VALIDATOR = Path(
    os.getenv(
        "NEXUS_FORM_VALIDATOR",
        str(Path.home() / ".codex/skills/form-validate/scripts/form-validate.py"),
    )
)
VENV_PYTHON = Path(
    os.getenv("NEXUS_PYTHON_BIN", str(ROOT / ".venv-gemini-bridge/bin/python"))
)


def run_validator(script: Path, argument: str, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VENV_PYTHON), str(script), argument, str(target), "-Detailed"],
        check=False,
        capture_output=True,
        text=True,
    )


def saved_settings_attribute(tree: etree._ElementTree) -> etree._Element:
    matches = tree.xpath(
        '//*[local-name()="Attribute"]'
        '[.//*[local-name()="Name" and text()="СохраненныеНастройки"]]'
    )
    if len(matches) != 1:
        raise AssertionError(f"expected one СохраненныеНастройки attribute, found {len(matches)}")
    return matches[0]


def main() -> None:
    epf_result = run_validator(EPF_VALIDATOR, "-ObjectPath", ROOT_XML)
    if epf_result.returncode != 0 or "[ERROR]" in epf_result.stdout:
        raise AssertionError(epf_result.stdout + epf_result.stderr)
    if "Unusual version '2.18'" in epf_result.stdout:
        raise AssertionError("canonical MetaDataObject version 2.18 is still rejected")

    form_result = run_validator(FORM_VALIDATOR, "-FormPath", FORM_XML)
    if form_result.returncode != 0 or "[ERROR]" in form_result.stdout:
        raise AssertionError(form_result.stdout + form_result.stderr)
    if "Form version='2.18'" in form_result.stdout:
        raise AssertionError("canonical Form version 2.18 is still rejected")

    with tempfile.TemporaryDirectory(prefix="epf-validator-negative-") as temp_name:
        temp_root = Path(temp_name)
        temp_xml = temp_root / f"{OBJECT_NAME}.xml"
        temp_object_dir = temp_root / OBJECT_NAME
        shutil.copy2(ROOT_XML, temp_xml)
        shutil.copytree(OBJECT_DIR, temp_object_dir)

        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(str(temp_xml), parser)
        attribute = saved_settings_attribute(tree)
        type_node = attribute.xpath('.//*[local-name()="Type"]')[0]
        type_node.append(etree.Element("UnknownType"))
        tree.write(str(temp_xml), encoding="utf-8", xml_declaration=True)
        unknown_result = run_validator(EPF_VALIDATOR, "-ObjectPath", temp_xml)
        if unknown_result.returncode == 0 or "Type block has no" not in unknown_result.stdout:
            raise AssertionError("unknown Type content must remain an error")

        tree = etree.parse(str(ROOT_XML), parser)
        attribute = saved_settings_attribute(tree)
        type_node = attribute.xpath('.//*[local-name()="Type"]')[0]
        type_node.getparent().remove(type_node)
        tree.write(str(temp_xml), encoding="utf-8", xml_declaration=True)
        missing_result = run_validator(EPF_VALIDATOR, "-ObjectPath", temp_xml)
        if missing_result.returncode == 0 or "missing Type block" not in missing_result.stdout:
            raise AssertionError("missing Type element must remain an error")

    print(
        "PASS: MetaDataObject/Form 2.18 accepted; "
        "platform-empty СохраненныеНастройки accepted; unknown/missing Type rejected"
    )


if __name__ == "__main__":
    main()
