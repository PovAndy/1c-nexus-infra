"""Создает атомарную резервную копию существующего целевого файла до изменения."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    from .common import is_runtime_path, resolve_target, workspace_root
except ImportError:  # прямой запуск скрипта
    from common import is_runtime_path, resolve_target, workspace_root


BACKUP_DIR = workspace_root() / "archive" / "backups"


def backup_target(file_path: str | None) -> Path | None:
    """Копирует только обычный непустой файл внутри проекта; runtime-пути игнорируются."""
    target = resolve_target(file_path)
    if target is None or is_runtime_path(target) or not target.is_file() or target.stat().st_size == 0:
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    safe_name = target.name.replace("/", "_").replace("\\", "_")
    destination = BACKUP_DIR / f"{timestamp}_{safe_name}.bak"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with target.open("rb") as source, temporary.open("xb") as output:
            shutil.copyfileobj(source, output, length=64 * 1024)
            output.flush()
            os.fsync(output.fileno())
        shutil.copystat(target, temporary, follow_symlinks=False)
        os.replace(temporary, destination)
        return destination
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
