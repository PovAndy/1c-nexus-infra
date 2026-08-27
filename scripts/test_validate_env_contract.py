#!/usr/bin/env python3
"""Проверяет fail-closed контракт локального .env на обезличенных fixtures."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_env_contract as contract  # noqa: E402


def valid_env() -> str:
    lines = [
        "OMVL_1C_ACTIVE_TARGET=postgres3",
        "RSVDATA_TARGET=postgres3",
        "LDS_1C_BRIDGE_TARGET=postgres3",
        "LDS_1C_BRIDGE_READ_ONLY=1",
    ]
    for target in contract.TARGETS:
        lines.extend(
            [
                f"LDS_1C_BRIDGE_URL_{target.upper()}=http://host/{target}/hs/codex-test",
                f"LDS_1C_BRIDGE_URL_IP_{target.upper()}=http://127.0.0.1/{target}/hs/codex-test",
                f"LDS_1C_BRIDGE_READ_ONLY_{target.upper()}=1",
            ]
        )
    return "\n".join(lines) + "\n"


class EnvContractTests(unittest.TestCase):
    def _validate(self, content: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env.openrouter.local"
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
            return contract.validate(path)

    def test_valid_fixture_passes(self) -> None:
        self.assertEqual(self._validate(valid_env()), [])

    def test_duplicate_variable_fails(self) -> None:
        errors = self._validate(valid_env() + "LDS_1C_BRIDGE_URL_IP_POSTGRES3=http://127.0.0.1/postgres3/hs/codex-test\n")
        self.assertTrue(any("duplicate variable LDS_1C_BRIDGE_URL_IP_POSTGRES3" in error for error in errors))

    def test_target_path_mismatch_fails(self) -> None:
        errors = self._validate(valid_env().replace("/postgres7/hs/codex-test", "/postgres3/hs/codex-test", 1))
        self.assertTrue(any("target path mismatch in LDS_1C_BRIDGE_URL_POSTGRES7" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
