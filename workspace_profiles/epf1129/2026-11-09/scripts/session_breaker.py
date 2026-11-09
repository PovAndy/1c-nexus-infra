"""Fail-closed compact handover from current Git, EPF and gate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

MAX_HANDOVER_BYTES = 1499


@dataclass(frozen=True)
class TaskHandoverPayload:
    git_branch: str
    git_head_sha: str
    epf_sha256: str
    gates_status: Literal['8/8 PASS']
    deploy_target: Literal['local', 'remote']
    next_actionable_step: str

    def __post_init__(self) -> None:
        if not isinstance(self.git_branch, str) or not self.git_branch or len(self.git_branch) > 128:
            raise ValueError('Invalid git branch')
        if any(not character.isprintable() for character in self.git_branch):
            raise ValueError('Control characters in git branch')
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', self.git_head_sha):
            raise ValueError('Invalid Git HEAD')
        if not re.fullmatch(r'[0-9a-f]{64}', self.epf_sha256):
            raise ValueError('Invalid EPF SHA-256')
        if self.gates_status != '8/8 PASS' or self.deploy_target not in ('local', 'remote'):
            raise ValueError('Unverified gate or deployment status')
        action = self.next_actionable_step
        if not isinstance(action, str) or not action.strip() or len(action) > 500:
            raise ValueError('Next action must contain 1..500 characters')
        if any(not character.isprintable() for character in action):
            raise ValueError('Control characters in next action')


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(['git', '-C', str(root), *arguments], capture_output=True, text=True, timeout=10, check=True)
    return result.stdout.strip()


def deployment(root: Path) -> Literal['local', 'remote']:
    configured = os.getenv('NEXUS_DEPLOY_TARGET', '').strip()
    if not configured:
        path = root / '.codex/deployment.json'
        configured = json.loads(path.read_text()).get('target', '') if path.is_file() else 'remote'
    if configured not in ('local', 'remote'):
        raise ValueError('Unknown deployment profile')
    return configured


def verify_gates(root: Path, compiled: Path) -> str:
    ledger = root / 'GATES.md'
    text = ledger.read_text(encoding='utf-8')
    sections = re.split(r'^## ([A-Za-z0-9][A-Za-z0-9._-]*)\s*$', text, flags=re.MULTILINE)
    gates = []
    for index in range(1, len(sections), 2):
        body = sections[index + 1]
        fields = dict(re.findall(r'^(CHECK|EXPECT|EVIDENCE):\s*(.+)$', body, re.MULTILINE))
        if fields:
            if set(fields) != {'CHECK', 'EXPECT', 'EVIDENCE'}:
                raise ValueError('Incomplete gate definition')
            gates.append((sections[index], fields))
    if len(gates) != 8 or len({name for name, _ in gates}) != 8:
        raise ValueError('Exactly eight distinct gates required')
    newest = max(ledger.stat().st_mtime_ns, compiled.stat().st_mtime_ns)
    sources = [root / name for name in git(root, 'ls-files', '-z').split('\0') if name]
    sources.extend((root / 'scripts').glob('*.py'))
    sources.extend(root / name for name in ('.env.openrouter.local', '.codex/deployment.json'))
    for source in sources:
        if any(part.casefold() == 'archive' for part in source.relative_to(root).parts):
            continue
        if source.is_file() and (source.suffix in ('.py', '.bsl', '.xml') or source.name in ('.clinerules', '.cursorrules', 'AGENTS.md', 'system_prompt.md', '.env.openrouter.local', 'deployment.json')):
            newest = max(newest, source.stat().st_mtime_ns)
    for name, fields in gates:
        relative = Path(fields['EVIDENCE'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe evidence path')
        evidence_path = (root / relative).resolve()
        if not evidence_path.is_relative_to((root / 'temp/gates').resolve()):
            raise ValueError('Evidence outside temp/gates')
        evidence = json.loads(evidence_path.read_text())
        expected_hash = hashlib.sha256(fields['CHECK'].encode()).hexdigest()
        if evidence.get('gate_id') != name or evidence.get('command_sha256') != expected_hash:
            raise ValueError('Gate command or identity changed')
        if evidence.get('status') != 'PASS' or evidence.get('returncode') != 0 or evidence.get('regex_matched') is not True:
            raise ValueError('Gate did not pass')
        if evidence_path.stat().st_mtime_ns < newest:
            raise ValueError('Stale gate evidence')
        for argument in shlex.split(fields['CHECK']):
            source = root / argument
            if argument.endswith('.py') and source.is_file() and source.stat().st_mtime_ns > evidence_path.stat().st_mtime_ns:
                raise ValueError('Gate implementation changed')
    return '8/8 PASS'


def compile_payload(root: Path, action: str) -> TaskHandoverPayload:
    compiled = root / 'build/compiled.epf'
    head = git(root, 'rev-parse', 'HEAD')
    before = compiled.stat()
    sha = digest(compiled)
    gates = verify_gates(root, compiled)
    after = compiled.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Compiled EPF changed while reading')
    if head != git(root, 'rev-parse', 'HEAD'):
        raise ValueError('Git HEAD changed while reading')
    return TaskHandoverPayload(git(root, 'branch', '--show-current') or '(detached)', head, sha, gates, deployment(root), action)


def write_handover(root: Path, payload: TaskHandoverPayload) -> Path:
    encoded = json.dumps(asdict(payload), ensure_ascii=False, separators=(',', ':'))
    text = '# TASK HANDOVER\n\nVerified workspace: ' + str(root) + '\n\n```json\n' + encoded + '\n```\n'
    data = text.encode('utf-8')
    if len(data) > MAX_HANDOVER_BYTES:
        raise ValueError('Handover exceeds the conservative UTF-8 byte budget')
    target = root / 'temp/TASK_HANDOVER.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.md.tmp')
    with temporary.open('wb') as stream:
        os.chmod(temporary, 0o600)
        stream.write(data)
    temporary.replace(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(os.environ.get('NEXUS_WORKSPACE_ROOT', Path(__file__).resolve().parents[1])))
    parser.add_argument('--next-step', default=os.environ.get('NEXUS_NEXT_ACTION', ''))
    args = parser.parse_args()
    root = args.workspace.resolve()
    action_path = root / 'temp/zcl_next_step.txt'
    try:
        action = args.next_step or action_path.read_text(encoding='utf-8').strip()
        payload = compile_payload(root, action)
        path = write_handover(root, payload)
        if args.next_step:
            action_path.write_text(action + '\n', encoding='utf-8')
            os.chmod(action_path, 0o600)
        print('HANDOVER_PASS ' + str(path) + ' bytes=' + str(path.stat().st_size))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Delete an older success handover when current verification fails.
        (root / 'temp/TASK_HANDOVER.md').unlink(missing_ok=True)
        print('HANDOVER_STOP ' + type(exc).__name__ + ': ' + str(exc).splitlines()[0][:160])
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
