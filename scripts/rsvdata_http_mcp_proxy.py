#!/usr/bin/env python3
"""Stdio-proxy к HTTP MCP:RSV Data без хранения пароля в конфиге Codex."""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


RSVDATA_CONNECT_TIMEOUT_SECONDS = 3.0


ROOT = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
DEFAULT_ENV_FILE = ROOT / ".env.openrouter.local"
DEFAULT_URL = os.environ.get("RSVDATA_MCP_URL", "http://127.0.0.1:8080/hs/rsvdata/mcp")
DEFAULT_PROXY = os.environ.get("LDS_NETWORK_PROXY_IP", "")
POWERSHELL = os.environ.get(
    "POWERSHELL_BIN",
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
)


def _load_env_file() -> None:
    env_file = Path(os.environ.get("OPENROUTER_ENV_FILE", str(DEFAULT_ENV_FILE)))
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _merge_no_proxy(existing: str) -> str:
    items = [item.strip() for item in existing.split(",") if item.strip()]
    for item in ("127.0.0.1", "localhost"):
        if item not in items:
            items.append(item)
    return ",".join(items)


def _prepare_network_env() -> None:
    proxy = os.environ.get("LDS_NETWORK_PROXY_IP") or os.environ.get("LDS_NETWORK_PROXY") or DEFAULT_PROXY
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.setdefault(key, proxy)
    os.environ["NO_PROXY"] = _merge_no_proxy(os.environ.get("NO_PROXY", ""))
    os.environ["no_proxy"] = _merge_no_proxy(os.environ.get("no_proxy", ""))


def _auth_header() -> str:
    login = os.environ.get("RSVDATA_USER") or os.environ.get("LDS_1C_BRIDGE_AGENT", "")
    password = os.environ.get("RSVDATA_PASS") or os.environ.get("LDS_1C_BRIDGE_PASS", "")
    if not login and not password:
        return ""
    token = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _is_wsl() -> bool:
    return platform.system() == "Linux" and "microsoft" in platform.release().lower()


def _rsv_url_from_bridge_url(url: str) -> str:
    base = url.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/hs/rsvdata/mcp"):
        return base
    if "/hs/codex-test" in base:
        return base.replace("/hs/codex-test", "/hs/rsvdata/mcp")
    return base.rstrip("/") + "/hs/rsvdata/mcp"


def _server_urls() -> list[str]:
    target = os.environ.get("RSVDATA_TARGET", "").strip().upper()
    target_url = os.environ.get(f"RSVDATA_MCP_URL_{target}", "") if target else ""
    raw_urls = [
        target_url,
        os.environ.get("RSVDATA_MCP_URL", ""),
        _rsv_url_from_bridge_url(os.environ.get("LDS_1C_BRIDGE_URL_IP", "")),
        _rsv_url_from_bridge_url(os.environ.get("LDS_1C_BRIDGE_URL", "")),
        DEFAULT_URL,
    ]
    result: list[str] = []
    seen: set[str] = set()
    for raw_url in raw_urls:
        url = raw_url.strip().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def _extract_json_response(content_type: str, body: str) -> dict[str, Any] | None:
    if "text/event-stream" in content_type:
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                return json.loads(payload)
        return None
    if body.strip():
        return json.loads(body)
    return None


def _post_json_to_url(url: str, message: dict[str, Any]) -> dict[str, Any] | None:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    auth = _auth_header()
    if auth:
        headers["Authorization"] = auth
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=RSVDATA_CONNECT_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            return _extract_json_response(response.headers.get("Content-Type", ""), body)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32000,
                "message": f"RSV Data HTTP {error.code}: {body[:300]}",
            },
        }
    except Exception as error:  # noqa: BLE001
        windows_response = _post_json_windows(url, message)
        if windows_response is not None:
            return windows_response
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32001,
                "message": f"RSV Data transport error: {type(error).__name__}: {error}",
            },
        }


def _post_json(message: dict[str, Any]) -> dict[str, Any] | None:
    attempts: list[str] = []
    for url in _server_urls():
        response = _post_json_to_url(url, message)
        if not response or "error" not in response:
            return response
        error_message = response["error"].get("message", "unknown")
        attempts.append(error_message)
        if "HTTP 401" in error_message or "Превышено допустимое количество ошибок" in error_message:
            break
    return {
        "jsonrpc": "2.0",
        "id": message.get("id"),
        "error": {
            "code": -32005,
            "message": "RSV Data unavailable: " + " | ".join(attempts)[:900],
        },
    }


def _post_json_windows(url: str, message: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_wsl() or not Path(POWERSHELL).exists():
        return None
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    url_b64 = base64.b64encode(url.encode("utf-8")).decode("ascii")
    auth_b64 = base64.b64encode(_auth_header().encode("utf-8")).decode("ascii")
    payload_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$url = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("__URL_B64__"))
$auth = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("__AUTH_B64__"))
$payload = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("__PAYLOAD_B64__"))
$headers = @{
  "Accept" = "application/json, text/event-stream"
}
if ($auth) { $headers["Authorization"] = $auth }
try {
  $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $url -Headers $headers -ContentType "application/json; charset=utf-8" -Body $payload -TimeoutSec 3
  @{ ok=$true; contentType=[string]$response.Headers["Content-Type"]; body=[string]$response.Content } | ConvertTo-Json -Compress
} catch {
  $status = $null
  $body = ""
  if ($_.Exception.Response) {
    $status = [int]$_.Exception.Response.StatusCode
    try {
      $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
      $body = $reader.ReadToEnd()
    } catch {}
  }
  @{ ok=$false; status=$status; message=[string]$_.Exception.Message; body=$body } | ConvertTo-Json -Compress
}
""".replace("__URL_B64__", url_b64).replace("__AUTH_B64__", auth_b64).replace("__PAYLOAD_B64__", payload_b64)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-EncodedCommand", encoded],
        text=False,
        capture_output=True,
        timeout=75,
        check=False,
    )
    raw = (proc.stdout or proc.stderr).decode("utf-8", errors="replace").strip()
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32002,
                "message": f"RSV Data Windows fallback invalid response: {raw[:300]}",
            },
        }
    if not outer.get("ok"):
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32003,
                "message": f"RSV Data Windows fallback HTTP {outer.get('status')}: {(outer.get('body') or outer.get('message') or '')[:300]}",
            },
        }
    try:
        return _extract_json_response(str(outer.get("contentType", "")), str(outer.get("body", "")))
    except Exception as error:  # noqa: BLE001
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32004,
                "message": f"RSV Data Windows fallback parse error: {type(error).__name__}: {error}",
            },
        }


def _print_response(response: dict[str, Any] | None) -> None:
    if response is None:
        return
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve() -> int:
    _load_env_file()
    _prepare_network_env()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        response = _post_json(message)
        _print_response(response)
    return 0


def smoke_config() -> int:
    _load_env_file()
    _prepare_network_env()
    print(json.dumps({
        "urls": _server_urls(),
        "has_auth": bool(_auth_header()),
        "proxy": os.environ.get("HTTP_PROXY", ""),
        "no_proxy": os.environ.get("NO_PROXY", ""),
    }, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-config", action="store_true")
    args = parser.parse_args()
    if args.smoke_config:
        return smoke_config()
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
