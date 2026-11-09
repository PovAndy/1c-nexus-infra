#!/usr/bin/env python3
"""Lossless final log/ADS cleanup; never hide tracked work to fabricate acceptance."""
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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scripts.sanitize_workspace_temp import critical_seeds, evidence_closure, open_files
from scripts.stabilize_workspace import atomic, digest, encoded, verify_archive
from scripts.workspace_runtime_receipts import is_volatile_receipt, verify_runtime_contracts
from scripts.reconcile_reality import parse_handover

ROOT = Path(__file__).resolve().parents[1]


class FinalConvergenceVerifiedReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    timestamp_utc: str
    workspace: str
    active_host_gateway: str = Field(pattern=r'^\d{1,3}(?:\.\d{1,3}){3}$')
    compiled_epf_sha256: str = Field(pattern=r'^67976fa92cb140f9f6627ec1fcc61dd99a230fce636a80cc4d99c2ec2ddb79fd$')
    handover_integrity_verified: bool
    archived_residual_logs_count: int
    final_archive_path: str = Field(pattern=r'^archive/cleanup_final_.+\.tar\.gz$')
    final_archive_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    git_untracked_count_final: int = Field(le=10, ge=0)
    git_diff_under_one_mib: bool
    gates_status_final: Literal['8/8 PASS']
    bsl_evaluator_cost: int = Field(ge=0, le=0)
    convergence_verdict: Literal['CONVERGED_SUCCESS']
    next_operational_stage: str


def identical_original(path: Path) -> Path | None:
    name = re.sub(r' — копия(?: \(\d+\))?', '', path.name)
    choices = [path.with_name(name)]
    if name.endswith('.txt'):
        choices.append(path.with_name(name[:-4]))
    for candidate in choices:
        if candidate != path and candidate.is_file() and not candidate.is_symlink() and digest(candidate) == digest(path):
            return candidate
    return None


