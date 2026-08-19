#!/usr/bin/env python3
"""Общие runtime-хелперы OMVL для LLM-прокси."""

from __future__ import annotations

import inspect
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

import httpx
from dotenv import load_dotenv

from omvl_resilience import (
    CircuitOpen,
    ResilienceStore,
    canonical_digest,
    classify_failure,
    safe_task_id,
)


PRIMARY_CODER_BASE_URL_ENV = "CODE_INDEX_PRODUCTION_API_BASE_URL"
PRIMARY_CODER_MODEL_ENV = "CODE_INDEX_PRODUCTION_MODEL_ID"
PRIMARY_CODER_KEY_ENV = "CODE_INDEX_PRODUCTION_API_KEY"
PAID_CHEAP_KEY_ENV = "OR_KEY_PAID_CHEAP"
PAID_CHEAP_MODEL_ENV = "PAID_CRITIC_MODEL"
OMVL5_COMMON_BASE_URL_ENV = "CODER_API_BASE_URL"
OMVL5_ROLE_SPECS: dict[str, dict[str, str]] = {
    "luna_implementer": {
        "model_env": "CODER_LUNA_MODEL",
        "key_env": "CODER_LUNA_API_KEY",
        "fallback_model_env": "CODER_LUNA_FALLBACK_MODEL",
        "fallback_key_env": "CODER_LUNA_FALLBACK_API_KEY",
    },
    "sol_inspector": {
        "model_env": "INSPECTOR_SOL_MODEL",
        "key_env": "INSPECTOR_SOL_API_KEY",
        "fallback_model_env": "INSPECTOR_SOL_FALLBACK_MODEL",
        "fallback_key_env": "INSPECTOR_SOL_FALLBACK_API_KEY",
    },
    "critic": {
        "model_env": "CRITIC_MODEL",
        "key_env": "CRITIC_API_KEY",
        "fallback_model_env": "CRITIC_FALLBACK_MODEL",
        "fallback_key_env": "CRITIC_FALLBACK_API_KEY",
    },
    "scribe": {
        "model_env": "SCRIBE_MODEL",
        "key_env": "SCRIBE_API_KEY",
        "fallback_model_env": "SCRIBE_FALLBACK_MODEL",
        "fallback_key_env": "SCRIBE_FALLBACK_API_KEY",
    },
}
CODER_CONNECT_TIMEOUT_ENV = "OMVL_CODER_CONNECT_TIMEOUT_SECONDS"
CODER_RESPONSE_TIMEOUT_ENV = "CODE_INDEX_PRODUCTION_TIMEOUT"
FALLBACK_CODER_CONNECT_TIMEOUT_ENV = "OMVL_CODER_FALLBACK_CONNECT_TIMEOUT_SECONDS"
FALLBACK_CODER_RESPONSE_TIMEOUT_ENV = "OMVL_CODER_FALLBACK_TIMEOUT_SECONDS"
FAST_STREAM_RESPONSE_TIMEOUT_SECONDS = 300.0
FAST_STREAM_PROTOCOL_ENV = "CODE_INDEX_PRODUCTION_STREAM_PROTOCOL"
CODER_PRIMARY_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 521, 522, 523, 524})
BSL_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\.Ref\b", "Недопустимое свойство .Ref: используйте .Ссылка"),
    (r"\bAS\b", "Недопустимый SQL-алиас AS: используйте КАК"),
    (r"Запрос\.Выполнить\s*\(", "Запрос.Выполнить() с inline-параметрами запрещён"),
    (r"Новый\s+Массив\s*\([^)]+\)", "Конструктор Новый Массив с аргументами запрещён"),
    (r"\[VERIFIED\]", "Самоприсвоение статуса [VERIFIED] запрещено"),
    (r"(?<!Запрос\.)\bВыполнить\s*\(", "Опасный вызов Выполнить() запрещён"),
)
BSL_CODER_SYSTEM_PROMPT = """You are a Strict 1C:Enterprise 8.3 BSL Code Executor and Technical Reviewer.
Your sole responsibility is to write and review BSL code based EXCLUSIVELY on provided evidence.

EPISTEMIC POLICY (CRITICAL):
1. NEVER output '[VERIFIED]'. You DO NOT have execution authority to verify code.
2. ALWAYS use '[REVIEW_DRAFT]' for review decisions or '[UNVERIFIED_DRAFT]' for code patches.

STRICT EXECUTION RULES:
1. ZERO-HALLUCINATION RULE: Never invent 1C metadata objects or BSL methods not in the input prompt. If missing -> output [UNKNOWN/STOP].
2. NO BUSINESS GUESSING: Never auto-assign organ prefixes or district IDs. Output 'STOP/REVIEW' for ambiguities.
3. BSL SAFEGUARDS: Always enforce 'ORDER BY' on queries and explicit transactions on bulk writes.
4. FORBIDDEN BSL SYNTAX: Never use '.Ref' (use '.Ссылка'), never use 'AS' in queries (use 'КАК'), never use 'Запрос.Выполнить(Параметры)' (use 'Запрос.УстановитьПараметр()').
5. OUTPUT FORMAT: Output ONLY clean BSL diffs or evidence status [REVIEW_DRAFT / UNVERIFIED_DRAFT / UNKNOWN / STOP]."""


