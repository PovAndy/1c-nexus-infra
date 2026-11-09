"""Validate regenerated acceptance receipts without weakening immutable contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.gate_check import parse_ledger
from scripts.stabilize_workspace import digest


def is_volatile_receipt(relative: str) -> bool:
    path = Path(relative)
    return relative == 'temp/deployment_report.json' or (path.parts[:2] == ('temp', 'gates') and path.suffix == '.json')


def read_stable_json(path: Path) -> tuple[dict[str, Any], int]:
    for attempt in range(3):
        before = path.stat()
        value = json.loads(path.read_text())
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns):
            if not isinstance(value, dict):
                raise ValueError('Receipt must contain a JSON object')
            return value, after.st_mtime_ns
    raise ValueError('Receipt kept changing while being read')


def validate_receipt(root: Path, relative: str, expected_epf: str, not_before_ns: int | None = None) -> None:
    data, modified = read_stable_json(root / relative)
    if not_before_ns is not None and modified < not_before_ns:
        raise ValueError('Execution receipt predates the requested verification')
    if relative == 'temp/deployment_report.json':
        if data.get('schema_version') != '1.0' or data.get('status') != 'PASS' or data.get('error') is not None:
            raise ValueError('Deployment receipt did not pass')
        if data.get('source_fresh') is not True or data.get('profile') not in ('local', 'remote'):
            raise ValueError('Deployment receipt source or target is unverified')
        if any(str(data.get(key, '')).lower() != expected_epf for key in ('build_sha256', 'target_sha256')):
            raise ValueError('Deployment receipt belongs to a different artifact')
        if not isinstance(data.get('checked_at'), (int, float)) or data['checked_at'] <= 0:
            raise ValueError('Deployment receipt has no valid execution time')
        if not_before_ns is not None and data['checked_at'] * 1e9 < not_before_ns:
            raise ValueError('Deployment execution time is stale')
        return
    gates = parse_ledger(root / 'GATES.md', root=root)
    matches = [gate for gate in gates if gate.evidence_path.name == Path(relative).name]
    if len(matches) != 1:
        raise ValueError('Receipt does not identify one ledger gate')
    gate = matches[0]
    if data.get('status') != 'PASS' or data.get('returncode') != 0 or data.get('regex_matched') is not True:
        raise ValueError('Gate receipt did not pass')
    if data.get('gate_id') != gate.gate_id or data.get('command_sha256') != hashlib.sha256(gate.command.encode()).hexdigest():
        raise ValueError('Gate receipt does not match its current command')
    if data.get('expected_exit') != gate.expected_exit:
        raise ValueError('Gate receipt expectations changed')


def verify_runtime_contracts(root: Path, hashes: dict[str, str], expected_epf: str) -> dict[str, list[str]]:
    if digest(root / 'build/compiled.epf') != expected_epf:
        raise ValueError('Immutable compiled artifact changed')
    refreshed = []
    rule_updates = []
    for relative, old_sha in hashes.items():
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('Contract path must remain inside the workspace')
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Contract path escaped the workspace')
        if is_volatile_receipt(relative):
            validate_receipt(root, relative, expected_epf)
            if digest(path) != old_sha:
                refreshed.append(relative)
        elif relative in ('.clinerules', '.cursorrules', 'AGENTS.md', 'system_prompt.md'):
            content = path.read_bytes()
            prefix, marker, tail = content.partition(b'<!-- PROMPT_CACHE_BOUNDARY -->')
            prefix = prefix.rstrip(b'\r\n')
            if not marker or len(prefix) != 15632 or hashlib.sha256(prefix).hexdigest() != 'bd29af5ec66654834aa0c497e73f8a6fa56b04ce08c6ca1e0c0d2d9e8ab4ab4b':
                raise ValueError('Immutable static prompt prefix changed: ' + relative)
            if digest(path) != old_sha:
                rule_updates.append(relative)
        elif not path.is_file() or digest(path) != old_sha:
            raise ValueError('Immutable contract changed: ' + relative)
    return {'validated_volatile_updates': refreshed, 'validated_dynamic_rule_updates': rule_updates}
