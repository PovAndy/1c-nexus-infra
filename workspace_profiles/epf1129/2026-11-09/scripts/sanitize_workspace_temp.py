#!/usr/bin/env python3
"""Archive old disposable output while preserving active evidence and source files."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scripts.gate_check import parse_ledger
from scripts.reconcile_reality import parse_handover
from scripts.stabilize_workspace import atomic, digest, encoded, verify_archive

ROOT = Path(__file__).resolve().parents[1]
PINNED_LOG = 'temp/tool_logs/20261108T152249Z_1794151369744336719_01e9892229723dc8.log'
PATH_REFERENCE = re.compile(r'(?:temp|tmp|docs|scripts|build)/[^\s\"\'`<>\[\]{}(),;]+')
SOURCE_EXTENSIONS = frozenset({'.py', '.bsl', '.xml', '.toml', '.yaml', '.yml', '.ps1', '.sh', '.js', '.ts', '.cjs', '.epf', '.erf', '.cf', '.cfu', '.cfe', '.zip', '.jar', '.sqlite', '.sqlite3', '.db', '.lock'})
OUTPUT_EXTENSIONS = frozenset({'.log', '.txt', '.out', '.err', '.stderr', '.stdout', '.raw', '.jsonl', '.csv', '.tsv', '.png', '.jpg', '.html', '.tmp'})


class TempSanitationReport(BaseModel):
    model_config = ConfigDict(extra='allow')
    timestamp_utc: str
    workspace: str
    preserved_critical_files: list[str]
    archived_file_count: int = Field(ge=0)
    archive_path: str = Field(pattern=r'^archive/cleanup_temp_.+\.tar\.gz$')
    archive_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    deleted_stale_count: int = Field(ge=0)
    git_untracked_count_post: int | None = Field(default=None, ge=0)
    compiled_epf_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    provenance_matches_handover: bool
    gates_status_post: str = 'PENDING'
    sanitation_verdict: str
    extension_host_rss_mb: float | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def require_measured_convergence(self) -> TempSanitationReport:
        if self.sanitation_verdict not in ('CONVERGED_SUCCESS', 'EVIDENCE_COMPROMISED', 'PARTIAL_PRESERVED_WORK'):
            raise ValueError('Unknown sanitation verdict')
        if self.sanitation_verdict == 'CONVERGED_SUCCESS':
            if self.git_untracked_count_post is None or self.git_untracked_count_post > 10:
                raise ValueError('Cannot claim convergence by hiding untracked work')
            if not self.provenance_matches_handover or self.gates_status_post != '8/8 PASS':
                raise ValueError('Convergence requires provenance and actual gate checks')
            if self.extension_host_rss_mb is None or self.extension_host_rss_mb > 512:
                raise ValueError('Convergence requires observed low-memory Extension Host')
        return self


def evidence_closure(root: Path, seeds: list[Path]) -> set[Path]:
    """Follow existing textual references; cycles are handled by the visited set."""
    visited: set[Path] = set()
    pending = list(seeds)
    total = 0
    while pending:
        path = pending.pop().resolve()
        if not path.is_relative_to(root.resolve()) or path in visited or not path.is_file():
            continue
        visited.add(path)
        if path.suffix.lower() not in {'.json', '.md', '.log', '.txt', '.py', '.toml'}:
            continue
        size = path.stat().st_size
        total += size
        if size > 16 * 1024**2 or total > 256 * 1024**2:
            raise ValueError('Evidence closure exceeds inspection budget; no deletion permitted')
        text = path.read_text(errors='replace')
        for value in PATH_REFERENCE.findall(text):
            relative = value.rstrip('.:')
            candidate = root / relative
            if candidate.is_file():
                pending.append(candidate)
    return visited


def critical_seeds(root: Path) -> list[Path]:
    gates = parse_ledger(root / 'GATES.md', root=root)
    if len(gates) != 8:
        raise ValueError('Exactly eight acceptance gates required')
    seeds = [root / 'GATES.md', root / 'temp/TASK_HANDOVER.md', root / 'docs/ACTIVE_HANDOVER.md',
             root / 'temp/zcl_next_step.txt', root / PINNED_LOG]
    seeds.extend(gate.evidence_path for gate in gates)
    seeds.extend((root / 'temp/gates').glob('*.json'))
    for name in ('.clinerules', '.cursorrules', 'AGENTS.md', 'system_prompt.md'):
        seeds.append(root / name)
    for name in ('ACTIVE_HANDOVER.md', 'temp/audit/STABILIZATION_VERIFICATION.json',
                 'temp/audit/STABILIZATION_REPORT.json'):
        if (root / name).is_file():
            seeds.append(root / name)
    if any(not p.is_file() for p in seeds):
        raise ValueError('A required evidence file is missing')
    return seeds


def open_files(root: Path) -> set[Path]:
    found: set[Path] = set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    target = fd.resolve()
                    if target.is_relative_to(root) and target.is_file():
                        found.add(target)
                except OSError:
                    continue
        except OSError:
            continue
    return found


def disposable(path: Path, root: Path, protected: set[Path], opened: set[Path], cutoff: float) -> bool:
    relative = path.relative_to(root)
    if relative.parts[0] not in ('temp', 'tmp') or path.is_symlink() or not path.is_file():
        return False
    if relative.parts[:2] in (('temp', 'gates'), ('temp', 'audit')):
        return False
    if path.resolve() in protected or path.resolve() in opened or path.stat().st_mtime >= cutoff:
        return False
    if path.suffix.lower() in SOURCE_EXTENSIONS:
        return False
    if any(part in ('node_modules', '.venv', '.venv-gemini-bridge', 'bsl-language-server') for part in relative.parts):
        return False
    suffix = path.suffix.lower()
    diagnostic_json = suffix == '.json' and bool(re.search(r'audit|report|probe|diagnostic|response|preview|benchmark|trace|dump', path.name, re.I))
    if suffix not in OUTPUT_EXTENSIONS and not diagnostic_json and not re.search(r'\.tmp\d*$', path.name):
        return False
    if suffix == '.txt':
        with path.open('rb') as stream:
            beginning = stream.read(4096).decode(errors='replace')
        if re.search(r'(?m)^\s*(?:Процедура|Функция|class |def |function |#!)', beginning):
            return False
    return True


def assert_protected(root: Path, hashes: dict[str, str]) -> None:
    changed = [name for name, expected in hashes.items() if not (root / name).is_file() or digest(root / name) != expected]
    if changed:
        raise ValueError('Protected evidence changed: ' + ', '.join(changed[:3]))


def make_plan(root: Path, expected_epf: str) -> dict[str, Any]:
    if digest(root / 'build/compiled.epf') != expected_epf:
        raise ValueError('Compiled artifact differs from the requested baseline')
    canonical = parse_handover(root / 'docs/ACTIVE_HANDOVER.md').compiled_sha256
    match = re.search(r'```json\s*(.*?)\s*```', (root / 'temp/TASK_HANDOVER.md').read_text(), re.S)
    if match is None or canonical != expected_epf or json.loads(match.group(1)).get('epf_sha256') != expected_epf:
        raise ValueError('Active handovers do not match the compiled artifact')
    protected = evidence_closure(root, critical_seeds(root))
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in sorted(protected)}
    opened = open_files(root)
    cutoff = time.time() - 86400
    candidates = []
    for folder in ('temp', 'tmp'):
        for path in (root / folder).rglob('*'):
            if disposable(path, root, protected, opened, cutoff):
                before = path.stat()
                sha = digest(path)
                after = path.stat()
                if (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns):
                    candidates.append({'path': path.relative_to(root).as_posix(), 'sha256': sha,
                                       'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns, 'inode': before.st_ino})
    assert_protected(root, hashes)
    return {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'compiled_epf_sha256': expected_epf,
            'protected_sha256': hashes, 'candidates': candidates,
            'candidate_bytes': sum(row['bytes'] for row in candidates),
            'policy': 'Only old regular disposable output in temp/tmp; preserve source, binaries, locks, live/open files, audit and gate namespaces'}


def apply_plan(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    assert_protected(root, plan['protected_sha256'])
    if digest(root / 'build/compiled.epf') != plan['compiled_epf_sha256']:
        raise ValueError('Compiled artifact changed after planning')
    opened = open_files(root)
    candidates = []
    for row in plan['candidates']:
        path = root / row['path']
        if not path.resolve().is_relative_to(root) or not disposable(path, root,
                {(root / name).resolve() for name in plan['protected_sha256']}, opened, time.time() - 86400):
            raise ValueError('Candidate is no longer safe to archive')
        current = path.stat()
        if (current.st_ino, current.st_size, current.st_mtime_ns) != (row['inode'], row['bytes'], row['mtime_ns']) or digest(path) != row['sha256']:
            raise ValueError('Candidate changed after planning; originals retained')
        candidates.append(row)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = root / 'archive' / ('cleanup_temp_' + stamp + '.tar.gz')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    manifest = {row['path']: row for row in candidates}
    with temporary.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        with tarfile.open(fileobj=output, mode='w:gz', compresslevel=1) as archive:
            for row in candidates:
                archive.add(root / row['path'], arcname=row['path'], recursive=False)
            data = encoded(manifest)
            member = tarfile.TarInfo('MANIFEST.json')
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        output.flush()
        os.fsync(output.fileno())
    verify_archive(temporary, manifest)
    assert_protected(root, plan['protected_sha256'])
    temporary.replace(target)
    deleted, retained = [], []
    current_opened = open_files(root)
    for row in candidates:
        path = root / row['path']
        if path.is_symlink() or path.resolve() in current_opened:
            retained.append(row['path'])
            continue
        current = path.stat()
        if (current.st_ino, current.st_size, current.st_mtime_ns) == (row['inode'], row['bytes'], row['mtime_ns']) and digest(path) == row['sha256']:
            path.unlink()
            deleted.append(row['path'])
        else:
            retained.append(row['path'])
    assert_protected(root, plan['protected_sha256'])
    result = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'workspace': str(root),
              'preserved_critical_files': sorted(plan['protected_sha256']),
              'protected_sha256': plan['protected_sha256'], 'archived_file_count': len(candidates),
              'archive_path': target.relative_to(root).as_posix(), 'archive_sha256': digest(target),
              'archive_bytes': target.stat().st_size, 'original_bytes': plan['candidate_bytes'],
              'deleted_stale_count': len(deleted), 'retained_changed_or_open': retained,
              'compiled_epf_sha256': plan['compiled_epf_sha256'], 'provenance_matches_handover': True,
              'gate_verification': 'PENDING', 'sanitation_verdict': 'PARTIAL_PRESERVED_WORK'}
    validated = TempSanitationReport.model_validate(result).model_dump()
    atomic(root / 'temp/audit/TEMP_SANITATION_REPORT.json', encoded(validated))
    return validated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-epf-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    plan_path = ROOT / 'temp/audit/TEMP_SANITATION_PLAN.json'
    if args.apply:
        plan = json.loads(plan_path.read_text())
        if plan['compiled_epf_sha256'] != args.expected_epf_sha256:
            raise ValueError('Plan belongs to a different compiled artifact')
        result = apply_plan(ROOT, plan)
        print(f'ARCHIVE_VERIFIED: archived={result["archived_file_count"]}; removed={result["deleted_stale_count"]}; protected={len(result["preserved_critical_files"])}')
    else:
        plan = make_plan(ROOT, args.expected_epf_sha256)
        atomic(plan_path, encoded(plan))
        print(f'PREVIEW: files={len(plan["candidates"])}; bytes={plan["candidate_bytes"]}; protected={len(plan["protected_sha256"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
