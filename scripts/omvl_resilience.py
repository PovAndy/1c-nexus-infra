#!/usr/bin/env python3
"""Отказоустойчивость облачных ролей OMVL без повторной тарификации."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = ROOT / "runtime" / "omvl-resilience"
SCHEMA_VERSION = 1
TRANSIENT_CLASSES = frozenset({"network", "timeout", "rate_limit", "transient_http", "contract"})
PROVIDER_IMMEDIATE_CLASSES = frozenset({"network"})
ROLE_AGENTS = {
    "luna_implementer": "codex_luna_fallback",
    "scribe": "codex_luna_fallback",
    "critic": "codex_terra_fallback",
    "sol_inspector": "codex_sol_fallback",
}
SECRET_PATTERN = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+\S+|api[_-]?key\s*[=:]\s*\S+)")
PRIVATE_PATTERN = re.compile(r"(?i)(?:/home/|[A-Za-z]:\\|(?:postgres|sql|x17|x1_\d{2})\b)")


class CircuitOpen(RuntimeError):
    """Сигнализирует, что сетевой вызов запрещён открытым предохранителем."""

    def __init__(self, scope: str, retry_at: float) -> None:
        super().__init__(f"Предохранитель {scope} открыт")
        self.scope = scope
        self.retry_at = retry_at


@dataclass(frozen=True)
class AttemptDecision:
    """Результат резервирования единственной внешней попытки."""

    action: str
    checkpoint: dict[str, Any]


def canonical_digest(value: Any) -> str:
    """Возвращает стабильный SHA-256 для контракта запроса."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def safe_task_id(role: str, request_digest: str, explicit: str | None = None) -> str:
    """Формирует устойчивый идентификатор без включения текста задания."""
    seed = explicit.strip() if explicit else f"{role}:{request_digest}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def classify_failure(*, status_code: int | None = None, exc: BaseException | None = None) -> str:
    """Классифицирует отказ без смешивания конфигурации и временных ошибок."""
    if status_code is not None:
        if status_code in {400, 401, 403, 404, 405, 422}:
            return "configuration"
        if status_code == 429:
            return "rate_limit"
        if status_code in {408, 500, 502, 503, 504, 521, 522, 523, 524}:
            return "transient_http"
        return "http_error"
    if exc is None:
        return "unknown"
    name = type(exc).__name__.lower()
    if any(part in name for part in ("connect", "network", "proxy", "tls")):
        return "network"
    if "timeout" in name:
        return "timeout"
    if isinstance(exc, (json.JSONDecodeError, ValueError, KeyError, TypeError)):
        return "contract"
    return "unknown"


