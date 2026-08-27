#!/usr/bin/env python3
"""Изолированно проверяет stdin-JSON hooks без баз, LLM и внешних сервисов."""

from __future__ import annotations

import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_hook  # noqa: E402
from hooks import stop_hook_gate_check  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class HooksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prefix = f".hook-test-{os.getpid()}-{time.time_ns()}"
        self.created: list[Path] = []

    def tearDown(self) -> None:
        for path in self.created:
            path.unlink(missing_ok=True)
        for backup in (ROOT / "archive" / "backups").glob(f"*_{self.prefix}*"):
            backup.unlink(missing_ok=True)
        stop_hook_gate_check.STATE_PATH.unlink(missing_ok=True)

    def _fixture(self, suffix: str, content: str) -> Path:
        path = ROOT / f"{self.prefix}{suffix}"
        path.write_text(content, encoding="utf-8")
        self.created.append(path)
        return path

    def _invoke(self, event: str, payload: str) -> tuple[int, str, str]:
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["run_hook.py", event]), patch.object(sys, "stdin", io.StringIO(payload)), redirect_stderr(stderr), redirect_stdout(stdout):
            code = run_hook.main()
        return code, stderr.getvalue(), stdout.getvalue()

    def test_stdin_pre_write_creates_backup(self) -> None:
        target = self._fixture(".bsl", "Процедура Тест()\nКонецПроцедуры\n")
        patch_input = f"*** Update File: {target.name}\n@@\n-текст\n+текст\n"
        code, stderr, stdout = self._invoke("pre-write", json.dumps({"tool_name": "apply_patch", "tool_input": {"command": patch_input}}))
        backups = list((ROOT / "archive" / "backups").glob(f"*_{target.name}.bak"))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(len(backups), 1)
        self.created.extend(backups)

    def test_non_bsl_stdin_event_exits_immediately(self) -> None:
        target = self._fixture(".md", "текст\n")
        started = time.perf_counter()
        code, stderr, stdout = self._invoke("post-write", f'{{"tool_input":{{"file_path":"{target.name}"}}}}')
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertLess(time.perf_counter() - started, 0.005)

    def test_dirty_bsl_blocks_with_structured_reason(self) -> None:
        target = self._fixture(".bsl", "Процедура Тест()\nСостояние();\nКонецПроцедуры\n")
        with patch.object(run_hook, "evaluate_target", return_value=(2, '{"kind":"server_forbidden_ui_call"}')):
            code, stderr, stdout = self._invoke("post-write", f'{{"tool_input":{{"file_path":"{target.name}"}}}}')
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("server_forbidden_ui_call", stderr)

    def test_clean_bsl_passes(self) -> None:
        target = self._fixture(".bsl", "Процедура Тест()\nКонецПроцедуры\n")
        with patch.object(run_hook, "evaluate_target", return_value=(0, "")):
            code, stderr, stdout = self._invoke("post-write", f'{{"tool_input":{{"file_path":"{target.name}"}}}}')
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")

    def test_stop_hook_escalates_after_five_unchanged_failures(self) -> None:
        runner = lambda *args, **kwargs: 1
        for _ in range(4):
            code, detail = stop_hook_gate_check.check_stop(gate_runner=runner)
            self.assertEqual(code, 2)
            self.assertIn("gates_unmet", detail)
        code, detail = stop_hook_gate_check.check_stop(gate_runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("stop_hook_escalation", detail)
        with patch.object(run_hook, "check_stop", return_value=(0, "")):
            code, stderr, stdout = self._invoke("stop-hook", "{}")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout), {"continue": True})


if __name__ == "__main__":
    unittest.main()
