#!/usr/bin/env python3
"""Офлайн-проверки Circuit Breaker, checkpoint и нативного work order."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx

from omvl_llm_runtime import CodexFallbackRequired, request_omvl5_role_completion
from omvl_resilience import CircuitOpen, ResilienceStore, classify_failure


TEST_ENV = {
    "CODER_API_BASE_URL": "https://roles.invalid/v1",
    "CODER_LUNA_MODEL": "claude-sonnet-5",
    "CODER_LUNA_API_KEY": "test-luna-key",
    "INSPECTOR_SOL_MODEL": "gpt-5.6-sol",
    "INSPECTOR_SOL_API_KEY": "test-sol-key",
    "CRITIC_MODEL": "deepseek-v4-flash",
    "CRITIC_API_KEY": "test-critic-key",
    "SCRIBE_MODEL": "gemini-3-flash",
    "SCRIBE_API_KEY": "test-scribe-key",
    "OMVL_CODER_CONNECT_TIMEOUT_SECONDS": "3",
    "CODE_INDEX_PRODUCTION_TIMEOUT": "30",
}


class MutableClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class ResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clock = MutableClock()
        self.store = ResilienceStore(self.root, clock=self.clock, cooldown_seconds=90, provider_window_seconds=60)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_failure_classification(self) -> None:
        self.assertEqual(classify_failure(status_code=401), "configuration")
        self.assertEqual(classify_failure(status_code=429), "rate_limit")
        self.assertEqual(classify_failure(status_code=503), "transient_http")
        self.assertEqual(classify_failure(exc=httpx.ConnectError("dns")), "network")
        self.assertEqual(classify_failure(exc=httpx.ReadTimeout("slow")), "timeout")

    def test_provider_opens_only_after_confirmed_scope(self) -> None:
        self.store.record_failure("critic", "transient_http")
        self.store.authorize("scribe")
        self.store.record_failure("scribe", "transient_http")
        with self.assertRaises(CircuitOpen) as raised:
            self.store.authorize("luna_implementer")
        self.assertEqual(raised.exception.scope, "provider")

    def test_network_failure_opens_provider_immediately(self) -> None:
        self.store.record_failure("critic", "network")
        with self.assertRaises(CircuitOpen) as raised:
            self.store.authorize("scribe")
        self.assertEqual(raised.exception.scope, "provider")

    def test_half_open_allows_exactly_one_probe(self) -> None:
        self.store.record_failure("critic", "network")
        self.clock.value += 91
        self.store.authorize("critic")
        with self.assertRaises(CircuitOpen):
            self.store.authorize("scribe")
        self.store.record_success("critic")
        self.store.authorize("scribe")

    def test_cancelled_async_lock_wait_does_not_leak_flock(self) -> None:
        blocker = self.store.provider_request_lock.open("a+", encoding="utf-8")
        fcntl.flock(blocker.fileno(), fcntl.LOCK_EX)

        async def scenario() -> None:
            async def waiter() -> None:
                async with self.store.async_provider_guard():
                    raise AssertionError("Заблокированный guard не должен быть получен")

            task = asyncio.create_task(waiter())
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            fcntl.flock(blocker.fileno(), fcntl.LOCK_UN)
            async with asyncio.timeout(1):
                async with self.store.async_provider_guard():
                    pass

        try:
            asyncio.run(scenario())
        finally:
            blocker.close()

    def test_single_external_reservation_for_concurrent_callers(self) -> None:
        def reserve(_: int) -> str:
            with self.store.task_guard("same-task"):
                return self.store.reserve_attempt(
                    task_id="same-task",
                    role="critic",
                    request_digest="digest",
                    route="critic",
                ).action

        with ThreadPoolExecutor(max_workers=20) as pool:
            actions = list(pool.map(reserve, range(20)))
        self.assertEqual(actions.count("external"), 1)
        self.assertEqual(actions.count("native_required"), 19)

    def test_complete_checkpoint_is_cached(self) -> None:
        self.store.reserve_attempt(task_id="done", role="scribe", request_digest="d", route="scribe")
        self.store.mark_complete("done", {"choices": [{"message": {"content": "ok"}}]}, "scribe")
        decision = self.store.reserve_attempt(task_id="done", role="scribe", request_digest="d", route="scribe")
        self.assertEqual(decision.action, "cached")
        self.store.record_failure("critic", "network")
        cached = self.store.existing_attempt(task_id="done", role="scribe", request_digest="d")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.action, "cached")

    def test_work_order_is_redacted_and_deterministic(self) -> None:
        path = self.store.require_native(
            task_id="redacted",
            role="critic",
            request_digest="d",
            failure_class="timeout",
            reason="Bearer secret-token-value",
            task_brief="Проверь /home/user и x17, api_key=secret-value",
            context_refs=("Graph:module",),
        )
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("secret-token-value", raw)
        self.assertNotIn("/home/user", raw)
        self.assertNotIn("api_key=secret-value", raw)
        self.assertEqual(json.loads(raw)["recommended_agent"], "codex_terra_fallback")

    def test_native_claim_and_finish_fsm(self) -> None:
        self.store.require_native(
            task_id="native-flow",
            role="sol_inspector",
            request_digest="d",
            failure_class="timeout",
            reason="ReadTimeout",
        )
        claimed = self.store.claim_native("native-flow", "codex_sol_fallback")
        self.assertEqual(claimed["status"], "claimed")
        self.store.finish_native("native-flow", "complete", "temp/native-result.md")
        checkpoint = json.loads(self.store.checkpoint_path("native-flow").read_text(encoding="utf-8"))
        self.assertEqual(checkpoint["state"], "complete")
        self.assertFalse(self.store.work_order_path("native-flow").exists())

    def test_task_id_collision_does_not_overwrite_work_order(self) -> None:
        path = self.store.require_native(
            task_id="collision",
            role="critic",
            request_digest="first",
            failure_class="timeout",
            reason="ReadTimeout",
        )
        before = path.read_bytes()
        with self.assertRaises(RuntimeError):
            self.store.require_native(
                task_id="collision",
                role="scribe",
                request_digest="second",
                failure_class="timeout",
                reason="ReadTimeout",
            )
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_checkpoint_is_quarantined(self) -> None:
        path = self.store.checkpoint_path("broken")
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.store.reserve_attempt(task_id="broken", role="critic", request_digest="d", route="critic")
        self.assertTrue(any(self.store.checkpoints.glob("broken.json.corrupt-*")))


class RuntimeIntegrationTests(unittest.TestCase):
    def test_concurrent_tasks_are_serialized_before_external_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls = 0

            async def handler(request: httpx.Request) -> httpx.Response:
                nonlocal calls
                calls += 1
                await asyncio.sleep(0.03)
                raise httpx.ReadTimeout("slow", request=request)

            store = ResilienceStore(Path(tmp))

            async def one(task_id: str) -> str:
                try:
                    await request_omvl5_role_completion(
                        "critic",
                        [{"role": "user", "content": "Проверка"}],
                        transport=httpx.MockTransport(handler),
                        task_id=task_id,
                        resilience_store=store,
                        response_timeout=15,
                    )
                except CodexFallbackRequired as exc:
                    return exc.failure_class
                raise AssertionError("Ожидался нативный fallback")

            async def scenario() -> list[str]:
                return await asyncio.wait_for(asyncio.gather(one("parallel-a"), one("parallel-b")), timeout=2)

            with patch.dict(os.environ, TEST_ENV, clear=False):
                failures = asyncio.run(scenario())
            self.assertEqual(calls, 1)
            self.assertEqual(failures, ["timeout", "circuit_open"])

    def test_503_creates_work_order_and_repeat_skips_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls = 0

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal calls
                calls += 1
                return httpx.Response(503, json={"error": "temporary"}, request=request)

            store = ResilienceStore(Path(tmp))
            kwargs = dict(
                role="critic",
                messages=[{"role": "user", "content": "Проверка"}],
                transport=httpx.MockTransport(handler),
                task_id="runtime-503",
                task_brief="Проверить архитектуру",
                resilience_store=store,
            )
            with patch.dict(os.environ, TEST_ENV, clear=False):
                with self.assertRaises(CodexFallbackRequired) as first:
                    asyncio.run(request_omvl5_role_completion(**kwargs))
                with self.assertRaises(CodexFallbackRequired) as second:
                    asyncio.run(request_omvl5_role_completion(**kwargs))
            self.assertEqual(calls, 1)
            self.assertEqual(first.exception.task_id, second.exception.task_id)
            self.assertTrue(Path(first.exception.work_order).is_file())

    def test_timeout_has_unknown_outcome_and_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls = 0

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal calls
                calls += 1
                raise httpx.ReadTimeout("slow", request=request)

            store = ResilienceStore(Path(tmp))
            kwargs = dict(
                role="sol_inspector",
                messages=[{"role": "user", "content": "Проверка"}],
                transport=httpx.MockTransport(handler),
                task_id="runtime-timeout",
                resilience_store=store,
                response_timeout=15,
            )
            with patch.dict(os.environ, TEST_ENV, clear=False):
                for _ in range(2):
                    with self.assertRaises(CodexFallbackRequired):
                        asyncio.run(request_omvl5_role_completion(**kwargs))
            self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
