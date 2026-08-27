#!/usr/bin/env python3
"""Проверки валидатора компактных manifests агентских навыков."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from validate_agent_skills import validate_skill


class AgentSkillValidationTests(unittest.TestCase):
    def test_accepts_compact_triggered_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "sample-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                '---\nname: sample-skill\ndescription: "Триггер: X. Антитриггер: Y."\n---\n# X\n', encoding="utf-8")
            self.assertEqual(validate_skill(skill), [])

    def test_rejects_missing_antitrigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "sample-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                '---\nname: sample-skill\ndescription: "Триггер: X."\n---\n# X\n', encoding="utf-8")
            self.assertTrue(validate_skill(skill))


if __name__ == "__main__":
    unittest.main()