class CodexFallbackRequired(RuntimeError):
    """Сигнализирует оркестратору о переходе на нативный fallback Codex."""

    def __init__(
        self,
        role: str,
        reason: str,
        *,
        failure_class: str = "unknown",
        task_id: str = "",
        work_order: str = "",
    ) -> None:
        super().__init__(f"Для роли {role} требуется нативный fallback Codex: {reason}")
        self.role = role
        self.reason = reason
        self.failure_class = failure_class
        self.task_id = task_id
        self.work_order = work_order


def coder_failover_routes() -> tuple[dict[str, str], dict[str, str]]:
    """Возвращает primary и Paid Cheap маршруты кодера без раскрытия секретов."""
    load_omvl_env()
    primary = {
        "name": "primary",
        "base_url": _env_or_file(PRIMARY_CODER_BASE_URL_ENV, "").rstrip("/"),
        "model": _env_or_file(PRIMARY_CODER_MODEL_ENV, ""),
        "api_key": _env_or_file(PRIMARY_CODER_KEY_ENV, ""),
    }
    fallback = {
        "name": "fallback_paid_cheap",
        "base_url": "https://openrouter.ai/api/v1",
        "model": _env_or_file(PAID_CHEAP_MODEL_ENV, "deepseek/deepseek-chat"),
        "api_key": _env_or_file(PAID_CHEAP_KEY_ENV, ""),
    }
    missing = [
        route["name"]
        for route in (primary, fallback)
        if not all(route[key] for key in ("base_url", "model", "api_key"))
    ]
    if missing:
        raise RuntimeError(f"Не настроены маршруты кодера: {', '.join(missing)}")
    return primary, fallback


def _is_placeholder_secret(value: str) -> bool:
    """Отличает маркер незаполненного секрета от рабочего значения."""
    normalized = value.strip().lower()
    return not normalized or any(marker in normalized for marker in ("placeholder", "required_unique", "insert_", "changeme"))


