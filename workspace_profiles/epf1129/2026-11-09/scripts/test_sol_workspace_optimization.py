"""Verify evidence preservation and conservative candidate selection."""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from scripts.gate_check import run_ledger
from scripts.sanitize_workspace_temp import apply_plan, disposable, evidence_closure
from scripts.stabilize_workspace import digest
from scripts.restart_workspace_extension_host import identity


class SolOptimizationTests(unittest.TestCase):
    def test_python_and_missing_pid_are_not_extension_hosts(self) -> None:
        own = identity(os.getpid())
        self.assertIsNotNone(own)
        self.assertFalse(own['extension_host'])
        self.assertIsNone(identity(2**31 - 1))

    def test_evidence_closure_handles_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'temp').mkdir()
            a, b = root / 'temp/a.json', root / 'temp/b.log'
            a.write_text('{"log":"temp/b.log"}')
            b.write_text('next: temp/a.json')
            self.assertEqual(evidence_closure(root, [a]), {a, b})

    def test_sources_and_referenced_logs_are_never_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'temp').mkdir()
            for name in ('module.bsl', 'probe.log', 'other.log', 'snippet.txt'):
                path = root / 'temp' / name
                path.write_text('Процедура Тест()\n' if name == 'snippet.txt' else 'evidence')
                os.utime(path, (1, 1))
            protected = {root / 'temp/probe.log'}
            cutoff = time.time() - 86400
            self.assertFalse(disposable(root / 'temp/module.bsl', root, protected, set(), cutoff))
            self.assertFalse(disposable(root / 'temp/probe.log', root, protected, set(), cutoff))
            self.assertFalse(disposable(root / 'temp/snippet.txt', root, protected, set(), cutoff))
            self.assertTrue(disposable(root / 'temp/other.log', root, protected, set(), cutoff))
            self.assertFalse(disposable(root / 'temp/other.log', root, protected, {root / 'temp/other.log'}, cutoff))

    def test_versioned_gate_run_preserves_original_and_cannot_mask_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            ledger = root / 'GATES.md'
            ledger.write_text('## G1\nCHECK: python3 -c "print(123)"\nEXPECT: exitcode=0; regex=123\nEVIDENCE: temp/gates/g1.json\n')
            self.assertEqual(run_ledger(ledger, root=root, reverify=True), 0)
            proof = root / 'temp/gates/g1.json'
            original = digest(proof)
            self.assertEqual(run_ledger(ledger, root=root, reverify=True, evidence_run='fresh'), 0)
            self.assertEqual(digest(proof), original)
            self.assertTrue((root / 'temp/gates/fresh/g1.json').is_file())
            self.assertEqual(run_ledger(ledger, root=root, reverify=True, evidence_run='fresh'), 1)
            self.assertEqual(run_ledger(ledger, root=root, reverify=True, evidence_run='../escape'), 1)
            ledger.write_text(ledger.read_text().replace('print(123)', 'raise SystemExit(2)'))
            self.assertEqual(run_ledger(ledger, root=root, reverify=True, evidence_run='failure'), 1)
            self.assertEqual(digest(proof), original)

    def test_archive_roundtrip_keeps_active_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'temp/tool_logs').mkdir(parents=True)
            (root / 'build').mkdir()
            (root / 'build/compiled.epf').write_bytes(b'unchanged binary')
            proof = root / 'temp/tool_logs/active.log'
            proof.write_text('active evidence')
            old = root / 'temp/tool_logs/old.log'
            old.write_text('complete obsolete output')
            os.utime(old, (1, 1))
            s = old.stat()
            plan = {'compiled_epf_sha256': digest(root / 'build/compiled.epf'),
                    'protected_sha256': {'temp/tool_logs/active.log': digest(proof)},
                    'candidate_bytes': s.st_size, 'candidates': [{'path': 'temp/tool_logs/old.log',
                    'sha256': digest(old), 'inode': s.st_ino, 'bytes': s.st_size, 'mtime_ns': s.st_mtime_ns}]}
            original = digest(proof)
            result = apply_plan(root, plan)
            self.assertEqual(result['deleted_stale_count'], 1)
            self.assertFalse(old.exists())
            self.assertEqual(digest(proof), original)
            self.assertTrue((root / result['archive_path']).is_file())


if __name__ == '__main__':
    unittest.main()
