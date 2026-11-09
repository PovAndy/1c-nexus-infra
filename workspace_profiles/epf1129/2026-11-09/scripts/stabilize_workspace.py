#!/usr/bin/env python3
"""Apply reversible workspace settings; archive evidence before removing old copies."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import signal
import stat
import subprocess
import tarfile
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(value, dict):
        raise ValueError(f'Expected JSON object: {path.name}')
    return value


def update_toml(text: str, role_base: Path | None = None) -> str:
    original = tomllib.loads(text)
    head, separator, tail = text.partition('\n[')
    for key, value in (('model_auto_compact_token_limit', '160000'),
                       ('model_auto_compact_token_limit_scope', '"body_after_prefix"')):
        pattern = rf'(?m)^{key}\s*=.*$'
        head = re.sub(pattern, key + ' = ' + value, head) if re.search(pattern, head) else head + '\n' + key + ' = ' + value
    result = head + separator + tail
    for name in ('mempalace', 'sequential-thinking'):
        pattern = rf'(?ms)(^\[mcp_servers\.(?:"{name}"|{name})\][^\n]*\n)(.*?)(?=^\[|\Z)'
        found = re.search(pattern, result)
        if found:
            body = found.group(2)
            body = re.sub(r'(?m)^enabled\s*=.*$', 'enabled = false', body) if re.search(r'(?m)^enabled\s*=', body) else 'enabled = false\n' + body
            result = result[:found.start(2)] + body + result[found.end(2):]
        else:
            result += f'\n[mcp_servers."{name}"]\nenabled = false\n'
    if role_base is not None:
        # Codex 0.139 cannot always deserialize relative role paths after
        # workspace config layers are merged. Keep the existing role itself.
        pattern = r'(?ms)(^\[agents\.(?:"token_worker"|token_worker)\][^\n]*\n)(.*?)(?=^\[|\Z)'
        found = re.search(pattern, result)
        if found:
            body = found.group(2)
            declaration = re.search(r'(?m)^config_file\s*=.*$', body)
            if declaration:
                role = tomllib.loads(body)['config_file']
                absolute = (role_base / role).resolve()
                if not absolute.is_file():
                    raise ValueError('Existing token worker role file is missing')
                replacement = 'config_file = ' + json.dumps(str(absolute))
                body = body[:declaration.start()] + replacement + body[declaration.end():]
                result = result[:found.start(2)] + body + result[found.end(2):]
    parsed = tomllib.loads(result)
    for key in ('model', 'model_provider', 'tool_output_token_limit'):
        if parsed.get(key) != original.get(key):
            raise ValueError(f'Unexpected change to {key}')
    return result


def configure(root: Path, backup: Path) -> list[dict[str, str]]:
    schema = read_json(root / 'temp/audit/bsl-configuration-schema.json')
    parameters = read_json(root / 'temp/audit/bsl-parameters-schema.json')
    bsl = {'$schema': 'https://1c-syntax.github.io/bsl-language-server/configuration/schema.json',
           'language': 'ru', 'diagnostics': {'computeTrigger': 'onSave', 'skipSupport': 'withSupport',
           'parameters': {'CognitiveComplexity': {'complexityThreshold': 25},
                          'CyclomaticComplexity': {'complexityThreshold': 20},
                          'LineLength': {'maxLineLength': 140}}}}
    from jsonschema import Draft7Validator
    diagnostic_properties = schema['properties']['diagnostics']['properties']
    for key in ('computeTrigger', 'skipSupport'):
        Draft7Validator(diagnostic_properties[key]).validate(bsl['diagnostics'][key])
    for key, value in bsl['diagnostics']['parameters'].items():
        definition = parameters['definitions'][key]
        if not set(value).issubset(definition['properties']):
            raise ValueError('Unsupported BSL parameter')
        Draft7Validator(definition).validate(value)
    pending: dict[Path, bytes] = {root / '.bsl-language-server.json': encoded(bsl)}
    for workspace, configuration in ((root, '.bsl-language-server.json'),
                                     (root.parent, 'epf1129/.bsl-language-server.json')):
        path = workspace / '.vscode/settings.json'
        settings = read_json(path)
        for key, suffix in (('files.watcherExclude', '/**'), ('search.exclude', '')):
            rules = settings.setdefault(key, {})
            for folder in ('.git', '.venv*', 'node_modules', 'temp', 'archive', 'build', '__pycache__', '.code-index', 'logs'):
                rules['**/' + folder + suffix] = True
            rules['**/*.epf'] = True
        settings.update({'files.autoSave': 'off', 'git.autorefresh': False,
                         'C_Cpp.intelliSenseEngine': 'disabled',
                         'language-1c-bsl.languageServerEnabled': True,
                         'language-1c-bsl.languageServerConfiguration': configuration,
                         'language-1c-bsl.trace.server': 'off'})
        pending[path] = encoded(settings)
        path = workspace / '.vscode/mcp.json'
        old = read_json(path)
        servers = old.get('servers', old.get('mcpServers', {}))
        server = dict(servers.get('filesystem', {'command': 'npx', 'args': ['--no-install', '@modelcontextprotocol/server-filesystem', str(root)]}))
        server['type'] = 'stdio'
        env = dict(server.get('env', {}))
        options = re.sub(r'(?:^|\s)--max-old-space-size(?:=|\s+)\d+', '', env.get('NODE_OPTIONS', '')).strip()
        env['NODE_OPTIONS'] = (options + ' --max-old-space-size=512').strip()
        server['env'] = env
        mcp = {k: v for k, v in old.items() if k not in ('servers', 'mcpServers')}
        mcp['servers'] = {'filesystem': server}
        pending[path] = encoded(mcp)
        path = workspace / '.codex/config.toml'
        pending[path] = update_toml(path.read_text(), path.parent).encode()
    path = root / '.codex/context_governance.json'
    policy = read_json(path)
    policy['growth_compaction_tokens'] = 160000
    pending[path] = encoded(policy)
    for name in ('.clinerules', '.cursorrules', 'AGENTS.md', 'system_prompt.md'):
        path = root / name
        data = path.read_bytes()
        marker = b'<!-- PROMPT_CACHE_BOUNDARY -->'
        prefix, boundary, tail = data.partition(marker)
        if not boundary:
            raise ValueError('Missing immutable-prefix boundary')
        tail = re.sub(rb'\b(?:32000|64000|128000) growth tokens', b'160000 growth tokens', tail)
        pending[path] = prefix + boundary + tail
    changes = []
    for path, data in pending.items():
        original = path.read_bytes() if path.exists() else None
        if original == data:
            continue
        relative = path.relative_to(root.parent)
        destination = backup / relative
        if original is not None:
            atomic(destination, original)
            destination.chmod(0o600)
        atomic(path, data)
        changes.append({'path': str(relative), 'before_sha256': hashlib.sha256(original).hexdigest() if original is not None else 'ABSENT', 'after_sha256': digest(path)})
    return changes


def verify_archive(path: Path, expected: dict[str, dict[str, Any]]) -> None:
    observed = set()
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            if member.name == 'MANIFEST.json':
                continue
            if member.name not in expected or not member.isfile():
                raise ValueError('Unexpected archive member')
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError('Unreadable archive member')
            hasher = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(block)
            if hasher.hexdigest() != expected[member.name]['sha256']:
                raise ValueError('Archive checksum mismatch')
            observed.add(member.name)
    if observed != set(expected):
        raise ValueError('Archive is incomplete')


def archive_logs(root: Path, cutoff: float) -> dict[str, Any]:
    files = sorted(p for name in ('temp/tool_logs', 'temp/gates') for p in (root / name).rglob('*')
                   if p.is_file() and not p.is_symlink() and p.stat().st_mtime < cutoff)
    if not files:
        return {'files': 0, 'removed_local_copies': 0}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = root / 'archive' / ('cleanup_' + stamp + '.tar.gz')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    manifest: dict[str, dict[str, Any]] = {}
    with temporary.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        with tarfile.open(fileobj=output, mode='w:gz', compresslevel=1) as archive:
            for path in files:
                before = path.stat()
                name = path.relative_to(root).as_posix()
                manifest[name] = {'sha256': digest(path), 'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns}
                archive.add(path, arcname=name, recursive=False)
                if (path.stat().st_size, path.stat().st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                    raise ValueError('Log changed during archive creation; originals retained')
            data = encoded(manifest)
            entry = tarfile.TarInfo('MANIFEST.json')
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        output.flush()
        os.fsync(output.fileno())
    verify_archive(temporary, manifest)
    temporary.replace(target)
    removed = 0
    for path in files:
        entry = manifest[path.relative_to(root).as_posix()]
        if path.is_symlink():
            continue
        if path.stat().st_mtime_ns == entry['mtime_ns'] and digest(path) == entry['sha256']:
            path.unlink()
            removed += 1
    return {'path': str(target.relative_to(root)), 'sha256': digest(target), 'files': len(files),
            'original_bytes': sum(item['bytes'] for item in manifest.values()), 'archive_bytes': target.stat().st_size,
            'removed_local_copies': removed, 'verified_all_member_sha256': True}


def processes() -> list[dict[str, Any]]:
    rows = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            raw = (path / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            command = (path / 'cmdline').read_bytes().decode(errors='replace')
            kind = next((label for label, match in (('extension-host', 'extensionHost'), ('mempalace', 'mempalace'),
                        ('sequential-thinking', 'server-sequential-thinking'), ('filesystem', 'server-filesystem')) if match in command), None)
            if kind:
                rows.append({'pid': int(path.name), 'ppid': int(fields[1]), 'kind': kind,
                             'rss_mb': int(fields[21]) * os.sysconf('SC_PAGE_SIZE') / 1024**2,
                             'start_ticks': fields[19], 'cwd': str((path / 'cwd').resolve())})
        except (OSError, ValueError, IndexError):
            continue
    return rows


def orphan_cleanup(root: Path) -> list[int]:
    terminated = []
    for row in processes():
        if row['kind'] not in ('mempalace', 'sequential-thinking') or row['ppid'] != 1:
            continue
        if not Path(row['cwd']).is_relative_to(root):
            continue
        current = next((item for item in processes() if item['pid'] == row['pid']), None)
        if current and current['start_ticks'] == row['start_ticks'] and current['ppid'] == 1:
            os.kill(row['pid'], signal.SIGTERM)
            terminated.append(row['pid'])
    return terminated


class StabilizationReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    timestamp_utc: str
    workspace: str
    bsl_diagnostics_trigger: Literal['onSave']
    mcp_active_servers: list[str]
    compiled_epf_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    handover_synchronized: bool
    git_untracked_count_post: int = Field(ge=0)
    extension_host_rss_mb: float = Field(ge=0)
    reclaimed_memory_mb: float = Field(ge=0)
    remediation_status: Literal['SUCCESS_CONVERGED', 'PARTIAL_RETRY_REQUIRED']
    details: dict[str, Any]

    @model_validator(mode='after')
    def truthful_success(self) -> StabilizationReport:
        if self.remediation_status == 'SUCCESS_CONVERGED':
            if self.git_untracked_count_post > 50 or self.extension_host_rss_mb > 512 or not self.handover_synchronized:
                raise ValueError('Cannot report convergence outside requested bounds')
            if self.details.get('git_status_count', 11) > 10 or self.details.get('gates') != '8/8 PASS':
                raise ValueError('Convergence requires clean status and verified gates')
            if not self.details.get('configuration_checks') or not all(self.details['configuration_checks'].values()):
                raise ValueError('Convergence requires current configuration verification')
            if not self.details.get('extension_host_observed'):
                raise ValueError('An unobserved Extension Host is not proof of low memory use')
            if set(self.mcp_active_servers) != {'filesystem'}:
                raise ValueError('Additional observed MCP daemons prevent convergence')
        return self


def configuration_checks(root: Path) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    bsl = read_json(root / '.bsl-language-server.json')
    checks['bsl_on_save'] = bsl.get('diagnostics', {}).get('computeTrigger') == 'onSave'
    for label, workspace in (('project', root), ('root', root.parent)):
        settings = read_json(workspace / '.vscode/settings.json')
        watch = settings.get('files.watcherExclude', {})
        checks[label + '_watchers'] = all(watch.get('**/' + name + '/**') is True
            for name in ('.git', '.venv*', 'node_modules', 'temp', 'archive', 'build', '__pycache__', '.code-index', 'logs'))
        checks[label + '_bsl_trace_off'] = settings.get('language-1c-bsl.trace.server') == 'off'
        checks[label + '_git_autorefresh_off'] = settings.get('git.autorefresh') is False
        configuration = settings.get('language-1c-bsl.languageServerConfiguration')
        checks[label + '_bsl_config_path'] = isinstance(configuration, str) and (workspace / configuration).resolve() == (root / '.bsl-language-server.json').resolve()
        mcp = read_json(workspace / '.vscode/mcp.json')
        checks[label + '_filesystem_only'] = 'mcpServers' not in mcp and set(mcp.get('servers', {})) == {'filesystem'}
        node_options = mcp.get('servers', {}).get('filesystem', {}).get('env', {}).get('NODE_OPTIONS', '')
        checks[label + '_filesystem_heap'] = '--max-old-space-size=512' in node_options.split()
        config = tomllib.loads((workspace / '.codex/config.toml').read_text())
        checks[label + '_compaction'] = config.get('model_auto_compact_token_limit') == 160000 and config.get('model_auto_compact_token_limit_scope') == 'body_after_prefix'
        checks[label + '_redundant_mcp_disabled'] = all(config.get('mcp_servers', {}).get(name, {}).get('enabled') is False for name in ('mempalace', 'sequential-thinking'))
        role = config.get('agents', {}).get('token_worker', {}).get('config_file')
        checks[label + '_existing_role_path'] = isinstance(role, str) and Path(role).is_absolute() and Path(role).is_file()
    policy = read_json(root / '.codex/context_governance.json')
    checks['policy_compaction'] = policy.get('growth_compaction_tokens') == 160000
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    audit = ROOT / 'temp/audit'
    audit.mkdir(parents=True, exist_ok=True)
    state_path = audit / 'STABILIZATION_ACTIONS.json'
    actions = read_json(state_path)
    if args.archive and not args.apply:
        parser.error('--archive requires --apply')
    if args.apply:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        changes = configure(ROOT, audit / ('backups_' + stamp))
        actions['configuration_changes'] = actions.get('configuration_changes', []) + changes
        atomic(state_path, encoded(actions))
        if args.archive:
            actions['archive'] = archive_logs(ROOT, time.time() - 86400)
            atomic(state_path, encoded(actions))
        actions['terminated_orphans'] = orphan_cleanup(ROOT)
        atomic(state_path, encoded(actions))
    from scripts.reconcile_reality import parse_handover
    from scripts.session_breaker import verify_gates
    compiled = ROOT / 'build/compiled.epf'
    actual = digest(compiled)
    handover_matches = parse_handover(ROOT / 'docs/ACTIVE_HANDOVER.md').compiled_sha256 == actual
    status = subprocess.check_output(['git', 'status', '--porcelain=v1', '-z'], cwd=ROOT).split(b'\0')
    rows = processes()
    maximum = max((row['rss_mb'] for row in rows if row['kind'] == 'extension-host'), default=0)
    checks = configuration_checks(ROOT)
    try:
        gates = verify_gates(ROOT, compiled)
    except (OSError, ValueError, KeyError):
        gates = 'UNVERIFIED'
    details = {'actions': actions, 'git_status_count': sum(bool(item) for item in status), 'gates': gates,
               'processes': rows, 'configured_vscode_servers': ['filesystem'],
               'configuration_checks': checks,
               'extension_host_observed': any(row['kind'] == 'extension-host' for row in rows),
               'heap_limit_scope': 'Filesystem MCP only; existing IDE Extension Host unchanged',
               'manual_reload_required': True, 'kernel_caches_dropped': False,
               'memory_reclamation_measurement': 'Unmeasured; zero is the conservative credited amount, not a measured result',
               'limitations': ['Heap limit is not an RSS limit', 'No global CPU or GC latency guarantee',
                               'Git changes outside authorized temporary logs are preserved',
                               'Archived gate evidence must be regenerated before verified handover']}
    untracked = sum(item.startswith(b'?? ') for item in status)
    active = sorted({row['kind'] for row in rows if row['kind'] != 'extension-host'})
    converged = (maximum <= 512 and untracked <= 50 and details['git_status_count'] <= 10
                 and handover_matches and gates == '8/8 PASS' and all(checks.values())
                 and details['extension_host_observed'] and set(active) == {'filesystem'})
    trigger = read_json(ROOT / '.bsl-language-server.json').get('diagnostics', {}).get('computeTrigger')
    report = StabilizationReport(timestamp_utc=datetime.now(timezone.utc).isoformat(), workspace=str(ROOT),
             bsl_diagnostics_trigger=trigger, mcp_active_servers=active,
             compiled_epf_sha256=actual, handover_synchronized=handover_matches, git_untracked_count_post=untracked,
             extension_host_rss_mb=round(maximum, 2), reclaimed_memory_mb=0,
             remediation_status='SUCCESS_CONVERGED' if converged else 'PARTIAL_RETRY_REQUIRED', details=details)
    atomic(audit / 'STABILIZATION_REPORT.json', encoded(report.model_dump()))
    print(f'{report.remediation_status}: RSS={maximum:.1f}MiB; untracked={untracked}; gates={gates}; handover={handover_matches}')
    return 0 if converged else 2


if __name__ == '__main__':
    raise SystemExit(main())
