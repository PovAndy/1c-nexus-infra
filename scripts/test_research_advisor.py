#!/usr/bin/env python3
"""Офлайн-проверки изолированного Research Advisor."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from research_advisor import (
    ResearchBrief,
    SourceCard,
    build_role_messages,
    evaluate_with_roles,
    load_policy,
    research_httpx_client_kwargs,
    sanitize_brief,
    validate_model_assessment,
    validate_public_url,
)


class ResearchAdvisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy()

    def test_brief_rejects_private_context(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_brief({"question": "Проверь /private/path", "scope": "Публичная практика", "acceptance": ["Только T1"]}, self.policy)

    def test_public_url_rejects_private_and_unapproved_routes(self) -> None:
        for url in ("http://developers.openai.com/x", "https://localhost/x", "https://example.org/x", "https://developers.openai.com/x?a=b"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_public_url(url, self.policy)

    def test_e2_needs_t1_and_independent_publishers(self) -> None:
        cards = [
            SourceCard("src-a", "https://developers.openai.com/a", "developers.openai.com", "T1", "A", "Текст", "a"),
            SourceCard("src-b", "https://github.com/a", "github.com", "T2", "B", "Текст", "b"),
        ]
        raw = {"status": "PASS", "claims": [{"claim_id": "c1", "claim": "Публичная практика", "source_ids": ["src-a", "src-b"], "conditions": "Версия указана", "limitations": "Нужна локальная проверка", "proposed_level": "E2"}], "issues": [], "stop_reasons": []}
        result = validate_model_assessment(raw, cards, self.policy)
        self.assertEqual(result["claims"][0]["evidence_level"], "E2")

    def test_single_forum_cannot_be_e2(self) -> None:
        cards = [SourceCard("src-a", "https://habr.com/a", "habr.com", "T3", "A", "Текст", "a")]
        raw = {"status": "PASS", "claims": [{"claim_id": "c1", "claim": "Идея", "source_ids": ["src-a"], "conditions": "Неизвестны", "limitations": "Требуется первичный источник", "proposed_level": "E2"}], "issues": [], "stop_reasons": []}
        result = validate_model_assessment(raw, cards, self.policy)
        self.assertEqual(result["claims"][0]["evidence_level"], "E1")

    def test_role_prompt_excludes_private_capabilities(self) -> None:
        brief = ResearchBrief("Сравнить публичные рекомендации", "Только общедоступные версии", ("Указать ограничения",))
        cards = [SourceCard("src-a", "https://owasp.org/a", "owasp.org", "T1", "A", "Текст", "a")]
        messages = build_role_messages("critic", brief, cards)
        self.assertIn("нет доступа к Web, MCP, файлам, Graph, RAG, базам", messages[0]["content"])
        self.assertIn("Недоверенный фрагмент", messages[1]["content"])

    def test_public_web_requires_explicit_proxy(self) -> None:
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy.example:8080"}, clear=True):
            self.assertEqual(research_httpx_client_kwargs()["proxy"], "http://proxy.example:8080")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                research_httpx_client_kwargs()

    def test_evidence_chain_uses_critic_sol_then_scribe(self) -> None:
        brief = ResearchBrief("Сравнить публичные рекомендации", "Только общедоступные версии", ("Указать ограничения",))
        cards = [
            SourceCard("src-a", "https://developers.openai.com/a", "developers.openai.com", "T1", "A", "Текст", "a"),
            SourceCard("src-b", "https://github.com/a", "github.com", "T2", "B", "Текст", "b"),
        ]
        candidate = {"status": "PASS", "claims": [{"claim_id": "c1", "claim": "Публичная практика", "source_ids": ["src-a", "src-b"], "conditions": "Версия указана", "limitations": "Нужна локальная проверка", "proposed_level": "E2"}], "issues": [], "stop_reasons": []}
        calls: list[str] = []

        async def fake_role(role, messages, **kwargs):
            calls.append(role)
            if role == "scribe":
                self.assertIn("Markdown", messages[-1]["content"])
                return {"choices": [{"message": {"content": "# Отчёт\n- E2: локальная проверка требуется."}}]}, role
            self.assertIn("JSON", messages[-1]["content"])
            return {"choices": [{"message": {"content": json.dumps(candidate, ensure_ascii=False)}}]}, role

        with patch("research_advisor.request_omvl5_role_completion", new=fake_role):
            result = asyncio.run(evaluate_with_roles(brief, cards, self.policy))
        self.assertEqual(calls, ["critic", "sol_inspector", "scribe"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["claims"][0]["evidence_level"], "E2")
        self.assertEqual(result["report"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