class ResilienceStore:
    """Хранит checkpoint, work order и состояния предохранителей атомарно."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
        cooldown_seconds: float = 90.0,
        provider_window_seconds: float = 60.0,
        half_open_lease_seconds: float = 30.0,
    ) -> None:
        self.root = Path(root or os.environ.get("OMVL_RESILIENCE_DIR", DEFAULT_STATE_DIR))
        self.clock = clock
        self.cooldown_seconds = cooldown_seconds
        self.provider_window_seconds = provider_window_seconds
        self.half_open_lease_seconds = half_open_lease_seconds
        self.checkpoints = self.root / "checkpoints"
        self.pending = self.root / "pending"
        self.locks = self.root / "locks"
        for path in (self.root, self.checkpoints, self.pending, self.locks):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)
        self.breakers_path = self.root / "breakers.json"
        self.breakers_lock = self.root / "breakers.lock"
        self.provider_request_lock = self.root / "provider-request.lock"

    @contextmanager
    def task_guard(self, task_id: str) -> Iterator[None]:
        """Сериализует один task ID на время внешнего вызова."""
        path = self.locks / f"{task_id}.lock"
        with path.open("a+", encoding="utf-8") as handle:
            os.chmod(path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @asynccontextmanager
    async def async_task_guard(self, task_id: str):
        """Асинхронно ожидает межпроцессную блокировку одной задачи."""
        path = self.locks / f"{task_id}.lock"
        async with self._async_file_guard(path):
            yield

    @contextmanager
    def provider_guard(self) -> Iterator[None]:
        """Не допускает конкурентные платные запросы к общему шлюзу."""
        with self.provider_request_lock.open("a+", encoding="utf-8") as handle:
            os.chmod(self.provider_request_lock, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @asynccontextmanager
    async def async_provider_guard(self):
        """Асинхронно сериализует обращения к общему внешнему шлюзу."""
        async with self._async_file_guard(self.provider_request_lock):
            yield

    @asynccontextmanager
    async def _async_file_guard(self, path: Path):
        """Ожидает flock без блокировки event loop и утечки lock при отмене."""
        handle = path.open("a+", encoding="utf-8")
        os.chmod(path, 0o600)
        acquired = False
        try:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.02)
            yield
        finally:
            if acquired:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    @contextmanager
    def _breakers_guard(self) -> Iterator[dict[str, Any]]:
        with self.breakers_lock.open("a+", encoding="utf-8") as handle:
            os.chmod(self.breakers_lock, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            state = self._read_json(self.breakers_path, {"provider": {}, "roles": {}, "failures": []})
            try:
                yield state
                self._atomic_write(self.breakers_path, state)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def authorize(self, role: str) -> None:
        """Разрешает CLOSED или единственный HALF_OPEN-запрос."""
        now = self.clock()
        with self._breakers_guard() as state:
            scopes = (("provider", state.setdefault("provider", {})), (f"role:{role}", state.setdefault("roles", {}).setdefault(role, {})))
            expired: list[tuple[str, dict[str, Any]]] = []
            for scope, item in scopes:
                mode = item.get("state", "closed")
                retry_at = float(item.get("retry_at", 0.0))
                lease_until = float(item.get("lease_until", 0.0))
                if mode == "open" and now < retry_at:
                    raise CircuitOpen(scope, retry_at)
                if mode == "half_open" and now < lease_until:
                    raise CircuitOpen(scope, lease_until)
                if mode in {"open", "half_open"}:
                    expired.append((scope, item))
            for _, item in expired:
                item.update({"state": "half_open", "lease_until": now + self.half_open_lease_seconds})

    def record_success(self, role: str) -> None:
        """Закрывает role/provider предохранители после успешного запроса."""
        with self._breakers_guard() as state:
            state["provider"] = {"state": "closed"}
            state.setdefault("roles", {})[role] = {"state": "closed"}
            state["failures"] = []

    def record_failure(self, role: str, failure_class: str, *, retry_after: float | None = None) -> None:
        """Открывает роль и при подтверждении — общий контур провайдера."""
        now = self.clock()
        cooldown = max(self.cooldown_seconds, retry_after or 0.0)
        with self._breakers_guard() as state:
            role_state = state.setdefault("roles", {}).setdefault(role, {})
            if failure_class in TRANSIENT_CLASSES or failure_class == "configuration":
                role_state.update({"state": "open", "retry_at": now + cooldown, "failure_class": failure_class})
            failures = [
                item for item in state.setdefault("failures", [])
                if now - float(item.get("at", 0.0)) <= self.provider_window_seconds
            ]
            if failure_class in TRANSIENT_CLASSES:
                failures.append({"role": role, "at": now, "failure_class": failure_class})
            state["failures"] = failures
            distinct_roles = {item.get("role") for item in failures}
            if failure_class in PROVIDER_IMMEDIATE_CLASSES or len(distinct_roles) >= 2:
                state["provider"] = {
                    "state": "open",
                    "retry_at": now + cooldown,
                    "failure_class": failure_class,
                }

    def reserve_attempt(
        self,
        *,
        task_id: str,
        role: str,
        request_digest: str,
        route: str,
    ) -> AttemptDecision:
        """Резервирует не более одной внешней попытки для task ID."""
        path = self.checkpoint_path(task_id)
        existing = self.existing_attempt(task_id=task_id, role=role, request_digest=request_digest)
        if existing is not None:
            return existing
        checkpoint = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "role": role,
            "request_digest": request_digest,
            "route": route,
            "state": "external_running",
            "external_attempt_count": 1,
            "created_at": self.clock(),
            "updated_at": self.clock(),
        }
        self._atomic_write(path, checkpoint)
        return AttemptDecision("external", checkpoint)

    def existing_attempt(self, *, task_id: str, role: str, request_digest: str) -> AttemptDecision | None:
        """Читает checkpoint до проверки breaker, чтобы cache не зависел от сети."""
        checkpoint = self._read_json(self.checkpoint_path(task_id), {})
        if not checkpoint:
            return None
        if checkpoint.get("request_digest") != request_digest or checkpoint.get("role") != role:
            raise RuntimeError("Коллизия task ID с другим контрактом запроса")
        if checkpoint.get("state") == "complete" and isinstance(checkpoint.get("response"), dict):
            return AttemptDecision("cached", checkpoint)
        return AttemptDecision("native_required", checkpoint)

    def mark_complete(self, task_id: str, response: dict[str, Any], route: str) -> None:
        """Сохраняет локальный результат для идемпотентного повторного запуска."""
        checkpoint = self._required_checkpoint(task_id)
        checkpoint.update({"state": "complete", "route": route, "response": response, "updated_at": self.clock()})
        self._atomic_write(self.checkpoint_path(task_id), checkpoint)
        self.work_order_path(task_id).unlink(missing_ok=True)

    def require_native(
        self,
        *,
        task_id: str,
        role: str,
        request_digest: str,
        failure_class: str,
        reason: str,
        task_brief: str = "",
        context_refs: tuple[str, ...] = (),
        acceptance_criteria: tuple[str, ...] = (),
        output_contract: str = "Краткий проверяемый результат на русском языке.",
        prohibited_capabilities: tuple[str, ...] = ("SQL/x17", "запись в базы", "локальные LLM"),
    ) -> Path:
        """Создаёт детерминированный и очищенный work order для Codex."""
        brief = self._safe_text(task_brief, 1200)
        refs = [self._safe_text(item, 240) for item in context_refs[:12]]
        acceptance = [self._safe_text(item, 300) for item in acceptance_criteria[:12]]
        order = {
            "schema_version": SCHEMA_VERSION,
            "work_order_id": f"omvl-{task_id}",
            "task_id": task_id,
            "status": "pending",
            "role": role,
            "recommended_agent": ROLE_AGENTS.get(role, "codex_terra_fallback"),
            "failure_class": failure_class,
            "reason": self._safe_text(reason, 300),
            "request_digest": request_digest,
            "task_brief": brief,
            "context_refs": refs,
            "acceptance_criteria": acceptance,
            "output_contract": self._safe_text(output_contract, 500),
            "prohibited_capabilities": [self._safe_text(item, 160) for item in prohibited_capabilities[:12]],
            "created_at": self.clock(),
        }
        checkpoint = self._read_json(self.checkpoint_path(task_id), {}) or {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "role": role,
            "request_digest": request_digest,
            "external_attempt_count": 0,
            "created_at": self.clock(),
        }
        if checkpoint.get("role") != role or checkpoint.get("request_digest") != request_digest:
            raise RuntimeError("Коллизия task ID при создании нативного work order")
        path = self.work_order_path(task_id)
        self._atomic_write(path, order)
        checkpoint.update({
            "state": "native_required",
            "failure_class": failure_class,
            "work_order": self._path_reference(path),
            "updated_at": self.clock(),
        })
        checkpoint.pop("response", None)
        self._atomic_write(self.checkpoint_path(task_id), checkpoint)
        return path

    def checkpoint_path(self, task_id: str) -> Path:
        return self.checkpoints / f"{task_id}.json"

    def work_order_path(self, task_id: str) -> Path:
        return self.pending / f"{task_id}.json"

    def list_pending(self) -> list[dict[str, Any]]:
        """Возвращает компактный список ожидающих нативных заданий."""
        result: list[dict[str, Any]] = []
        for path in sorted(self.pending.glob("*.json")):
            order = self._read_json(path, {})
            if order.get("status") in {"pending", "claimed"}:
                result.append({
                    "task_id": order.get("task_id"),
                    "status": order.get("status"),
                    "role": order.get("role"),
                    "recommended_agent": order.get("recommended_agent"),
                    "work_order": str(path),
                })
        return result

    def claim_native(self, task_id: str, agent: str) -> dict[str, Any]:
        """Фиксирует принятие work order родительским оркестратором."""
        with self.task_guard(task_id):
            order = self._read_json(self.work_order_path(task_id), {})
            if not order:
                raise RuntimeError("Work order не найден")
            recommended = str(order.get("recommended_agent", ""))
            if agent != recommended:
                raise RuntimeError(f"Ожидался агент {recommended}, получен {agent}")
            order.update({"status": "claimed", "claimed_by": agent, "claimed_at": self.clock()})
            self._atomic_write(self.work_order_path(task_id), order)
            checkpoint = self._required_checkpoint(task_id)
            checkpoint.update({"state": "native_running", "native_agent": agent, "updated_at": self.clock()})
            self._atomic_write(self.checkpoint_path(task_id), checkpoint)
            return order

    def finish_native(self, task_id: str, status: str, evidence_ref: str) -> None:
        """Завершает нативную фазу без сохранения полного ответа модели."""
        if status not in {"complete", "stop"}:
            raise ValueError("Допустимы только complete или stop")
        with self.task_guard(task_id):
            order = self._read_json(self.work_order_path(task_id), {})
            if order.get("status") != "claimed":
                raise RuntimeError("Work order не был принят оркестратором")
            checkpoint = self._required_checkpoint(task_id)
            checkpoint.update({
                "state": status,
                "native_evidence_ref": self._safe_text(evidence_ref, 300),
                "updated_at": self.clock(),
            })
            checkpoint.pop("response", None)
            self._atomic_write(self.checkpoint_path(task_id), checkpoint)
            self.work_order_path(task_id).unlink(missing_ok=True)

    def _required_checkpoint(self, task_id: str) -> dict[str, Any]:
        checkpoint = self._read_json(self.checkpoint_path(task_id), {})
        if not checkpoint:
            raise RuntimeError("Checkpoint задачи не найден")
        return checkpoint

    @staticmethod
    def _path_reference(path: Path) -> str:
        """Сокращает production-путь, не ломая изолированные runtime-тесты."""
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    @staticmethod
    def _safe_text(value: str, limit: int) -> str:
        text = SECRET_PATTERN.sub("[REDACTED]", str(value)).strip()
        if PRIVATE_PATTERN.search(text):
            text = PRIVATE_PATTERN.sub("[PRIVATE_CONTEXT]", text)
        return text[:limit]

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            quarantine = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}")
            path.replace(quarantine)
            raise RuntimeError(f"Повреждённый runtime-артефакт изолирован: {quarantine.name}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Некорректный runtime-артефакт: {path.name}")
        return value

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