def _omvl5_base_url() -> str:
    """Проверяет единый публичный HTTPS-маршрут облачных ролей OMVL 5.0."""
    base_url = _env_or_file(OMVL5_COMMON_BASE_URL_ENV, "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise RuntimeError(f"{OMVL5_COMMON_BASE_URL_ENV} должен быть публичным HTTPS URL без query/fragment")
    return base_url


def omvl5_role_routes() -> dict[str, dict[str, dict[str, str]]]:
    """Возвращает primary и необязательные внешние fallback-маршруты ролей."""
    load_omvl_env()
    base_url = _omvl5_base_url()
    routes: dict[str, dict[str, dict[str, str]]] = {}
    all_keys: list[str] = []
    for role, spec in OMVL5_ROLE_SPECS.items():
        model = _env_or_file(spec["model_env"], "").strip()
        api_key = _env_or_file(spec["key_env"], "").strip()
        fallback_model = _env_or_file(spec["fallback_model_env"], "").strip()
        fallback_key = _env_or_file(spec["fallback_key_env"], "").strip()
        if not model or _is_placeholder_secret(api_key):
            raise RuntimeError(f"OMVL 5.0 роль {role} не готова: требуется primary model/key")
        all_keys.append(api_key)
        role_routes: dict[str, dict[str, str]] = {
            "primary": {"name": role, "base_url": base_url, "model": model, "api_key": api_key}
        }
        if fallback_model and not _is_placeholder_secret(fallback_key):
            if api_key == fallback_key:
                raise RuntimeError(f"OMVL 5.0 роль {role} использует один ключ для primary и fallback")
            all_keys.append(fallback_key)
            role_routes["fallback"] = {
                "name": f"{role}_fallback",
                "base_url": base_url,
                "model": fallback_model,
                "api_key": fallback_key,
            }
        elif not _is_placeholder_secret(fallback_key):
            raise RuntimeError(f"OMVL 5.0 роль {role} имеет fallback key без fallback model")
        routes[role] = role_routes
    if len(all_keys) != len(set(all_keys)):
        raise RuntimeError("OMVL 5.0 нарушает изоляцию: API-ключ повторно назначен нескольким ролям")
    return routes


def _openai_chat_url(base_url: str) -> str:
    """Формирует OpenAI-совместимый endpoint без дублирования версии API."""
    normalized = base_url.rstrip("/")
    if normalized.endswith(("/api", "/v1")):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


async def request_omvl5_role_completion(
    role: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.0,
    transport: Any | None = None,
    task_id: str | None = None,
    task_brief: str = "",
    context_refs: tuple[str, ...] = (),
    acceptance_criteria: tuple[str, ...] = (),
    output_contract: str = "Краткий проверяемый результат на русском языке.",
    response_timeout: float | None = None,
    resilience_store: ResilienceStore | None = None,
    response_validator: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], str]:
    """Выполняет одну внешнюю попытку либо создаёт нативный work order Codex."""
    role_routes = omvl5_role_routes()
    if role not in role_routes:
        raise ValueError(f"Неизвестная роль OMVL 5.0: {role}")
    route = role_routes[role]["primary"]
    request_digest = canonical_digest(
        {
            "role": role,
            "model": route["model"],
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    )
    effective_task_id = safe_task_id(role, request_digest, task_id)
    store = resilience_store or ResilienceStore()

    def require_native(failure_class: str, reason: str) -> CodexFallbackRequired:
        path = store.require_native(
            task_id=effective_task_id,
            role=role,
            request_digest=request_digest,
            failure_class=failure_class,
            reason=reason,
            task_brief=task_brief,
            context_refs=context_refs,
            acceptance_criteria=acceptance_criteria,
            output_contract=output_contract,
        )
        return CodexFallbackRequired(
            role,
            reason,
            failure_class=failure_class,
            task_id=effective_task_id,
            work_order=str(path),
        )

    async with store.async_task_guard(effective_task_id):
        async with store.async_provider_guard():
            existing = store.existing_attempt(
                task_id=effective_task_id,
                role=role,
                request_digest=request_digest,
            )
            if existing is not None and existing.action == "cached":
                return existing.checkpoint["response"], str(existing.checkpoint.get("route", route["name"]))
            if existing is not None:
                failure_class = str(existing.checkpoint.get("failure_class", "unknown_outcome"))
                raise require_native(failure_class, "внешняя попытка уже выполнялась; повтор запрещён")
            try:
                store.authorize(role)
            except CircuitOpen as exc:
                raise require_native("circuit_open", f"{exc.scope}; повтор после {int(exc.retry_at)}") from exc

            decision = store.reserve_attempt(
                task_id=effective_task_id,
                role=role,
                request_digest=request_digest,
                route=route["name"],
            )
            if decision.action != "external":
                raise RuntimeError("Нарушен контракт резервирования внешней попытки")

            payload: dict[str, Any] = {
                "model": route["model"],
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }
            try:
                effective_timeout = min(coder_response_timeout(), response_timeout) if response_timeout else coder_response_timeout()
                async with httpx.AsyncClient(
                    **coder_httpx_client_kwargs(
                        transport=transport,
                        connect_timeout=coder_connect_timeout(),
                        response_timeout=effective_timeout,
                    )
                ) as client:
                    response = await client.post(
                        _openai_chat_url(route["base_url"]),
                        headers={"Authorization": f"Bearer {route['api_key']}"},
                        json=payload,
                    )
                if response.status_code >= 400:
                    failure_class = classify_failure(status_code=response.status_code)
                    retry_after = None
                    if response.status_code == 429:
                        try:
                            retry_after = float(response.headers.get("Retry-After", ""))
                        except ValueError:
                            retry_after = None
                    store.record_failure(role, failure_class, retry_after=retry_after)
                    raise require_native(failure_class, f"HTTP {response.status_code}")
                response.raise_for_status()
                try:
                    result = _ensure_usable_coder_result(response.json())
                    if response_validator is not None:
                        response_validator(result)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
                    store.record_failure(role, "contract")
                    raise require_native("contract", type(exc).__name__) from exc
                store.record_success(role)
                store.mark_complete(effective_task_id, result, route["name"])
                return result, route["name"]
            except CodexFallbackRequired:
                raise
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError, RuntimeError) as exc:
                failure_class = classify_failure(exc=exc)
                store.record_failure(role, failure_class)
                raise require_native(failure_class, type(exc).__name__) from exc


