#!/usr/bin/env python3
"""Безопасный прокси CodexTestBridge для проверок 1С runtime."""

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

from mcp.server.fastmcp import FastMCP


ROOT = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
ENV_FILE = ROOT / ".env.openrouter.local"
DEFAULT_BASE_URL = os.environ.get("LDS_1C_BRIDGE_URL", "http://127.0.0.1:18080/test-bridge")
POWERSHELL = os.environ.get(
    "POWERSHELL_BIN",
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
)
DIRECT_TIMEOUT_ENV = "LDS_1C_BRIDGE_DIRECT_TIMEOUT_SECONDS"
WINDOWS_FIRST_ENV = "LDS_1C_BRIDGE_WINDOWS_FIRST"
READ_ONLY_COMMANDS = {"Health", "Metadata", "Describe", "Query"}
WRITE_RISK_COMMANDS = {
    "ExecuteBSL",
    "CallCommonModule",
    "WriteObject",
    "GetObject",
    "DeleteObject",
    "RenderExternalPrintForm",
    "RenderExternalReport",
}

mcp = FastMCP("codex-test-bridge")


def _load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _base_url() -> str:
    _load_env_file()
    return os.environ.get("LDS_1C_BRIDGE_URL", DEFAULT_BASE_URL).rstrip("/")


def _candidate_base_urls() -> list[str]:
    _load_env_file()
    target = os.environ.get("LDS_1C_BRIDGE_TARGET", "").strip().upper()
    target_url = os.environ.get(f"LDS_1C_BRIDGE_URL_{target}", "") if target else ""
    target_url_ip = os.environ.get(f"LDS_1C_BRIDGE_URL_IP_{target}", "") if target else ""
    configured_urls = [
        target_url,
        target_url_ip,
        os.environ.get("LDS_1C_BRIDGE_URL", ""),
        os.environ.get("LDS_1C_BRIDGE_URL_IP", ""),
        DEFAULT_BASE_URL,
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_base in configured_urls:
        base = raw_base.strip().rstrip("/")
        if not base:
            continue
        for candidate in (base, base.rstrip("/") + "/hs/codex-test"):
            if base.endswith("/hs/codex-test") and candidate != base:
                continue
            if candidate in seen:
                continue
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def _headers(payload: dict[str, Any] | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    agent = os.environ.get("LDS_1C_BRIDGE_AGENT", "")
    password = os.environ.get("LDS_1C_BRIDGE_PASS", "")
    if agent or password:
        headers["Authorization"] = f"Basic {_auth_token()}"
    return headers


def _auth_token() -> str:
    agent = os.environ.get("LDS_1C_BRIDGE_AGENT", "")
    password = os.environ.get("LDS_1C_BRIDGE_PASS", "")
    if not agent and not password:
        return ""
    return base64.b64encode(f"{agent}:{password}".encode("utf-8")).decode("ascii")


def _is_wsl() -> bool:
    return platform.system() == "Linux" and "microsoft" in platform.release().lower()


def _request_json_windows(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _is_wsl() or not Path(POWERSHELL).exists():
        return {"ok": False, "error": "windows_fallback_unavailable", "url": url}
    auth_token = _auth_token()
    payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    url_b64 = base64.b64encode(url.encode("utf-8")).decode("ascii")
    token_b64 = base64.b64encode(auth_token.encode("utf-8")).decode("ascii")
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")
    script = """
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$bridgeUrl = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("__BRIDGE_URL_B64__"))
$bridgePayloadJson = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("__BRIDGE_PAYLOAD_B64__"))
$bridgeAuthToken = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("__BRIDGE_TOKEN_B64__"))
$headers = @{}
if ($bridgeAuthToken) { $headers["Authorization"] = "Basic " + $bridgeAuthToken }
try {
  if ($bridgePayloadJson) {
    $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $bridgeUrl -Headers $headers -ContentType "application/json; charset=utf-8" -Body $bridgePayloadJson -TimeoutSec 30
  } else {
    $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $bridgeUrl -Headers $headers -TimeoutSec 30
  }
  @{ok=$true; status=[int]$response.StatusCode; content=[string]$response.Content; url=$bridgeUrl} | ConvertTo-Json -Compress
} catch {
  $status = $null
  $content = ""
  if ($_.Exception.Response) {
    $status = [int]$_.Exception.Response.StatusCode
    try {
      $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
      $content = $reader.ReadToEnd()
    } catch {}
  }
  @{ok=$false; error="windows_http_error"; status=$status; message=[string]$_.Exception.Message; content=$content; url=$bridgeUrl} | ConvertTo-Json -Compress
}
""".replace("__BRIDGE_URL_B64__", url_b64).replace(
        "__BRIDGE_PAYLOAD_B64__", payload_b64
    ).replace("__BRIDGE_TOKEN_B64__", token_b64)
    # -EncodedCommand раздувает UTF-16 сценарий до лимита аргумента Windows в WSL.
    # Передача одной строки через -Command не использует shell и сохраняет base64-параметры.
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", script],
        text=False,
        capture_output=True,
        timeout=45,
        check=False,
    )
    raw = (proc.stdout or proc.stderr).decode("utf-8", errors="replace").strip()
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "windows_fallback_invalid_json", "returncode": proc.returncode, "output": raw[:800], "url": url}
    if outer.get("ok") and outer.get("content"):
        try:
            result = json.loads(outer["content"])
        except json.JSONDecodeError:
            result = {"ok": True, "content": outer["content"]}
        result["transport"] = "windows_powershell"
        result.setdefault("bridge_url", url.rsplit("/", 1)[0])
        return result
    outer["transport"] = "windows_powershell"
    return outer


def _direct_timeout_seconds() -> float:
    """Возвращает короткий лимит прямого WSL-запроса без долгой блокировки fallback."""
    _load_env_file()
    raw = os.environ.get(DIRECT_TIMEOUT_ENV, "4").strip()
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{DIRECT_TIMEOUT_ENV} должен быть числом") from exc
    if not 1.0 <= timeout <= 10.0:
        raise RuntimeError(f"{DIRECT_TIMEOUT_ENV} должен быть в диапазоне [1; 10]")
    return timeout


def _windows_first() -> bool:
    """Использует сетевой стек Windows первым только для WSL и по явной политике."""
    _load_env_file()
    configured = os.environ.get(WINDOWS_FIRST_ENV, "1").strip().casefold()
    return _is_wsl() and configured not in {"0", "false", "no", "off"}


def _request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if os.environ.get("OMVL_TEST_BRIDGE_DRY_RUN") == "1":
        return {"ok": True, "dry_run": True, "url": url, "payload": payload or {"command": "Health"}}
    if payload is None:
        request = urllib.request.Request(url, method="GET", headers=_headers(payload))
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers=_headers(payload),
        )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=_direct_timeout_seconds()) as response:
            data = response.read().decode("utf-8")
        return json.loads(data)
    except urllib.error.URLError as error:
        return {
            "ok": False,
            "error": "bridge_unavailable",
            "message": str(error.reason if hasattr(error, "reason") else error),
            "url": url,
        }
    except TimeoutError as error:
        return {"ok": False, "error": "bridge_timeout", "message": str(error), "url": url}


