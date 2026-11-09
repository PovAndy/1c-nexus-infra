#!/usr/bin/env python3
"""Explicitly authorized, identity-checked Extension Host restart after audit flush."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.stabilize_workspace import atomic, encoded, processes
from scripts.workspace_runtime_receipts import verify_runtime_contracts

ROOT = Path(__file__).resolve().parents[1]


def identity(pid: int) -> dict[str, Any] | None:
    path = Path('/proc') / str(pid)
    try:
        command = (path / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        raw = (path / 'stat').read_text()
        fields = raw[raw.rfind(')') + 2:].split()
        return {'pid': pid, 'start_ticks': fields[19], 'exe': str((path / 'exe').resolve()),
                'uid': path.stat().st_uid, 'state': fields[0],
                'extension_host': '--type=extensionHost' in command}
    except (OSError, ValueError, IndexError):
        return None


def worker(args: argparse.Namespace) -> int:
    time.sleep(args.delay_seconds)
    result: dict[str, Any] = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                              'pid_requested': args.pid, 'signal': 'SIGTERM', 'status': 'SKIPPED'}
    same_boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip() == args.boot_id
    current = identity(args.pid)
    expected = {'pid': args.pid, 'start_ticks': args.start_ticks, 'exe': args.expected_exe,
                'uid': os.getuid(), 'extension_host': True}
    if current is None:
        result['status'] = 'ALREADY_EXITED'
    elif not same_boot or any(current.get(k) != value for k, value in expected.items()):
        result['status'] = 'IDENTITY_MISMATCH_NO_SIGNAL'
    else:
        report_path = ROOT / 'temp/audit/TEMP_SANITATION_REPORT.json'
        report = json.loads(report_path.read_text())
        verify_runtime_contracts(ROOT, report['protected_sha256'], report['compiled_epf_sha256'])
        if report.get('gates_status_post') != '8/8 PASS':
            raise ValueError('Restart requires actual post-cleanup gate verification')
        atomic(ROOT / 'temp/audit/EXTENSION_HOST_RESTART_RESULT.json', encoded(dict(result, status='SIGNAL_PENDING')))
        os.kill(args.pid, signal.SIGTERM)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            observed = identity(args.pid)
            if observed is None or observed['state'] == 'Z' or observed['start_ticks'] != args.start_ticks:
                result['status'] = 'TERMINATED'
                break
            time.sleep(0.25)
        else:
            result['status'] = 'STILL_RUNNING_NO_SIGKILL'
    result['observed_extension_hosts'] = [r for r in processes() if r['kind'] == 'extension-host']
    result['rss_limit_guaranteed'] = False
    atomic(ROOT / 'temp/audit/EXTENSION_HOST_RESTART_RESULT.json', encoded(result))
    return 0 if result['status'] in ('TERMINATED', 'ALREADY_EXITED') else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--start-ticks', required=True)
    parser.add_argument('--expected-exe', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--delay-seconds', type=int, default=45)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.pid <= 1 or not 5 <= args.delay_seconds <= 120:
        parser.error('Unsafe PID or restart delay')
    if args.worker:
        try:
            return worker(args)
        except (OSError, ValueError, KeyError) as exc:
            atomic(ROOT / 'temp/audit/EXTENSION_HOST_RESTART_RESULT.json', encoded({
                'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'pid_requested': args.pid,
                'status': 'STOP_CONTRACT_OR_RECEIPT_INVALID', 'error_type': type(exc).__name__,
                'detail': str(exc).splitlines()[0][:160], 'signal_sent': False}))
            return 2
    current = identity(args.pid)
    if current is None:
        print('Extension Host already exited; no signal scheduled')
        atomic(ROOT / 'temp/audit/EXTENSION_HOST_RESTART_RESULT.json', encoded({'pid_requested': args.pid, 'status': 'ALREADY_EXITED'}))
        return 0
    expected = {'start_ticks': args.start_ticks, 'exe': args.expected_exe, 'uid': os.getuid(), 'extension_host': True}
    if any(current.get(key) != value for key, value in expected.items()):
        raise ValueError('PID identity does not match the requested Extension Host')
    log_path = ROOT / 'temp/audit/EXTENSION_HOST_RESTART_WORKER.log'
    with log_path.open('ab') as output:
        os.chmod(log_path, 0o600)
        command = [sys.executable, '-m', 'scripts.restart_workspace_extension_host', *sys.argv[1:], '--worker']
        child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    atomic(ROOT / 'temp/audit/EXTENSION_HOST_RESTART_SCHEDULE.json', encoded({
        'pid': args.pid, 'worker_pid': child.pid, 'delay_seconds': args.delay_seconds,
        'status': 'SCHEDULED', 'expected_exe': args.expected_exe, 'start_ticks': args.start_ticks}))
    print(f'RESTART_SCHEDULED: PID={args.pid}; delay={args.delay_seconds}s; result=temp/audit/EXTENSION_HOST_RESTART_RESULT.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
