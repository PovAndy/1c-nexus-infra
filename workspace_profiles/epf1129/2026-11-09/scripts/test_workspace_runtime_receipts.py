"""Keep volatile receipts refreshable and static contracts fail-closed."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from scripts.gate_check import run_ledger
from scripts.mcp_host_gateway_launcher import replace_host, pin_rsv_target_url
from scripts.stabilize_workspace import digest
from scripts.workspace_runtime_receipts import validate_receipt, verify_runtime_contracts
from scripts.finalize_workspace_environment import identical_original


class RuntimeReceiptTests(unittest.TestCase):
    def test_successful_gate_receipt_can_be_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build').mkdir()
            epf = root / 'build/compiled.epf'
            epf.write_bytes(b'fixed')
            ledger = root / 'GATES.md'
            ledger.write_text('## G1\nCHECK: python3 -c "print(123)"\nEXPECT: exitcode=0; regex=123\nEVIDENCE: temp/gates/g1.json\n')
            self.assertEqual(run_ledger(ledger, root=root, reverify=True), 0)
            proof = root / 'temp/gates/g1.json'
            hashes = {'temp/gates/g1.json': digest(proof)}
            data = json.loads(proof.read_text())
            data['verification_note'] = 'monotonic refresh'
            proof.write_text(json.dumps(data))
            self.assertEqual(verify_runtime_contracts(root, hashes, digest(epf))['validated_volatile_updates'], ['temp/gates/g1.json'])
            data['status'] = 'FAIL'
            proof.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                verify_runtime_contracts(root, hashes, digest(epf))

    def test_static_change_is_not_an_accepted_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build').mkdir()
            epf = root / 'build/compiled.epf'
            epf.write_bytes(b'fixed')
            source = root / 'module.bsl'
            source.write_text('original')
            hashes = {'module.bsl': digest(source)}
            source.write_text('changed')
            with self.assertRaises(ValueError):
                verify_runtime_contracts(root, hashes, digest(epf))

    def test_dynamic_rules_can_change_but_static_prefix_cannot(self) -> None:
        prefix = (Path(__file__).resolve().parents[1] / 'AGENTS.md').read_bytes().partition(b'<!-- PROMPT_CACHE_BOUNDARY -->')[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build').mkdir()
            epf = root / 'build/compiled.epf'
            epf.write_bytes(b'fixed')
            rules = root / 'AGENTS.md'
            rules.write_bytes(prefix + b'<!-- PROMPT_CACHE_BOUNDARY -->\nold runtime')
            hashes = {'AGENTS.md': digest(rules)}
            rules.write_bytes(prefix + b'<!-- PROMPT_CACHE_BOUNDARY -->\nnew runtime')
            result = verify_runtime_contracts(root, hashes, digest(epf))
            self.assertEqual(result['validated_dynamic_rule_updates'], ['AGENTS.md'])
            rules.write_bytes(b'X' + rules.read_bytes()[1:])
            with self.assertRaises(ValueError):
                verify_runtime_contracts(root, hashes, digest(epf))

    def test_stale_deployment_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'temp').mkdir()
            p = root / 'temp/deployment_report.json'
            p.write_text(json.dumps({'schema_version': '1.0', 'status': 'PASS', 'error': None,
                'source_fresh': True, 'profile': 'local', 'build_sha256': 'a'*64,
                'target_sha256': 'a'*64, 'checked_at': time.time()-10}))
            validate_receipt(root, 'temp/deployment_report.json', 'a'*64)
            with self.assertRaises(ValueError):
                validate_receipt(root, 'temp/deployment_report.json', 'a'*64, time.time_ns())

    def test_gateway_replacement_preserves_auth_path_and_query(self) -> None:
        value = replace_host('http://u:p@172.24.96.1:8080/base02/hs/rsvdata/mcp?x=1', '192.168.32.1')
        self.assertEqual(value, 'http://u:p@192.168.32.1:8080/base02/hs/rsvdata/mcp?x=1')
        with self.assertRaises(ValueError):
            replace_host('https://example.com/base02', '192.168.32.1')

    def test_unique_copy_is_not_a_disposable_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'config.json'
            duplicate = root / 'config — копия.json'
            original.write_text('same')
            duplicate.write_text('same')
            self.assertEqual(identical_original(duplicate), original)
            duplicate.write_text('unique work')
            self.assertIsNone(identical_original(duplicate))

    def test_target_specific_url_cannot_reintroduce_stale_gateway(self) -> None:
        env = {'RSVDATA_TARGET': 'BASE02', 'RSVDATA_MCP_URL': 'http://192.168.32.1/base02/hs/rsvdata/mcp',
               'RSVDATA_MCP_URL_BASE02': 'http://172.24.96.1/base02/hs/rsvdata/mcp'}
        pin_rsv_target_url(env, '192.168.32.1')
        self.assertEqual(env['RSVDATA_MCP_URL_BASE02'], 'http://192.168.32.1/base02/hs/rsvdata/mcp')
        env['RSVDATA_MCP_URL_BASE02'] = 'http://172.24.96.1/postgres2/hs/rsvdata/mcp'
        with self.assertRaises(ValueError):
            pin_rsv_target_url(env, '192.168.32.1')


if __name__ == '__main__':
    unittest.main()