def _normalize_command(command: str) -> str:
    aliases = {
        "health": "Health",
        "metadata": "Metadata",
        "describe": "Describe",
        "query": "Query",
        "execute-bsl": "ExecuteBSL",
        "execute_bsl": "ExecuteBSL",
    }
    return aliases.get(command, command)


def _ensure_allowed(command: str, allow_write_risk: bool) -> None:
    if command in READ_ONLY_COMMANDS:
        return
    if command in WRITE_RISK_COMMANDS and allow_write_risk:
        return
    raise ValueError(f"Команда {command} заблокирована политикой read-only")


def call_bridge(command: str, payload: dict[str, Any] | None = None, allow_write_risk: bool = False) -> dict[str, Any]:
    command = _normalize_command(command)
    _ensure_allowed(command, allow_write_risk)
    body = {"command": command}
    if payload:
        body.update(payload)
    attempts: list[dict[str, Any]] = []
    for base_url in _candidate_base_urls():
        url = f"{base_url}/health" if command == "Health" else f"{base_url}/command"
        request_payload = None if command == "Health" else body
        if _windows_first():
            windows_result = _request_json_windows(url, request_payload)
            if windows_result.get("ok", True):
                windows_result.setdefault("bridge_url", base_url)
                return windows_result
            result = _request_json(url, request_payload)
            result = {**result, "windows_primary": windows_result}
        else:
            result = _request_json(url, request_payload)
            if result.get("ok", True):
                result.setdefault("bridge_url", base_url)
                return result
            if _is_wsl():
                windows_result = _request_json_windows(url, request_payload)
                if windows_result.get("ok", True):
                    windows_result.setdefault("bridge_url", base_url)
                    return windows_result
                result = {**result, "windows_fallback": windows_result}
        if result.get("ok", True):
            result.setdefault("bridge_url", base_url)
            return result
        attempts.append(result)
        if result.get("error") not in {"bridge_unavailable", "bridge_timeout"}:
            return result
    return {
        "ok": False,
        "error": "bridge_unavailable",
        "attempts": attempts,
    }


@mcp.tool()
def call_test_bridge(command: str = "Metadata", payload_json: str = "{}", allow_write_risk: bool = False) -> dict[str, Any]:
    """Вызвать CodexTestBridge. По умолчанию разрешены только Health, Metadata, Describe, Query."""
    payload = json.loads(payload_json) if payload_json.strip() else {}
    return call_bridge(command, payload, allow_write_risk)


def _direct(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Вызов CodexTestBridge")
    parser.add_argument("command", nargs="?", default="metadata")
    parser.add_argument("--sections", default="catalogs,documents,enums")
    parser.add_argument("--kind", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--query", default="")
    parser.add_argument("--payload-json", default="{}")
    parser.add_argument("--allow-write-risk", action="store_true")
    args = parser.parse_args(argv)

    command = _normalize_command(args.command)
    payload = json.loads(args.payload_json)
    if command == "Metadata" and "sections" not in payload:
        payload["sections"] = [item.strip() for item in args.sections.split(",") if item.strip()]
    if command == "Describe":
        payload.update({"kind": args.kind, "name": args.name})
    if command == "Query":
        payload.update({"text": args.query, "limit": int(payload.get("limit", 100)), "params": payload.get("params", {})})

    result = call_bridge(command, payload, args.allow_write_risk)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--direct":
        return _direct(sys.argv[2:])
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
