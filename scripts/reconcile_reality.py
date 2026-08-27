#!/usr/bin/env python3
"""Сверяет фактическое состояние среды с ACTIVE_HANDOVER без записи в базы."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_RE = re.compile(r'Srvr="[^"]+";Ref="(?P<target>postgres(?:3|9))";')
CURRENT_HASH_RE = re.compile(r"Текущий рабочий файл отличается \(SHA-256\s+`(?P<hash>[0-9a-fA-F]{64})`\)")
VERIFIED_HASH_RE = re.compile(r"SHA-256\s+`(?P<hash>[0-9a-fA-F]{64})`")


@dataclass(frozen=True)
class HandoverFacts:
    database_target: str
    compiled_sha256: str


def sha256_file(path: Path) -> str:
    """Возвращает SHA-256 файла потоково."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_handover(path: Path) -> HandoverFacts:
    """Извлекает первый активный target и SHA текущего compiled.epf из handover."""
    text = path.read_text(encoding="utf-8")
    target = TARGET_RE.search(text)
    current_hash = CURRENT_HASH_RE.search(text)
    verified_hash = VERIFIED_HASH_RE.search(text)
    if target is None:
        raise ValueError("в ACTIVE_HANDOVER.md не найден активный target postgres3/postgres9")
    match = current_hash or verified_hash
    if match is None:
        raise ValueError("в ACTIVE_HANDOVER.md не найден SHA-256 compiled.epf")
    return HandoverFacts(target.group("target"), match.group("hash").lower())


def git_status(root: Path) -> list[str]:
    """Возвращает porcelain снимок tracked-изменений без untracked шума."""
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=no"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=5,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git status завершился ошибкой")
    return sorted(line for line in result.stdout.splitlines() if line)


def git_head(root: Path) -> str:
    """Возвращает HEAD без сетевого доступа."""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=3,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git rev-parse завершился ошибкой")
    return result.stdout.strip()


def make_snapshot(root: Path, facts: HandoverFacts, status: list[str], compiled_hash: str) -> dict[str, object]:
    """Создает компактный снимок без исходников, секретов и содержимого баз."""
    status_digest = hashlib.sha256("\n".join(status).encode("utf-8", errors="surrogateescape")).hexdigest()
    return {
        "schema_version": "1.0", "head": git_head(root), "status_sha256": status_digest,
        "status_count": len(status), "handover": asdict(facts), "compiled_sha256": compiled_hash,
    }


def read_snapshot(path: Path) -> dict[str, object] | None:
    """Читает ранее принятый локальный снимок."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_snapshot(path: Path, snapshot: dict[str, object]) -> None:
    """Атомарно сохраняет компактный baseline следующего SessionStart."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def reconcile(root: Path, handover: Path, state: Path, accept_current: bool) -> tuple[bool, list[str]]:
    """Сверяет target, compiled EPF и git snapshot; сетевых и DB-вызовов нет."""
    facts = parse_handover(handover)
    compiled = root / "build" / "compiled.epf"
    if not compiled.is_file():
        return False, ["compiled.epf отсутствует"]
    actual_hash = sha256_file(compiled)
    status = git_status(root)
    snapshot = make_snapshot(root, facts, status, actual_hash)
    differences: list[str] = []
    if actual_hash != facts.compiled_sha256:
        differences.append("SHA-256 build/compiled.epf не совпадает с ACTIVE_HANDOVER.md")
    previous = read_snapshot(state)
    if accept_current or previous is None:
        write_snapshot(state, snapshot)
        return (not differences), (differences or ["baseline принят из текущего документированного состояния"])
    for key in ("head", "status_sha256", "status_count", "handover", "compiled_sha256"):
        if previous.get(key) != snapshot.get(key):
            differences.append(f"drift поля {key}")
    if differences:
        return False, differences + status[:12]
    return True, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--handover", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--accept-current", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    root = args.root.resolve()
    handover = (args.handover or root / "docs" / "ACTIVE_HANDOVER.md").resolve()
    state = (args.state or root / "temp" / "reality_reconciliation.state.json").resolve()
    try:
        passed, details = reconcile(root, handover, state, args.accept_current)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"REALITY_CHECK: WARN; {exc}")
        return 0
    elapsed_ms = (time.perf_counter() - started) * 1000
    if passed:
        suffix = f"; {details[0]}" if details else ""
        print(f"REALITY_CHECK: PASS; elapsed_ms={elapsed_ms:.1f}{suffix}")
    else:
        print("REALITY_CHECK: WARN; " + "; ".join(details[:16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
