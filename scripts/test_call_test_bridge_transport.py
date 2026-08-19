#!/usr/bin/env python3
"""Проверяет выбор транспорта CodexTestBridge без сети и без базы данных."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import call_test_bridge as bridge


class BridgeTransportTests(unittest.TestCase):
    """Проверяет короткий direct fallback и приоритет Windows в WSL."""

    def test_direct_timeout_default_and_bounds(self) -> None:
        with patch.dict(os.environ, {bridge.DIRECT_TIMEOUT_ENV: "4"}, clear=False):
            self.assertEqual(bridge._direct_timeout_seconds(), 4.0)
        with patch.dict(os.environ, {bridge.DIRECT_TIMEOUT_ENV: "11"}, clear=False):
            with self.assertRaises(RuntimeError):
                bridge._direct_timeout_seconds()

    def test_windows_transport_is_primary_in_wsl(self) -> None:
        calls: list[str] = []

        def windows(url: str, payload: object = None) -> dict[str, object]:
            calls.append("windows")
            return {"ok": True, "transport": "windows_powershell"}

        def direct(url: str, payload: object = None) -> dict[str, object]:
            calls.append("direct")
            return {"ok": True, "transport": "direct"}

        with (
            patch.object(bridge, "_candidate_base_urls", return_value=["http://bridge/hs/codex-test"]),
            patch.object(bridge, "_is_wsl", return_value=True),
            patch.object(bridge, "_request_json_windows", side_effect=windows),
            patch.object(bridge, "_request_json", side_effect=direct),
            patch.dict(os.environ, {bridge.WINDOWS_FIRST_ENV: "1"}, clear=False),
        ):
            result = bridge.call_bridge("Health")
        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["windows"])
        self.assertEqual(result["transport"], "windows_powershell")

    def test_direct_is_used_only_after_windows_failure(self) -> None:
        calls: list[str] = []

        def windows(url: str, payload: object = None) -> dict[str, object]:
            calls.append("windows")
            return {"ok": False, "error": "windows_http_error"}

        def direct(url: str, payload: object = None) -> dict[str, object]:
            calls.append("direct")
            return {"ok": True, "transport": "direct"}

        with (
            patch.object(bridge, "_candidate_base_urls", return_value=["http://bridge/hs/codex-test"]),
            patch.object(bridge, "_is_wsl", return_value=True),
            patch.object(bridge, "_request_json_windows", side_effect=windows),
            patch.object(bridge, "_request_json", side_effect=direct),
            patch.dict(os.environ, {bridge.WINDOWS_FIRST_ENV: "1"}, clear=False),
        ):
            result = bridge.call_bridge("Health")
        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["windows", "direct"])
        self.assertEqual(result["transport"], "direct")


if __name__ == "__main__":
    unittest.main()
