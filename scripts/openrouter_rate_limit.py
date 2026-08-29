"""Атомарный leaky-bucket limiter для WAN25 и изолированных role gateway."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = BASE_DIR / "runtime"
STATE_FILE = RUNTIME_DIR / "wan25-rate-limit.json"
LOCK_FILE = RUNTIME_DIR / "wan25-rate-limit.lock"
WAN25_BASE_URL_ENV = "CODER_API_BASE_URL"
WAN25_ENABLED_ENV = "WAN25_GATEWAY_ENABLED"
WAN25_RPM_ENV = "WAN25_RPM_LIMIT"
WAN25_MIN_INTERVAL_ENV = "WAN25_MIN_INTERVAL_SECONDS"
WAN25_MAX_QUEUE_WAIT_ENV = "WAN25_MAX_QUEUE_WAIT_SECONDS"
DEFAULT_BASE_URL = "https://apiai.wan-2-5.pro/v1"
MINIMUM_INTERVAL_SECONDS = 6.0
DEFAULT_MAX_QUEUE_WAIT_SECONDS = 18.0


class Wan25QueueOverflow(RuntimeError):
    """Ожидание primary маршрута превышает длину допустимой очереди."""

    def __init__(self, wait_seconds: float, model: str) -> None:
        super().__init__(f"WAN25_QUEUE_OVERFLOW: model={model}; wait_seconds={wait_seconds:.3f}")
        self.wait_seconds = wait_seconds
        self.model = model


def wan25_gateway_enabled() -> bool:
    """Возвращает opt-in состояние единого WAN25 gateway."""
    return os.getenv(WAN25_ENABLED_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}


def wan25_base_url() -> str:
    """Возвращает нормализованный HTTPS URL общего gateway."""
    value = os.getenv(WAN25_BASE_URL_ENV, DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise RuntimeError(f"{WAN25_BASE_URL_ENV} должен быть HTTPS URL без query/fragment")
    return value


def _gateway_id(base_url: str) -> str:
    return hashlib.sha256(base_url.encode("utf-8")).hexdigest()[:16]


def _minimum_interval() -> float:
    raw_interval = os.getenv(WAN25_MIN_INTERVAL_ENV, "").strip()
    if raw_interval:
        try:
            requested = float(raw_interval)
        except ValueError as exc:
            raise RuntimeError(f"Некорректный {WAN25_MIN_INTERVAL_ENV}") from exc
    else:
        try:
            rpm = int(os.getenv(WAN25_RPM_ENV, "10"))
        except ValueError as exc:
            raise RuntimeError(f"Некорректный {WAN25_RPM_ENV}") from exc
        if not 1 <= rpm <= 10:
            raise RuntimeError(f"{WAN25_RPM_ENV} должен быть в диапазоне [1; 10]")
        requested = 60.0 / rpm
    if requested < MINIMUM_INTERVAL_SECONDS:
        raise RuntimeError(f"{WAN25_MIN_INTERVAL_ENV} не может быть меньше {MINIMUM_INTERVAL_SECONDS:.1f}")
    return requested


def _max_queue_wait() -> float:
    try:
        value = float(os.getenv(WAN25_MAX_QUEUE_WAIT_ENV, str(DEFAULT_MAX_QUEUE_WAIT_SECONDS)))
    except ValueError as exc:
        raise RuntimeError(f"Некорректный {WAN25_MAX_QUEUE_WAIT_ENV}") from exc
    if value < 0:
        raise RuntimeError(f"{WAN25_MAX_QUEUE_WAIT_ENV} не может быть отрицательным")
    return value


def _load_state() -> dict[str, dict[str, float | str]]:
    if not STATE_FILE.exists():
        return {}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(state: dict[str, dict[str, float | str]]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _acquire_slot_sync(base_url: str, model: str, max_queue_wait: float | None = None) -> None:
    """Атомарно резервирует следующий слот единого gateway."""
    effective_max_wait = _max_queue_wait() if max_queue_wait is None else max_queue_wait
    if effective_max_wait < 0:
        raise RuntimeError("max_queue_wait не может быть отрицательным")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    gateway_id = _gateway_id(base_url)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        while True:
            state = _load_state()
            bucket = state.setdefault(gateway_id, {})
            now = time.monotonic()
            wait_for = max(0.0, float(bucket.get("next_allowed_at", 0.0)) - now)
            if wait_for > effective_max_wait:
                raise Wan25QueueOverflow(wait_for, model)
            if wait_for:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                time.sleep(wait_for)
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                continue
            bucket["next_allowed_at"] = now + _minimum_interval()
            bucket["last_model"] = model
            _save_state(state)
            return


async def acquire_wan25_slot(
    api_key: str,
    model: str,
    *,
    base_url: str | None = None,
    max_queue_wait: float | None = None,
) -> None:
    """Ожидает слот общего WAN25 gateway; ключ не сохраняется в state."""
    del api_key
    await asyncio.to_thread(_acquire_slot_sync, base_url or wan25_base_url(), model, max_queue_wait)


def remember_retry_after(
    api_key: str,
    model: str,
    retry_after: str | None,
    *,
    base_url: str | None = None,
    minimum_delay: float = 7.0,
) -> None:
    """Продлевает cooldown gateway после 429, не записывая ключ."""
    del api_key
    try:
        provider_delay = float(retry_after) if retry_after else 0.0
    except ValueError:
        provider_delay = 0.0
    effective_url = base_url or wan25_base_url()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _load_state()
        bucket = state.setdefault(_gateway_id(effective_url), {})
        bucket["next_allowed_at"] = max(
            float(bucket.get("next_allowed_at", 0.0)),
            time.monotonic() + max(MINIMUM_INTERVAL_SECONDS, minimum_delay, provider_delay),
        )
        bucket["last_model"] = model
        _save_state(state)


async def acquire_openrouter_slot(api_key: str, model: str) -> None:
    """Compatibility API: лимитирует только при opt-in WAN25 gateway."""
    if wan25_gateway_enabled():
        await acquire_wan25_slot(api_key, model)


def fallback_model_for(model: str) -> str:
    """Возвращает явно заданный WAN25 fallback без обращения к каталогу провайдера."""
    normalized = model.strip().upper().replace("/", "_").replace(".", "_").replace("-", "_")
    return os.getenv(f"WAN25_FALLBACK_MODEL_{normalized}", "")