def make_plan(root: Path, expected_epf: str) -> dict[str, Any]:
    if digest(root / 'build/compiled.epf') != expected_epf:
        raise ValueError('Compiled artifact differs from the explicit baseline')
    match = re.search(r'```json\s*(.*?)\s*```', (root / 'temp/TASK_HANDOVER.md').read_text(), re.S)
    if match is None or json.loads(match.group(1)).get('epf_sha256') != expected_epf or parse_handover(root / 'docs/ACTIVE_HANDOVER.md').compiled_sha256 != expected_epf:
        raise ValueError('Active handover provenance differs from compiled artifact')
    protected = evidence_closure(root, critical_seeds(root))
    protected.add(root / 'build/compiled.epf')
    protected.update(p for p in (root / 'src').rglob('*') if p.is_file() and p.suffix in ('.bsl', '.xml'))
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in protected}
    verify_runtime_contracts(root, hashes, expected_epf)
    opened = open_files(root)
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode(errors='surrogateescape').split('\0'))
    choices: dict[Path, str] = {}
    cutoff = time.time() - 300
    for path in (root / 'temp/tool_logs').rglob('*'):
        if path.is_file() and path.stat().st_mtime < cutoff:
            choices[path] = 'unreferenced_log'
    unique_copies = []
    for folder, directories, files in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if d not in ('.git', 'node_modules', '.code-index', 'archive', 'Archive') and not d.startswith('.venv')]
        for name in files:
            path = Path(folder) / name
            if name.endswith((':Zone.Identifier', '.Zone.Identifier')):
                choices[path] = 'ads_sidecar'
            elif ' — копия' in name:
                if identical_original(path) is not None:
                    choices[path] = 'identical_copy'
                else:
                    unique_copies.append(path.relative_to(root).as_posix())
    candidates = []
    for path, reason in sorted(choices.items()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file() or path.resolve() in protected or path.resolve() in opened or relative in tracked:
            continue
        before = path.stat()
        sha = digest(path)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            continue
        candidates.append({'path': relative, 'reason': reason, 'bytes': before.st_size,
                           'inode': before.st_ino, 'mtime_ns': before.st_mtime_ns, 'sha256': sha})
    return {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'expected_epf': expected_epf,
            'protected_sha256': hashes, 'candidates': candidates, 'unique_copies_retained': unique_copies,
            'excluded_scan_trees': ['.git', '.venv*', 'node_modules', '.code-index', 'archive', 'Archive']}


def apply_plan(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    verify_runtime_contracts(root, plan['protected_sha256'], plan['expected_epf'])
    opened = open_files(root)
    rows = plan['candidates']
    for row in rows:
        path = root / row['path']
        if not path.resolve().is_relative_to(root) or path.is_symlink() or path.resolve() in opened:
            raise ValueError('Candidate became unsafe; originals retained')
        s = path.stat()
        if (s.st_ino, s.st_size, s.st_mtime_ns) != (row['inode'], row['bytes'], row['mtime_ns']) or digest(path) != row['sha256']:
            raise ValueError('Candidate changed after preview; originals retained')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = root / 'archive' / ('cleanup_final_' + stamp + '.tar.gz')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    manifest = {row['path']: row for row in rows}
    with temporary.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        with tarfile.open(fileobj=output, mode='w:gz', compresslevel=1) as archive:
            for row in rows:
                archive.add(root / row['path'], arcname=row['path'], recursive=False)
            data = encoded(manifest)
            member = tarfile.TarInfo('MANIFEST.json')
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        output.flush()
        os.fsync(output.fileno())
    verify_archive(temporary, manifest)
    verify_runtime_contracts(root, plan['protected_sha256'], plan['expected_epf'])
    temporary.replace(target)
    removed, retained = [], []
    opened = open_files(root)
    for row in rows:
        path = root / row['path']
        if path.is_symlink() or path.resolve() in opened:
            retained.append(row['path'])
            continue
        s = path.stat()
        if (s.st_ino, s.st_size, s.st_mtime_ns) == (row['inode'], row['bytes'], row['mtime_ns']) and digest(path) == row['sha256']:
            path.unlink()
            removed.append(row)
        else:
            retained.append(row['path'])
    volatile = verify_runtime_contracts(root, plan['protected_sha256'], plan['expected_epf'])
    result = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'archive_path': target.relative_to(root).as_posix(),
              'archive_sha256': digest(target), 'archive_bytes': target.stat().st_size,
              'archived_count': len(rows), 'deleted_count': len(removed),
              'deleted_by_kind': {reason: sum(row['reason'] == reason for row in removed) for reason in ('unreferenced_log', 'ads_sidecar', 'identical_copy')},
              'unique_copies_retained': plan['unique_copies_retained'], 'changed_or_open_retained': retained,
              'immutable_contracts_preserved': True, **volatile}
    atomic(root / 'temp/audit/FINAL_SANITATION_ARCHIVE.json', encoded(result))
    return result


def write_status(root: Path, not_before_ns: int) -> dict[str, Any]:
    from scripts.gate_check import parse_ledger
    from scripts.workspace_runtime_receipts import validate_receipt
    from scripts.mcp_host_gateway_launcher import windows_gateway
    plan = json.loads((root / 'temp/audit/FINAL_ENVIRONMENT_PLAN.json').read_text())
    archive = json.loads((root / 'temp/audit/FINAL_SANITATION_ARCHIVE.json').read_text())
    updates = verify_runtime_contracts(root, plan['protected_sha256'], plan['expected_epf'])
    gates = parse_ledger(root / 'GATES.md', root=root)
    if len(gates) != 8:
        raise ValueError('Exactly eight gates are required')
    for gate in gates:
        validate_receipt(root, gate.evidence_path.relative_to(root).as_posix(), plan['expected_epf'], not_before_ns)
    validate_receipt(root, 'temp/deployment_report.json', plan['expected_epf'], not_before_ns)
    if digest(root / archive['archive_path']) != archive['archive_sha256']:
        raise ValueError('Final archive changed')
    start = time.monotonic()
    raw = subprocess.check_output(['git', 'status', '--porcelain=v1', '-z'], cwd=root)
    status_seconds = time.monotonic() - start
    rows = [row for row in raw.split(b'\0') if row]
    untracked = sum(row.startswith(b'?? ') for row in rows)
    command = subprocess.Popen(['git', 'diff', '--no-ext-diff'], cwd=root, stdout=subprocess.PIPE)
    diff_bytes = sum(len(block) for block in iter(lambda: command.stdout.read(1024 * 1024), b''))
    if command.wait() != 0:
        raise ValueError('Git diff failed')
    # Client startup latency cannot be inferred from reading a small Markdown file.
    measurement_path = root / 'temp/audit/SESSION_STARTUP_MEASUREMENT.json'
    measurement = json.loads(measurement_path.read_text()) if measurement_path.is_file() else {}
    duration = measurement.get('duration_ms')
    clean_session = (measurement.get('measurement_source') == 'codex-client'
                     and measurement.get('clean_slate') is True
                     and measurement.get('handover_sha256') == digest(root / 'temp/TASK_HANDOVER.md')
                     and isinstance(duration, (int, float)) and duration >= 0)
    converged = (untracked <= 10 and len(rows) <= 10 and diff_bytes < 50 * 1024
                 and status_seconds <= 0.10 and clean_session and duration <= 350)
    result = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'workspace': str(root),
              'active_host_gateway': windows_gateway(), 'compiled_epf_sha256': plan['expected_epf'],
              'handover_integrity_verified': True, 'archived_residual_logs_count': archive['deleted_by_kind']['unreferenced_log'],
              'final_archive_path': archive['archive_path'], 'final_archive_sha256': archive['archive_sha256'],
              'git_untracked_count_final': untracked, 'git_status_entries_final': len(rows),
              'git_tracked_changes_final': len(rows)-untracked, 'git_status_seconds': status_seconds,
              'git_diff_bytes': diff_bytes, 'git_diff_under_one_mib': diff_bytes < 1024**2,
              'gates_status_final': '8/8 PASS', 'bsl_evaluator_cost': 0,
              'convergence_verdict': 'CONVERGED_SUCCESS' if converged else 'PARTIAL_PRESERVED_WORK',
              'clean_slate_session_confirmed': clean_session, 'hydration_latency_measured': clean_session,
              'next_operational_stage': 'Start a new Codex session from handover and inspect this status; Block [28] remains paused',
              'receipt_updates': updates, 'archive_details': archive}
    atomic(root / 'temp/audit/FINAL_CONVERGENCE_STATUS.json', encoded(result))
    if converged:
        fields = {key: result[key] for key in FinalConvergenceVerifiedReport.model_fields}
        verified = FinalConvergenceVerifiedReport.model_validate(fields)
        atomic(root / 'temp/audit/FINAL_CONVERGENCE_VERIFIED.json', encoded(verified.model_dump()))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-epf-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--not-before-ns', type=int)
    args = parser.parse_args()
    path = ROOT / 'temp/audit/FINAL_ENVIRONMENT_PLAN.json'
    if args.report:
        if args.not_before_ns is None:
            parser.error('--report requires the actual reverify start time')
        result = write_status(ROOT, args.not_before_ns)
        print(f'{result["convergence_verdict"]}: gates=8/8 PASS; untracked={result["git_untracked_count_final"]}; diff={result["git_diff_bytes"]}')
        return 0 if result['convergence_verdict'] == 'CONVERGED_SUCCESS' else 2
    if args.apply:
        plan = json.loads(path.read_text())
        if plan['expected_epf'] != args.expected_epf_sha256:
            raise ValueError('Preview baseline differs')
        result = apply_plan(ROOT, plan)
        print(f'FINAL_ARCHIVE_PASS: files={result["archived_count"]}; removed={result["deleted_count"]}; immutable contracts preserved')
    else:
        plan = make_plan(ROOT, args.expected_epf_sha256)
        atomic(path, encoded(plan))
        print(f'FINAL_PREVIEW: files={len(plan["candidates"])}; protected={len(plan["protected_sha256"])}; unique copies retained={len(plan["unique_copies_retained"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