def coder_connect_timeout() -> float:
    """Читает контрактный connect timeout и не допускает небезопасных значений."""
    raw = _env_or_file(CODER_CONNECT_TIMEOUT_ENV, "3.0")
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Некорректный {CODER_CONNECT_TIMEOUT_ENV}") from exc
    if not 0 < timeout <= 10.0:
        raise RuntimeError(f"{CODER_CONNECT_TIMEOUT_ENV} должен быть в диапазоне (0; 10]")
    return timeout


def coder_response_timeout() -> float:
    """Читает общий лимит ответа production-кодера без смешивания с connect timeout."""
    raw = _env_or_file(CODER_RESPONSE_TIMEOUT_ENV, "120")
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Некорректный {CODER_RESPONSE_TIMEOUT_ENV}") from exc
    if not 15.0 <= timeout <= 300.0:
        raise RuntimeError(f"{CODER_RESPONSE_TIMEOUT_ENV} должен быть в диапазоне [15; 300]")
    return timeout


def coder_fallback_connect_timeout() -> float:
    """Читает короткий лимит подключения fallback-маршрута."""
    raw = _env_or_file(FALLBACK_CODER_CONNECT_TIMEOUT_ENV, "5.0")
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Некорректный {FALLBACK_CODER_CONNECT_TIMEOUT_ENV}") from exc
    if not 0 < timeout <= 10.0:
        raise RuntimeError(f"{FALLBACK_CODER_CONNECT_TIMEOUT_ENV} должен быть в диапазоне (0; 10]")
    return timeout


def coder_fallback_response_timeout() -> float:
    """Читает ограниченный лимит ответа fallback без изменения primary-профиля."""
    raw = _env_or_file(FALLBACK_CODER_RESPONSE_TIMEOUT_ENV, "60")
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Некорректный {FALLBACK_CODER_RESPONSE_TIMEOUT_ENV}") from exc
    if not 15.0 <= timeout <= 120.0:
        raise RuntimeError(f"{FALLBACK_CODER_RESPONSE_TIMEOUT_ENV} должен быть в диапазоне [15; 120]")
    return timeout


def coder_httpx_client_kwargs(
    *,
    transport: Any | None = None,
    connect_timeout: float | None = None,
    response_timeout: float | None = None,
) -> dict[str, Any]:
    """Формирует клиент с раздельными лимитами подключения и ответа кодера."""
    effective_response_timeout = response_timeout if response_timeout is not None else coder_response_timeout()
    effective_connect_timeout = connect_timeout if connect_timeout is not None else coder_connect_timeout()
    kwargs = httpx_client_kwargs(effective_response_timeout)
    kwargs["timeout"] = httpx.Timeout(effective_response_timeout, connect=effective_connect_timeout)
    if transport is not None:
        kwargs.pop("proxy", None)
        kwargs.pop("proxies", None)
        kwargs["transport"] = transport
    return kwargs


