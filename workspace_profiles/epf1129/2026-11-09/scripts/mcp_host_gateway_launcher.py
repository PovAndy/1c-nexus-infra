#!/usr/bin/env python3
"""Resolve the verified WSL Windows peer before starting an existing MCP server."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]


def default_gateway() -> str:
    routes = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route', 'show', 'default'], text=True, timeout=3))
    gateways = {route['gateway'] for route in routes if route.get('gateway')}
    if len(gateways) != 1:
        raise ValueError('Default route is absent or ambiguous')
    gateway = gateways.pop()
    if not ipaddress.IPv4Address(gateway).is_private:
        raise ValueError('Expected a private Windows peer address')
    return gateway


def windows_gateway() -> str:
    gateway = default_gateway()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    cache_path = ROOT / 'temp/audit/HOST_GATEWAY_CACHE.json'
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    if cache.get('gateway') == gateway and cache.get('linux_boot_id') == boot and cache.get('verified_windows_host') is True:
        return gateway
    command = ['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe', '-NoProfile', '-NonInteractive',
               '-Command', 'Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,InterfaceAlias | ConvertTo-Json -Compress']
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=True)
    records = json.loads(completed.stdout.decode('utf-8-sig'))
    records = [records] if isinstance(records, dict) else records
    if not any(row.get('IPAddress') == gateway and 'WSL' in row.get('InterfaceAlias', '').upper() for row in records):
        raise ValueError('Default gateway is not a verified Windows WSL adapter; endpoints retained')
    from scripts.stabilize_workspace import atomic, encoded
    atomic(cache_path, encoded({'gateway': gateway, 'linux_boot_id': boot, 'verified_windows_host': True, 'verified_at': time.time()}))
    return gateway


def replace_host(url: str, gateway: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Expected a configured HTTP endpoint')
    try:
        private = ipaddress.ip_address(parsed.hostname).is_private
    except ValueError:
        private = parsed.hostname == 'localhost'
    if not private:
        raise ValueError('Refusing to redirect a non-local endpoint')
    prefix = parsed.netloc.rsplit('@', 1)[0] + '@' if '@' in parsed.netloc else ''
    netloc = prefix + gateway + (':' + str(parsed.port) if parsed.port is not None else '')
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def pin_rsv_target_url(environment: dict[str, str], gateway: str) -> None:
    """RSV's BASE02 guard prefers its target-specific URL over the generic URL."""
    if environment.get('RSVDATA_TARGET', '').strip().upper() != 'BASE02':
        return
    key = 'RSVDATA_MCP_URL_BASE02'
    value = environment.get(key, '')
    if not value and environment.get('OPENROUTER_ENV_FILE'):
        path = Path(environment['OPENROUTER_ENV_FILE'])
        if path.is_file():
            for line in path.read_text(errors='replace').splitlines():
                name, separator, candidate = line.partition('=')
                if separator and name.strip() == key:
                    value = candidate.strip().strip('\"\'')
                    break
    value = value or environment.get('RSVDATA_MCP_URL', '')
    if 'base02' not in urlsplit(value).path.split('/'):
        raise ValueError('BASE02 target-specific endpoint is missing or points elsewhere')
    environment[key] = replace_host(value, gateway)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-id', choices=('mcp-rsv-data', 'codex-test-bridge'), required=True)
    parser.add_argument('--endpoint-env', action='append', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    allowed = {'mcp-rsv-data': {'RSVDATA_MCP_URL'}, 'codex-test-bridge': {'LDS_1C_BRIDGE_URL_IP'}}
    if not set(args.endpoint_env).issubset(allowed[args.server_id]):
        parser.error('Only the selected Windows endpoint variables may be redirected')
    try:
        config = tomllib.loads((Path.home() / '.codex/config.toml').read_text())
        server = config['mcp_servers'][args.server_id]
        command = server.get('command')
        if not isinstance(command, str) or Path(command).resolve() == Path(__file__).resolve():
            raise ValueError('Original global MCP command is unavailable')
        environment = dict(server.get('env', {}))
        environment.update(os.environ)
        gateway = windows_gateway()
        endpoints = []
        for key in args.endpoint_env:
            environment[key] = replace_host(environment[key], gateway)
            parsed = urlsplit(environment[key])
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            with socket.create_connection((gateway, port), timeout=1):
                endpoints.append({'variable': key, 'gateway': gateway, 'port': port, 'tcp_reachable': True})
        if args.server_id == 'mcp-rsv-data':
            pin_rsv_target_url(environment, gateway)
        if args.check_only:
            print(json.dumps({'server': args.server_id, 'endpoints': endpoints, 'original_command_preserved': True}))
            return 0
        cwd = server.get('cwd')
        if cwd:
            os.chdir(cwd)
        os.execvpe(command, [command, *server.get('args', [])], environment)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('MCP host gateway unavailable: ' + type(exc).__name__, file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
