#!/usr/bin/env python3
"""Локальные тесты оценщика Adaptive Best-of-N без моделей и баз данных."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from eval_bsl_candidate import adaptive_decision, evaluate_candidate


def _passed_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args[0], 0, "", "")


def _failed_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args[0], 1, "", "Синтаксическая ошибка")


class EvalBslCandidateTests(unittest.TestCase):
    """Проверяет штрафы и экономный выбор, не вызывая внешний контур."""

    def _candidate(self, text: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "candidate.bsl"
        path.write_text(text, encoding="utf-8")
        return path

    def test_fast_path_accepts_clean_candidate(self) -> None:
        result = evaluate_candidate(self._candidate("Процедура Тест()\nКонецПроцедуры"), runner=_passed_runner)
        self.assertEqual(result["cost"], 0)
        self.assertEqual(adaptive_decision([result])["status"], "ACCEPTED_FAST_PATH")

    def test_penalties_are_additive_and_metadata_is_anchored(self) -> None:
        result = evaluate_candidate(
            self._candidate(
                "ВЫБРАТЬ Т.Ref AS Код ПОМЕСТИТЬ ВТТест ИЗ Справочники.Тест AS Т; "
                "Запрос.Выполнить()"
            ),
            runner=_failed_runner,
        )
        self.assertEqual(result["cost"], 1900)
        self.assertEqual({issue["kind"] for issue in result["issues"]}, {"syntax", "tempdb_leak", "bsl_linter", "unanchored_metadata"})

    def test_fallback_requires_exactly_two_variations(self) -> None:
        rejected = evaluate_candidate(self._candidate("ПОМЕСТИТЬ ВТТест"), runner=_passed_runner)
        self.assertEqual(adaptive_decision([rejected])["status"], "REQUEST_EXACTLY_TWO_TARGETED_VARIATIONS")
        second = evaluate_candidate(self._candidate("Процедура Тест()\nКонецПроцедуры"), runner=_passed_runner)
        third = evaluate_candidate(self._candidate("ПОМЕСТИТЬ ВТТест"), runner=_passed_runner)
        decision = adaptive_decision([rejected, second, third])
        self.assertEqual(decision["status"], "SELECTED_FALLBACK")
        self.assertEqual(decision["llm_calls"], 2)

    def test_unavailable_diagnostics_are_stop(self) -> None:
        def unavailable(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired("oscript", 30)

        result = evaluate_candidate(self._candidate("Процедура Тест()\nКонецПроцедуры"), runner=unavailable)
        self.assertEqual(result["status"], "STOP_DIAGNOSTICS_UNAVAILABLE")
        self.assertEqual(adaptive_decision([result])["llm_calls"], 0)


if __name__ == "__main__":
    unittest.main()