def _ensure_usable_coder_result(result: Any) -> dict[str, Any]:
    """Отвергает формально успешные, но пустые ответы кодера."""
    if not isinstance(result, dict):
        raise RuntimeError("Кодер вернул ответ в неподдерживаемом формате")
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Кодер вернул пустой список choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError("Кодер вернул некорректный элемент choices")
    message = first_choice.get("message")
    if not isinstance(message, dict) or not str(message.get("content") or "").strip():
        raise RuntimeError("Кодер вернул пустой ответ")
    return result


def sanitize_bsl_output(text: str) -> tuple[bool, list[str]]:
    """Проверяет сгенерированный BSL на запрещённые небезопасные конструкции."""
    if not isinstance(text, str):
        return False, ["Результат кодера не является строкой BSL"]
    errors = [message for pattern, message in BSL_FORBIDDEN_PATTERNS if re.search(pattern, text, re.IGNORECASE)]
    return not errors, errors


def _ollama_generate_url(base_url: str) -> str:
    """Формирует endpoint генерации через разрешённый глобальный маршрут."""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/api"):
        return f"{normalized}/generate"
    return f"{normalized}/api/generate"


def _openai_stream_url(base_url: str) -> str:
    """Формирует OpenAI-совместимый streaming endpoint глобального шлюза."""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/api"):
        return f"{normalized}/chat/completions"
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _fast_stream_protocol() -> str:
    """Читает протокол streaming API без привязки к приватному маршруту."""
    protocol = _env_or_file(FAST_STREAM_PROTOCOL_ENV, "openai").strip().lower()
    if protocol not in {"openai", "ollama"}:
        raise RuntimeError(f"{FAST_STREAM_PROTOCOL_ENV} должен быть openai или ollama")
    return protocol


