#!/usr/bin/env python3
"""Локальная регрессия legacy- и OMVL 5.0 каскадов без сетевых вызовов."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path

import httpx


ROOT = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
RUNTIME_PATH = ROOT / "scripts" / "omvl_llm_runtime.py"
ENVIRONMENT = {
    "CODE_INDEX_PRODUCTION_API_BASE_URL": "https://primary.invalid/v1",
    "CODE_INDEX_PRODUCTION_MODEL_ID": "primary-coder",
    "CODE_INDEX_PRODUCTION_API_KEY": "test-primary-key",
    "OR_KEY_PAID_CHEAP": "test-fallback-key",
    "PAID_CRITIC_MODEL": "deepseek/deepseek-chat",
    "OMVL_CODER_CONNECT_TIMEOUT_SECONDS": "10.0",
    "CODE_INDEX_PRODUCTION_TIMEOUT": "120",
    "OMVL_CODER_FALLBACK_CONNECT_TIMEOUT_SECONDS": "5.0",
    "OMVL_CODER_FALLBACK_TIMEOUT_SECONDS": "60",
    "CODER_API_BASE_URL": "https://roles.invalid/v1",
    "CODER_LUNA_MODEL": "gpt-5.6-luna-max",
    "CODER_LUNA_API_KEY": "test-luna-primary-key",
    "CODER_LUNA_FALLBACK_MODEL": "gpt-5.6-sol",
    "CODER_LUNA_FALLBACK_API_KEY": "__REQUIRED_UNIQUE_LUNA_FALLBACK_API_KEY__",
    "INSPECTOR_SOL_MODEL": "gpt-5.6-sol",
    "INSPECTOR_SOL_API_KEY": "test-sol-primary-key",
    "INSPECTOR_SOL_FALLBACK_MODEL": "deepseek/deepseek-chat",
    "INSPECTOR_SOL_FALLBACK_API_KEY": "__REQUIRED_UNIQUE_SOL_FALLBACK_API_KEY__",
    "CRITIC_MODEL": "deepseek/deepseek-chat",
    "CRITIC_API_KEY": "test-critic-primary-key",
    "CRITIC_FALLBACK_MODEL": "gpt-5.6-sol",
    "CRITIC_FALLBACK_API_KEY": "__REQUIRED_UNIQUE_CRITIC_FALLBACK_API_KEY__",
    "SCRIBE_MODEL": "google/gemini-3.5-flash",
    "SCRIBE_API_KEY": "test-scribe-primary-key",
    "SCRIBE_FALLBACK_MODEL": "deepseek/deepseek-chat",
    "SCRIBE_FALLBACK_API_KEY": "__REQUIRED_UNIQUE_SCRIBE_FALLBACK_API_KEY__",
}


def _runtime_module():
    spec = importlib.util.spec_from_file_location("omvl_llm_runtime_failover_test", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить OMVL runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _with_test_environment():
    previous = {key: os.environ.get(key) for key in ENVIRONMENT}
    os.environ.update(ENVIRONMENT)
    return previous


def _restore_environment(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


async def _assert_primary_active(runtime) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    result, route = await runtime.request_coder_completion(
        [{"role": "user", "content": "test"}], transport=httpx.MockTransport(handler)
    )
    assert route == "primary"
    assert result["choices"]
    assert len(calls) == 1
    assert "primary.invalid" in calls[0]


async def _assert_fallback_active(runtime) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "primary.invalid" in url:
            return httpx.Response(503, json={"error": "temporary"}, request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=request)

    result, route = await runtime.request_coder_completion(
        [{"role": "user", "content": "test"}], transport=httpx.MockTransport(handler)
    )
    assert route == "fallback_paid_cheap"
    assert result["choices"]
    assert len(calls) == 2
    assert "primary.invalid" in calls[0]
    assert "openrouter.ai" in calls[1]


async def _assert_empty_primary_falls_back(runtime) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "primary.invalid" in url:
            return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}, request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=request)

    result, route = await runtime.request_coder_completion(
        [{"role": "user", "content": "test"}], transport=httpx.MockTransport(handler)
    )
    assert route == "fallback_paid_cheap"
    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 2


async def _assert_omvl5_primary_active(runtime) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=request)

    result, route = await runtime.request_omvl5_role_completion(
        "luna_implementer",
        [{"role": "user", "content": "test"}],
        transport=httpx.MockTransport(handler),
        task_id="test-omvl-primary-active",
    )
    assert route == "luna_implementer"
    assert result["choices"]
    assert len(calls) == 1
    assert all("roles.invalid/v1/chat/completions" in call for call in calls)


async def _assert_omvl5_requires_codex_fallback(runtime) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "temporary"}, request=request)

    try:
        await runtime.request_omvl5_role_completion(
            "luna_implementer",
            [{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(handler),
            task_id="test-omvl-requires-native",
        )
    except runtime.CodexFallbackRequired as exc:
        assert exc.role == "luna_implementer"
    else:
        raise AssertionError("При недоступном primary ожидался переход на Codex fallback")


def main() -> int:
    with tempfile.TemporaryDirectory() as state_dir:
        ENVIRONMENT["OMVL_RESILIENCE_DIR"] = state_dir
        previous = _with_test_environment()
        try:
            runtime = _runtime_module()
            kwargs = runtime.coder_httpx_client_kwargs(
                transport=httpx.MockTransport(lambda request: httpx.Response(200)),
                connect_timeout=runtime.coder_connect_timeout(),
                response_timeout=runtime.coder_response_timeout(),
            )
            assert kwargs["timeout"].connect == 10.0
            assert kwargs["timeout"].read == 120.0
            fallback_kwargs = runtime.coder_httpx_client_kwargs(
                transport=httpx.MockTransport(lambda request: httpx.Response(200)),
                connect_timeout=runtime.coder_fallback_connect_timeout(),
                response_timeout=runtime.coder_fallback_response_timeout(),
            )
            assert fallback_kwargs["timeout"].connect == 5.0
            assert fallback_kwargs["timeout"].read == 60.0
            role_routes = runtime.omvl5_role_routes()
            assert set(role_routes) == {"luna_implementer", "sol_inspector", "critic", "scribe"}
            role_keys = [route["api_key"] for routes in role_routes.values() for route in routes.values()]
            assert len(role_keys) == len(set(role_keys))
            assert all(set(routes) == {"primary"} for routes in role_routes.values())
            asyncio.run(_assert_primary_active(runtime))
            asyncio.run(_assert_fallback_active(runtime))
            asyncio.run(_assert_empty_primary_falls_back(runtime))
            asyncio.run(_assert_omvl5_primary_active(runtime))
            asyncio.run(_assert_omvl5_requires_codex_fallback(runtime))
        finally:
            _restore_environment(previous)
            ENVIRONMENT.pop("OMVL_RESILIENCE_DIR", None)
    print("PASS: Legacy Active; OMVL5 primary-only и переход на Codex fallback Active; primary=10/120s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
