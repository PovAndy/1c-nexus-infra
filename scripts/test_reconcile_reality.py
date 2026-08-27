#!/usr/bin/env python3
"""Проверки детерминированной сверки состояния рабочей среды."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from reconcile_reality import parse_handover, reconcile


class RealityReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "build").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "temp").mkdir()
        compiled = self.root / "build" / "compiled.epf"
        compiled.write_bytes(b"known-compiled-epf")
        digest = hashlib.sha256(compiled.read_bytes()).hexdigest()
        (self.root / "docs" / "ACTIVE_HANDOVER.md").write_text(
            'Srvr="SSRV01";Ref="postgres3";\nТекущий рабочий файл отличается (SHA-256 `' + digest + '`)\n', encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_parses_active_facts(self) -> None:
        facts = parse_handover(self.root / "docs" / "ACTIVE_HANDOVER.md")
        self.assertEqual(facts.database_target, "postgres3")
        self.assertEqual(len(facts.compiled_sha256), 64)

    def test_baseline_then_detects_git_drift(self) -> None:
        state = self.root / "temp" / "reality.state.json"
        self.assertTrue(reconcile(self.root, self.root / "docs" / "ACTIVE_HANDOVER.md", state, False)[0])
        (self.root / "docs" / "ACTIVE_HANDOVER.md").write_text(
            (self.root / "docs" / "ACTIVE_HANDOVER.md").read_text(encoding="utf-8") + "изменение\n",
            encoding="utf-8",
        )
        passed, details = reconcile(self.root, self.root / "docs" / "ACTIVE_HANDOVER.md", state, False)
        self.assertFalse(passed)
        self.assertTrue(any("status_sha256" in item for item in details))

    def test_detects_compiled_hash_mismatch(self) -> None:
        state = self.root / "temp" / "reality.state.json"
        (self.root / "build" / "compiled.epf").write_bytes(b"unexpected")
        passed, details = reconcile(self.root, self.root / "docs" / "ACTIVE_HANDOVER.md", state, True)
        self.assertFalse(passed)
        self.assertTrue(any("SHA-256" in item for item in details))


if __name__ == "__main__":
    unittest.main()
