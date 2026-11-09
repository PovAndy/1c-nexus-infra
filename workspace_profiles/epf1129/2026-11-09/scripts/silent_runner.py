"""File-first command execution: full private log, exactly three output lines."""

import os
import sys
import time

try:
    # CPython 3.12 ships HACL SHA-256; avoid initializing unused OpenSSL hashes.
    from _sha2 import sha256
except ImportError:
    from hashlib import sha256

SUMMARY_CHARS = 120
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def last_summary(path: str) -> str:
    """Find the last nonblank physical line without retaining the whole log."""
    import codecs

    with open(path, 'rb') as stream:
        position = stream.seek(0, os.SEEK_END)
        while position:
            line_end: int | None = None
            line_start = 0
            scan = position
            while scan:
                start = max(0, scan - 8192)
                stream.seek(start)
                block = stream.read(scan - start)
                limit = len(block)
                if line_end is None:
                    limit = len(block.rstrip(b' \t\r\n\v\f'))
                    if not limit:
                        scan = start
                        continue
                    line_end = start + limit
                separator = max(block.rfind(b'\n', 0, limit), block.rfind(b'\r', 0, limit))
                if separator >= 0:
                    line_start = start + separator + 1
                    break
                scan = start
            if line_end is None:
                return '(empty)'
            stream.seek(line_start)
            remaining = line_end - line_start
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            output: list[str] = []
            while remaining:
                block = stream.read(min(4096, remaining))
                if not block:
                    raise OSError('Log changed while reading')
                remaining -= len(block)
                value = decoder.decode(block, final=remaining == 0)
                for char in value:
                    if not char.isprintable() or (not output and char.isspace()):
                        continue
                    if len(output) < SUMMARY_CHARS:
                        output.append(char)
                    if len(output) == SUMMARY_CHARS and not char.isspace():
                        return ''.join(output)
            clean = ''.join(output).rstrip()
            if clean:
                return clean
            position = max(0, line_start - 1)
    return '(empty)'


def run(argv: list[str], *, workspace: str = ROOT) -> tuple[int, int, str, str]:
    """Execute argv directly; shell interpretation is an explicit CLI opt-in."""
    directory = os.path.join(workspace, 'temp', 'tool_logs')
    os.makedirs(directory, mode=0o700, exist_ok=True)
    digest = sha256(b'\x00'.join(os.fsencode(value) for value in argv)).hexdigest()[:16]
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    filename = f'{stamp}_{time.time_ns():019d}_{digest}.log'
    path = os.path.join(directory, filename)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        if not argv:
            os.write(descriptor, b'Missing command\n')
            code = 64
        else:
            try:
                if hasattr(os, 'posix_spawnp'):
                    actions = [(os.POSIX_SPAWN_DUP2, descriptor, 1), (os.POSIX_SPAWN_DUP2, descriptor, 2)]
                    pid = os.posix_spawnp(argv[0], argv, os.environ, file_actions=actions)
                    _, status = os.waitpid(pid, 0)
                    code = os.waitstatus_to_exitcode(status)
                else:
                    import subprocess

                    code = subprocess.run(argv, stdout=descriptor, stderr=descriptor, check=False).returncode
                if code < 0:
                    code = 128 - code
            except OSError as exc:
                os.write(descriptor, ('Command startup failed: ' + type(exc).__name__ + '\n').encode())
                code = 127
    finally:
        os.close(descriptor)
    size = os.stat(path).st_size
    return code, size, last_summary(path), 'temp/tool_logs/' + filename


def main(argv: list[str] | None = None) -> int:
    command = list(sys.argv[1:] if argv is None else argv)
    expected: str | None = None
    if command[:1] == ['--expect-regex']:
        if len(command) < 3:
            command = []
        else:
            expected = command[1]
            command = command[2:]
    if command[:1] == ['--']:
        command.pop(0)
    elif command[:1] == ['--shell']:
        command = [os.environ.get('SHELL', '/bin/sh'), '-c', command[1]] if len(command) == 2 else []
    if command and command[0] in ('python3', 'python'):
        command[0] = sys.executable
    try:
        code, size, summary, relative = run(command)
    except (OSError, ValueError) as exc:
        # No traceback or arbitrary exception text may reach the model context.
        code, size, summary, relative = 74, 0, type(exc).__name__, '(unavailable)'
    verified = code == 0
    if verified and expected is not None:
        import re

        try:
            pattern = re.compile(expected)
            with open(os.path.join(ROOT, relative), encoding='utf-8', errors='replace') as stream:
                verified = any(pattern.search(line) is not None for line in stream)
        except (OSError, re.error):
            verified = False
    label = 'PASS' if verified else 'FAIL'
    sys.stdout.write(f'[{label}] Exit: {code} | Output bytes: {size}\nSummary: {summary}\nLog: {relative}\n')
    return code if code else (0 if verified else 2)


if __name__ == '__main__':
    raise SystemExit(main())