def _stream_request_spec(primary: dict[str, str], prompt: str, mode: str) -> tuple[str, dict[str, Any], str]:
    """Возвращает endpoint, payload и формат потоковых событий выбранного API."""
    options = {
        "temperature": 0.0,
        "top_p": 0.10,
        "repeat_penalty": 1.08,
        "num_ctx": 32768,
        "num_predict": 250 if mode == "review" else 800,
    }
    protocol = _fast_stream_protocol()
    if protocol == "ollama":
        return (
            _ollama_generate_url(primary["base_url"]),
            {
                "model": primary["model"],
                "system": BSL_CODER_SYSTEM_PROMPT,
                "prompt": prompt,
                "stream": True,
                "options": options,
            },
            protocol,
        )
    return (
        _openai_stream_url(primary["base_url"]),
        {
            "model": primary["model"],
            "messages": [
                {"role": "system", "content": BSL_CODER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
            "temperature": options["temperature"],
            "top_p": options["top_p"],
            "max_tokens": options["num_predict"],
        },
        protocol,
    )


def _stream_fragment(line: str, protocol: str) -> tuple[str, str, bool]:
    """Извлекает итоговый текст, reasoning и признак завершения потока."""
    payload = line.strip()
    if protocol == "openai":
        if not payload.startswith("data:"):
            return "", "", False
        payload = payload[5:].strip()
        if payload == "[DONE]":
            return "", "", True
    event = json.loads(payload)
    if not isinstance(event, dict):
        return "", "", False
    if protocol == "ollama":
        fragment = event.get("response")
        if fragment is None and isinstance(event.get("message"), dict):
            fragment = event["message"].get("content")
        return str(fragment or ""), "", event.get("done") is True
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "", "", False
    delta = choices[0].get("delta")
    fragment = delta.get("content") if isinstance(delta, dict) else ""
    reasoning = delta.get("reasoning_content") if isinstance(delta, dict) else ""
    return str(fragment or ""), str(reasoning or ""), bool(choices[0].get("finish_reason"))


def query_gpt2_coder_fast(prompt: str, *, mode: str = "code") -> dict[str, Any]:
    """Запрашивает GPT2 потоково, измеряет TTFT и фильтрует BSL-черновик."""
    if mode not in {"code", "review"}:
        raise ValueError("mode должен быть 'code' или 'review'")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt должен быть непустой строкой")

    primary, _ = coder_failover_routes()
    prepared_prompt = prompt.strip()
    if mode == "review":
        prepared_prompt += "\n\nВАЖНО: НЕ ГЕНЕРИРУЙ BSL-КОД. Выдай только решение и список контрольных ворот."
    endpoint, payload, protocol = _stream_request_spec(primary, prepared_prompt, mode)
    started = time.monotonic()
    first_token_at: float | None = None
    chunks: list[str] = []
    reasoning_chunks: list[str] = []
    headers = {"Accept": "application/x-ndjson"}
    if primary["api_key"]:
        headers["Authorization"] = f"Bearer {primary['api_key']}"
    try:
        client_kwargs = coder_httpx_client_kwargs(
            connect_timeout=coder_connect_timeout(),
            response_timeout=FAST_STREAM_RESPONSE_TIMEOUT_SECONDS,
        )
        with httpx.Client(**client_kwargs) as client:
            with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    fragment, reasoning_fragment, done = _stream_fragment(line, protocol)
                    if fragment or reasoning_fragment:
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                    if fragment:
                        chunks.append(fragment)
                    if reasoning_fragment:
                        reasoning_chunks.append(reasoning_fragment)
                    if done:
                        break
        total_seconds = time.monotonic() - started
        text = "".join(chunks).strip()
        if not text and mode == "review":
            text = "".join(reasoning_chunks).strip()
        if not text:
            raise RuntimeError("Потоковый кодер завершился без содержательного ответа")
        if mode == "code":
            is_valid, syntax_errors = sanitize_bsl_output(text)
        else:
            is_valid, syntax_errors = sanitize_bsl_output(text)
            syntax_errors = [error for error in syntax_errors if "[VERIFIED]" in error]
            is_valid = not syntax_errors
        return {
            "status": "PASS" if is_valid else "SYNTAX_REJECT",
            "ttft_seconds": round((first_token_at or time.monotonic()) - started, 3),
            "total_seconds": round(total_seconds, 3),
            "text": text,
            "syntax_errors": syntax_errors,
            "evidence_status": "[UNVERIFIED_DRAFT]" if mode == "code" else "[REVIEW_DRAFT]",
        }
    except (httpx.HTTPError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        total_seconds = time.monotonic() - started
        return {
            "status": "FAIL",
            "ttft_seconds": None,
            "total_seconds": round(total_seconds, 3),
            "text": "",
            "syntax_errors": [f"{type(exc).__name__}: {exc}"],
            "evidence_status": "[UNVERIFIED_DRAFT]" if mode == "code" else "[REVIEW_DRAFT]",
        }


async def request_coder_completion(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.0,
    transport: Any | None = None,
) -> tuple[dict[str, Any], str]:
    """Запрашивает кодер и бесшумно переводит primary на Paid Cheap при отказе."""
    primary, fallback = coder_failover_routes()
    last_error: Exception | None = None
    for route in (primary, fallback):
        if route["name"] == "primary":
            connect_timeout = coder_connect_timeout()
            response_timeout = coder_response_timeout()
        else:
            connect_timeout = coder_fallback_connect_timeout()
            response_timeout = coder_fallback_response_timeout()
        try:
            async with httpx.AsyncClient(
                **coder_httpx_client_kwargs(
                    transport=transport,
                    connect_timeout=connect_timeout,
                    response_timeout=response_timeout,
                )
            ) as client:
                response = await client.post(
                    f"{route['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {route['api_key']}"},
                    json={
                        "model": route["model"],
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "stream": False,
                    },
                )
            if route["name"] == "primary" and response.status_code in CODER_PRIMARY_RETRYABLE_STATUSES:
                last_error = httpx.HTTPStatusError(
                    "Primary coder is temporarily unavailable", request=response.request, response=response
                )
                continue
            response.raise_for_status()
            return _ensure_usable_coder_result(response.json()), route["name"]
        except (httpx.TimeoutException, httpx.RequestError, json.JSONDecodeError, RuntimeError) as exc:
            if route["name"] == "primary":
                last_error = exc
                continue
            raise
    raise RuntimeError("Не удалось получить ответ ни от primary, ни от Paid Cheap кодера") from last_error


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.getenv("OPENROUTER_ENV_FILE", BASE_DIR / ".env.openrouter.local"))
RUNTIME_DIR = BASE_DIR / "runtime"
GEMINI_CLI_HOME = RUNTIME_DIR / "gemini-cli-home"
MODELS_CACHE = RUNTIME_DIR / "openrouter-models-cache.json"
MODELS_API_URL = "https://openrouter.ai/api/v1/models"
MODEL_CACHE_TTL_SECONDS = 3600


def load_omvl_env() -> None:
    load_dotenv(ENV_FILE)


def resolve_env_alias(alias_var: str, fallback_vars: tuple[str, ...] = (), default: str = "") -> str:
    alias = os.getenv(alias_var)
    if alias:
        value = os.getenv(alias)
        if value:
            return value
    for name in fallback_vars:
        value = os.getenv(name)
        if value:
            return value
    return default


def _tcp_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wsl_default_gateway() -> str:
    try:
        completed = subprocess.run(
            ["ip", "route"],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in completed.stdout.splitlines():
        parts = line.split()
        if parts[:1] == ["default"] and "via" in parts:
            return parts[parts.index("via") + 1]
    return ""


def _with_host(raw_url: str, host: str) -> str:
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return raw_url
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunparse(parsed._replace(netloc=f"{userinfo}{host}{port}"))


def proxy_url() -> str:
    return os.getenv("LDS_NETWORK_PROXY", "").strip()


def proxy_url_ip() -> str:
    return os.getenv("LDS_NETWORK_PROXY_IP", "").strip()


def effective_proxy_url() -> str:
    raw_proxy = proxy_url()
    if not raw_proxy:
        return proxy_url_ip()
    parsed = urlparse(raw_proxy)
    if not parsed.hostname or not parsed.port:
        return raw_proxy
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return raw_proxy
    if _tcp_open(parsed.hostname, parsed.port):
        return raw_proxy
    explicit_ip_proxy = proxy_url_ip()
    if explicit_ip_proxy:
        explicit = urlparse(explicit_ip_proxy)
        if explicit.hostname and explicit.port and _tcp_open(explicit.hostname, explicit.port):
            return explicit_ip_proxy
    gateway = _wsl_default_gateway()
    if gateway and _tcp_open(gateway, parsed.port):
        return _with_host(raw_proxy, gateway)
    return raw_proxy


def httpx_client_kwargs(timeout: int | float = 120) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": timeout, "trust_env": False}
    proxy = effective_proxy_url()
    if proxy:
        signature = inspect.signature(httpx.AsyncClient)
        if "proxy" in signature.parameters:
            kwargs["proxy"] = proxy
        else:
            kwargs["proxies"] = proxy
    return kwargs


def proxy_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    proxy = effective_proxy_url()
    if proxy:
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


def _preferred_node_bin() -> str:
    for candidate in (
        Path.home() / ".nvm" / "versions" / "node" / "v22.22.0" / "bin",
        Path.home() / ".nvm" / "versions" / "node" / "v22.19.0" / "bin",
    ):
        node = candidate / "node"
        if node.exists() and os.access(node, os.X_OK):
            return str(candidate)
    return ""


def _env_or_file(name: str, default: str = "") -> str:
    env_values = _read_env_values()
    return os.getenv(name) or env_values.get(name, default)


def _read_env_values(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    pattern = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        key, value = match.groups()
        values[key] = value.strip().strip('"').strip("'")
    return values


def google_ai_studio_key() -> str:
    env_values = _read_env_values()
    candidates = (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_AI_STUDIO_API_KEY",
        "AI_STUDIO_API_KEY",
        "LDS_GEMINI_API_KEY",
        "LDS_GOOGLE_API_KEY",
        "OMVL_GEMINI_API_KEY",
    )
    for name in candidates:
        value = os.getenv(name) or env_values.get(name)
        if value:
            return value
    alias = os.getenv("OMVL_GEMINI_API_KEY_ALIAS") or env_values.get("OMVL_GEMINI_API_KEY_ALIAS")
    if alias:
        return os.getenv(alias) or env_values.get(alias, "")
    return ""


def _ensure_gemini_api_key_home() -> None:
    settings_dir = GEMINI_CLI_HOME / ".gemini"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"
    data: dict[str, Any] = {}
    if settings_file.exists():
        try:
            loaded = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    security = data.setdefault("security", {})
    if not isinstance(security, dict):
        security = {}
        data["security"] = security
    auth = security.setdefault("auth", {})
    if not isinstance(auth, dict):
        auth = {}
        security["auth"] = auth
    auth["selectedType"] = "gemini-api-key"
    settings_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def gemini_cli_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = proxy_env(base_env)
    node_bin = _preferred_node_bin()
    if node_bin:
        path_items = [item for item in env.get("PATH", "").split(os.pathsep) if item]
        env["PATH"] = os.pathsep.join([node_bin, *[item for item in path_items if item != node_bin]])
    api_key = google_ai_studio_key()
    auth_mode = _env_or_file("OMVL_GEMINI_AUTH_MODE", "oauth").strip().lower()
    if auth_mode in {"api-key", "api_key", "apikey"}:
        auth_mode = "api_key"
    if auth_mode not in {"oauth", "api_key", "auto"}:
        auth_mode = "oauth"

    if auth_mode == "auto":
        auth_mode = "api_key" if api_key else "oauth"

    if auth_mode == "api_key" and api_key:
        _ensure_gemini_api_key_home()
        env["HOME"] = str(GEMINI_CLI_HOME)
        env["GEMINI_DEFAULT_AUTH_TYPE"] = "gemini-api-key"
        env["GEMINI_API_KEY"] = api_key
        env["GOOGLE_API_KEY"] = api_key
    else:
        env["HOME"] = _env_or_file("OMVL_GEMINI_HOME", str(Path.home()))
        env["GEMINI_DEFAULT_AUTH_TYPE"] = "oauth-personal"
        env.pop("GEMINI_API_KEY", None)
        env.pop("GOOGLE_API_KEY", None)
    return env


async def fetch_openrouter_models() -> list[str]:
    if os.getenv("OMVL_CASCADE_SELFTEST") == "1":
        return [
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
            "qwen/qwen3.6-flash",
            "qwen/qwen3.6-plus",
        ]

    now = time.time()
    if MODELS_CACHE.exists():
        try:
            cached = json.loads(MODELS_CACHE.read_text(encoding="utf-8"))
            if now - float(cached.get("fetched_at", 0)) < MODEL_CACHE_TTL_SECONDS:
                models = cached.get("models", [])
                if isinstance(models, list):
                    return [str(item) for item in models]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    async with httpx.AsyncClient(**httpx_client_kwargs(timeout=30)) as client:
        response = await client.get(MODELS_API_URL)
        response.raise_for_status()
        data = response.json()

    models = []
    for item in data.get("data", []):
        model_id = item.get("id")
        if model_id:
            models.append(str(model_id))

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_CACHE.write_text(
        json.dumps({"fetched_at": now, "models": models}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return models


def _model_needles(model: str) -> tuple[str, ...]:
    return ()


def _score_model(requested: str, candidate: str, needles: tuple[str, ...]) -> tuple[int, int, str]:
    candidate_l = candidate.lower()
    requested_l = requested.lower()
    score = 0
    if candidate_l == requested_l:
        score -= 100
    if candidate_l.endswith(":free"):
        score -= 20
    if "free" in candidate_l:
        score -= 5
    if "preview" in candidate_l or "beta" in candidate_l:
        score += 5
    if not all(needle in candidate_l for needle in needles):
        score += 1000
    return score, len(candidate), candidate


async def resolve_openrouter_model(model: str) -> str:
    needles = _model_needles(model)
    if not needles:
        return model
    try:
        models = await fetch_openrouter_models()
    except Exception:
        return model
    candidates = [item for item in models if all(needle in item.lower() for needle in needles) and item.lower().endswith(":free")]
    if not candidates:
        return model
    return sorted(candidates, key=lambda item: _score_model(model, item, needles))[0]
