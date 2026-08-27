"""Общие fail-closed утилиты event-hook контура."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIRS = frozenset({".git", ".venv", ".venv-gemini-bridge", "archive", "logs", "runtime", "temp", "tmp"})


def workspace_root() -> Path:
    """Возвращает единственный разрешенный корень, не доверяя данным hook-события."""
    return ROOT.resolve()


def resolve_target(value: str | None) -> Path | None:
    """Принимает только существующий или будущий путь внутри рабочего корня."""
    if not value or not isinstance(value, str):
        return None
    root = workspace_root()
    candidate = Path(value)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def is_runtime_path(path: Path) -> bool:
    """Исключает артефакты, которые не должны повторно порождать hook-события."""
    try:
        relative = path.resolve().relative_to(workspace_root())
    except ValueError:
        return True
    return any(part in RUNTIME_DIRS for part in relative.parts)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Атомарно записывает небольшой state-файл с приватными правами."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any] | None:
    """Возвращает только объект JSON; поврежденный state не считается корректным."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def file_fingerprint(path: Path) -> str:
    """Возвращает короткий хеш содержимого для loop-guard без хранения исходника."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65_536), b""):
                digest.update(chunk)
    except OSError:
        return "missing"
    return digest.hexdigest()
