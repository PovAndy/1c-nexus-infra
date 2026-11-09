"""Regression checks for lossless archive cleanup and configuration preservation."""
from __future__ import annotations

import os
import tarfile
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from scripts.stabilize_workspace import StabilizationReport, archive_logs, update_toml


class StabilizationTests(unittest.TestCase):
    def test_archive_retains_evidence_and_skips_recent_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / 'temp/tool_logs'
            logs.mkdir(parents=True)
            old = logs / 'old.log'
            old.write_bytes(b'complete evidence\n' * 100)
            os.utime(old, (1, 1))
            recent = logs / 'recent.log'
            recent.write_text('active output')
            link = logs / 'link.log'
            link.symlink_to(recent)
            result = archive_logs(root, time.time() - 86400)
            self.assertEqual(result['removed_local_copies'], 1)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(link.is_symlink())
            with tarfile.open(root / result['path']) as archive:
                stream = archive.extractfile('temp/tool_logs/old.log')
                self.assertIsNotNone(stream)
                self.assertEqual(stream.read(), b'complete evidence\n' * 100)
            self.assertEqual(archive_logs(root, time.time() - 86400)['files'], 0)

    def test_failed_archive_verification_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / 'temp/gates'
            logs.mkdir(parents=True)
            source = logs / 'proof.json'
            source.write_text('{"status":"PASS"}')
            os.utime(source, (1, 1))
            with patch('scripts.stabilize_workspace.verify_archive', side_effect=ValueError('corrupt archive')):
                with self.assertRaises(ValueError):
                    archive_logs(root, time.time() - 86400)
            self.assertEqual(source.read_text(), '{"status":"PASS"}')

    def test_toml_update_preserves_routing_and_is_idempotent(self) -> None:
        original = ('model = "existing-model"\nmodel_auto_compact_token_limit = 128000\n'
                    'tool_output_token_limit = 1024\n[agents]\nmax_threads = 1\n'
                    '[mcp_servers.mempalace]\ncommand = "existing-command"\nenabled = true\n')
        result = update_toml(original)
        data = tomllib.loads(result)
        self.assertEqual(data['model'], 'existing-model')
        self.assertEqual(data['tool_output_token_limit'], 1024)
        self.assertEqual(data['agents']['max_threads'], 1)
        self.assertFalse(data['mcp_servers']['mempalace']['enabled'])
        self.assertEqual(data['mcp_servers']['mempalace']['command'], 'existing-command')
        self.assertEqual(data['model_auto_compact_token_limit'], 160000)
        self.assertEqual(update_toml(result), result)

    def test_role_path_is_compatible_with_installed_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            role = root / 'worker.toml'
            role.write_text('sandbox_mode = "read-only"\n')
            original = '[agents.token_worker]\nconfig_file = "worker.toml"\n'
            result = update_toml(original, root)
            self.assertEqual(tomllib.loads(result)['agents']['token_worker']['config_file'], str(role))
            self.assertEqual(update_toml(result, root), result)

    def test_missing_role_does_not_silently_change_routing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                update_toml('[agents.token_worker]\nconfig_file = "missing.toml"\n', Path(directory))

    def test_unknown_host_is_not_successful_memory_verification(self) -> None:
        with self.assertRaises(ValidationError):
            StabilizationReport(timestamp_utc='2026-11-08T00:00:00Z', workspace='/workspace',
                bsl_diagnostics_trigger='onSave', mcp_active_servers=['filesystem'],
                compiled_epf_sha256='a' * 64, handover_synchronized=True,
                git_untracked_count_post=0, extension_host_rss_mb=0, reclaimed_memory_mb=0,
                remediation_status='SUCCESS_CONVERGED', details={'git_status_count': 0,
                'gates': '8/8 PASS', 'configuration_checks': {'verified': True},
                'extension_host_observed': False})

    def test_partial_report_preserves_out_of_bounds_observation(self) -> None:
        report = StabilizationReport(timestamp_utc='2026-11-08T00:00:00Z', workspace='/workspace',
            bsl_diagnostics_trigger='onSave', mcp_active_servers=['filesystem', 'mempalace'],
            compiled_epf_sha256='a' * 64, handover_synchronized=True,
            git_untracked_count_post=827, extension_host_rss_mb=2000, reclaimed_memory_mb=0,
            remediation_status='PARTIAL_RETRY_REQUIRED', details={'gates': 'UNVERIFIED'})
        self.assertEqual(report.extension_host_rss_mb, 2000)
        self.assertEqual(report.git_untracked_count_post, 827)


if __name__ == '__main__':
    unittest.main()
