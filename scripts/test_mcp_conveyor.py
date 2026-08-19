#!/usr/bin/env python3
"""Детерминированная проверка OMVL MCP-конвейера epf1129."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BASE_DIR = Path(__file__).resolve().parents[1]
PYTHON = BASE_DIR / ".venv-gemini-bridge" / "bin" / "python"
ENV_FILE = BASE_DIR / ".env.openrouter.local"
CALL_OWL = BASE_DIR / "scripts" / "call_owl.py"
CALL_CRITIC = BASE_DIR / "scripts" / "call_critic.py"
RUN_CODE_INDEX = BASE_DIR / "scripts" / "run_code_index_mcp.py"
CALL_TEST_BRIDGE = BASE_DIR / "scripts" / "call_test_bridge.py"
KB_MANAGER = BASE_DIR / "scripts" / "kb_manager.py"
KB_FILE = BASE_DIR.parent / "knowledge_base.json"


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["OPENROUTER_ENV_FILE"] = str(ENV_FILE)
    return env


def _selftest_env() -> dict[str, str]:
    env = _base_env()
    env["OMVL_CASCADE_SELFTEST"] = "1"
    return env


def _read_env_values() -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        key, value = match.groups()
        result[key] = value.strip().strip('"').strip("'")
    return result


def _file_contains(path: Path, needle: str) -> bool:
    return needle in path.read_text(encoding="utf-8")


def _resolve_alias(values: dict[str, str], alias_var: str) -> str:
    alias = values.get(alias_var, "")
    return values.get(alias, "")


def run_direct(script: Path, prompt: str, env: dict[str, str] | None = None, timeout: int = 140) -> tuple[int, str]:
    completed = subprocess.run(
        [str(PYTHON), str(script), "--direct"],
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env or _base_env(),
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def run_kb_manager(args: list[str], timeout: int = 60) -> tuple[int, str]:
    completed = subprocess.run(
        [str(PYTHON), str(KB_MANAGER), *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(BASE_DIR.parent),
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def run_test_bridge_metadata_dry_run(timeout: int = 45) -> tuple[int, str]:
    env = _base_env()
    env["OMVL_TEST_BRIDGE_DRY_RUN"] = "1"
    completed = subprocess.run(
        [str(PYTHON), str(CALL_TEST_BRIDGE), "--direct", "metadata"],
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def _entry_id_from_output(output: str) -> str:
    match = re.search(r"kb_manager: added\s+(\S+)", output)
    return match.group(1) if match else ""


def _load_kb_table() -> list[dict[str, object]]:
    data = json.loads(KB_FILE.read_text(encoding="utf-8"))
    table = data.get("error_solution_table", [])
    if not isinstance(table, list):
        raise ValueError("error_solution_table не является массивом")
    return [item for item in table if isinstance(item, dict)]


def _find_kb_entry(entry_id: str) -> dict[str, object] | None:
    for entry in _load_kb_table():
        if entry.get("id") == entry_id:
            return entry
    return None


def test_kb_manager_fsm_transition() -> tuple[bool, str]:
    marker = f"OMVL 3.9 FSM transition self-test {os.getpid()} {time.time_ns()}"
    code, output = run_kb_manager(["--task", marker, "--status", "under_review"])
    entry_id = _entry_id_from_output(output)
    if code != 0 or not entry_id:
        return False, output[:700]

    for status in ("unstable", "success"):
        code, output = run_kb_manager(["--id", entry_id, "--status", status])
        if code != 0:
            return False, output[:700]

    entries = [entry for entry in _load_kb_table() if entry.get("id") == entry_id]
    if len(entries) != 1:
        return False, f"ожидалась одна запись, найдено {len(entries)}"
    entry = entries[0]
    ok = entry.get("fsm_status") == "success" and entry.get("status") == "удачно" and bool(entry.get("updated_at"))
    return ok, f"id={entry_id} status={entry.get('status')} fsm={entry.get('fsm_status')}"


def test_kb_manager_locking() -> tuple[bool, str]:
    marker = f"OMVL 3.9 flock self-test {os.getpid()} {time.time_ns()}"
    processes: list[subprocess.Popen[str]] = []
    for index in range(5):
        processes.append(
            subprocess.Popen(
                [str(PYTHON), str(KB_MANAGER), "--task", f"{marker} #{index}", "--status", "under_review"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(BASE_DIR.parent),
            )
        )

    outputs: list[str] = []
    ids: list[str] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=60)
        output = (stdout + stderr).strip()
        outputs.append(output)
        if process.returncode != 0:
            return False, output[:700]
        entry_id = _entry_id_from_output(output)
        if not entry_id:
            return False, output[:700]
        ids.append(entry_id)

    table = _load_kb_table()
    present = {entry.get("id") for entry in table if entry.get("id") in set(ids)}
    ok = len(present) == len(ids)
    return ok, f"parallel_writes={len(ids)} present={len(present)}"


async def mcp_handshake(script: Path, expected_tool: str, timeout: int = 25) -> tuple[bool, str]:
    result: tuple[bool, str] | None = None

    async def _run() -> tuple[bool, str]:
        nonlocal result
        params = StdioServerParameters(
            command=str(PYTHON),
            args=[str(script)],
            env=_base_env(),
            cwd=str(BASE_DIR),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                result = (expected_tool in names, ",".join(names))
                return result

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except TimeoutError:
        if result is not None:
            ok, detail = result
            return ok, f"{detail}; cleanup timeout after handshake"
        return False, f"timeout after {timeout}s"


async def stdio_guard(script: Path, expected_tool: str, timeout: int = 20) -> tuple[bool, str]:
    env = _base_env()
    process = await asyncio.create_subprocess_exec(
        str(PYTHON),
        str(script),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(BASE_DIR),
        env=env,
    )

    stderr_chunks: list[bytes] = []

    async def _collect_stderr() -> None:
        assert process.stderr is not None
        while True:
            chunk = await process.stderr.read(4096)
            if not chunk:
                return
            stderr_chunks.append(chunk)

    stderr_task = asyncio.create_task(_collect_stderr())

    async def _send(message: dict[str, object]) -> None:
        assert process.stdin is not None
        process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def _read_response(request_id: int) -> dict[str, object]:
        assert process.stdout is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timeout waiting for id={request_id}")
            raw_line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            if not raw_line:
                raise RuntimeError("stdout closed before response")
            line = raw_line.decode("utf-8", errors="replace").strip()
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"stdout pollution: {line[:300]}") from exc
            if message.get("id") == request_id:
                return message

    async def _terminate() -> None:
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        stderr_task.cancel()
        try:
            await stderr_task
        except asyncio.CancelledError:
            pass

    try:
        await _send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "omvl-stdio-guard", "version": "1"},
                },
            }
        )
        init_response = await _read_response(1)
        if "result" not in init_response:
            return False, f"initialize failed: {str(init_response)[:500]}"

        await _send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        await _send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_response = await _read_response(2)
        tools = tools_response.get("result", {}).get("tools", []) if isinstance(tools_response.get("result"), dict) else []
        names = [str(tool.get("name", "")) for tool in tools if isinstance(tool, dict)]
        if expected_tool not in names:
            return False, f"tool {expected_tool} not found: {','.join(names)}"

        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
        detail = ",".join(names)
        if stderr_text:
            detail += f"; stderr={stderr_text[:300]}"
        return True, detail
    except Exception as exc:
        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
        detail = f"{type(exc).__name__}: {exc}"
        if stderr_text:
            detail += f"; stderr={stderr_text[:300]}"
        return False, detail
    finally:
        await _terminate()


def print_result(name: str, ok: bool, detail: str) -> bool:
    status = "УСПЕХ" if ok else "ОШИБКА"
    print(f"{status} {name}: {detail}", flush=True)
    return ok


async def main() -> int:
    results: list[bool] = []

    values = _read_env_values()
    expected_models = {
        "OR_MODEL_LIBRARIAN_FALLBACK": "qwen/qwen3.6-flash",
        "OR_MODEL_CRITIC": "deepseek/deepseek-v4-pro",
        "OR_MODEL_CRITIC_FALLBACK": "qwen/qwen3.6-plus",
        "OR_MODEL_FORENSICS": "qwen/qwen3.6-plus",
        "OR_MODEL_SCRIBE": "deepseek/deepseek-v4-flash",
        "OR_MODEL_GEMINI_25_PRO": "gemini-2.5-pro",
    }
    model_ok = all(values.get(key) == value for key, value in expected_models.items())
    results.append(print_result("env_models_omvl_42", model_ok, "модели OMVL 4.2 сверены"))

    paid_key_ok = (
        "OR_KEY_PAID_CHEAP" in values
        and values.get("OMVL_ROLE_LIBRARIAN_PAID_KEY_ALIAS") == "OR_KEY_PAID_CHEAP"
        and values.get("OMVL_ROLE_CRITIC_PRIMARY_KEY_ALIAS") == "OR_KEY_PAID_CHEAP"
        and values.get("OMVL_ROLE_CRITIC_FALLBACK_KEY_ALIAS") == "OR_KEY_PAID_CHEAP"
        and values.get("OMVL_ROLE_FORENSICS_PRIMARY_KEY_ALIAS") == "OR_KEY_PAID_CHEAP"
        and values.get("OMVL_ROLE_SCRIBE_PRIMARY_KEY_ALIAS") == "OR_KEY_PAID_CHEAP"
    )
    results.append(print_result("paid_cheap_key_aliases", paid_key_ok, "роли используют OR_KEY_PAID_CHEAP"))

    role_alias_ok = (
        _resolve_alias(values, "OMVL_ROLE_LIBRARIAN_PAID_MODEL_ALIAS") == "qwen/qwen3.6-flash"
        and values.get("OMVL_ROLE_LIBRARIAN_LOCAL_MODEL_ALIASES") == "OR_MODEL_GEMINI_25_PRO"
        and _resolve_alias(values, "OMVL_ROLE_CRITIC_PRIMARY_MODEL_ALIAS") == "deepseek/deepseek-v4-pro"
        and _resolve_alias(values, "OMVL_ROLE_CRITIC_FALLBACK_MODEL_ALIAS") == "qwen/qwen3.6-plus"
        and _resolve_alias(values, "OMVL_ROLE_FORENSICS_PRIMARY_MODEL_ALIAS") == "qwen/qwen3.6-plus"
        and _resolve_alias(values, "OMVL_ROLE_SCRIBE_PRIMARY_MODEL_ALIAS") == "deepseek/deepseek-v4-flash"
    )
    results.append(print_result("role_alias_resolution_42", role_alias_ok, "роли разворачиваются через alias-переменные 4.2"))

    limiter_ok = (
        Path(BASE_DIR / "scripts" / "openrouter_rate_limit.py").exists()
        and _file_contains(CALL_OWL, "acquire_openrouter_slot")
        and _file_contains(CALL_CRITIC, "acquire_openrouter_slot")
    )
    results.append(print_result("openrouter_limiter_active", limiter_ok, "лимитер подключен к прокси"))

    gemini_ok = shutil.which("gemini") is not None
    results.append(print_result("gemini_cli_present", gemini_ok, shutil.which("gemini") or "gemini не найден"))

    prompt = "Проверка каскада OMVL. Верни короткий ответ."
    code, output = run_direct(CALL_OWL, prompt, env=_selftest_env())
    results.append(
        print_result(
            "owl_cascade_gemini_first",
            code == 0 and "CASCADE_USED: local_gemini_cli" in output and "gemini-2.5-pro" in output,
            output[:500],
        )
    )

    paid_env = _selftest_env()
    paid_env["OMVL_DISABLE_GEMINI_CLI"] = "1"
    code, output = run_direct(CALL_OWL, prompt, env=paid_env)
    results.append(
        print_result(
            "owl_cascade_paid_after_cli_fail",
            code == 0
            and "CASCADE_USED: openrouter_paid" in output
            and "qwen/qwen3.6-flash" in output,
            output[:500],
        )
    )

    fallback_env = _selftest_env()
    fallback_env["OMVL_DISABLE_GEMINI_CLI"] = "1"
    fallback_env["OMVL_FORCE_OPENROUTER_STATUS"] = "429"
    code, output = run_direct(CALL_OWL, prompt, env=fallback_env)
    results.append(
        print_result(
            "owl_cascade_deepseek_after_qwen_429",
            code == 0
            and "CASCADE_USED: openrouter_paid_fallback" in output
            and "qwen/qwen3.6-flash" in output
            and "deepseek/deepseek-v4-flash" in output,
            output[:500],
        )
    )

    shield_env = _selftest_env()
    shield_env["OMVL_DISABLE_GEMINI_CLI"] = "1"
    shield_env["OMVL_AGENTSHIELD_ECHO_PROMPT"] = "1"
    shield_prompt = "Проверка AgentShield: LDS_PROVIDER_TOKEN_A=test-secret EPF_SQL_RO_PWD=pg-secret password=inline-secret"
    code, output = run_direct(CALL_OWL, shield_prompt, env=shield_env)
    shield_ok = (
        code == 0
        and "[MASKED_BY_AGENTSHIELD]" in output
        and "LDS_PROVIDER_TOKEN_A" not in output
        and "test-secret" not in output
        and "pg-secret" not in output
        and "inline-secret" not in output
    )
    results.append(print_result("owl_agentshield_masks_prompt", shield_ok, output[:700]))

    ok, tools = await mcp_handshake(CALL_OWL, "get_context")
    results.append(print_result("owl_stdio_handshake", ok, tools))

    ok, detail = await stdio_guard(CALL_OWL, "get_context")
    results.append(print_result("owl_stdio_guard", ok, detail))

    ok, tools = await mcp_handshake(CALL_CRITIC, "verify_syntax")
    results.append(print_result("critic_stdio_handshake", ok, tools))

    ok, detail = await stdio_guard(CALL_CRITIC, "verify_syntax")
    results.append(print_result("critic_stdio_guard", ok, detail))

    ok, tools = await mcp_handshake(RUN_CODE_INDEX, "get_stats")
    results.append(print_result("code_index_mcp_handshake", ok, tools))

    ok, detail = await stdio_guard(RUN_CODE_INDEX, "get_stats")
    results.append(print_result("code_index_stdio_guard", ok, detail))

    ok, tools = await mcp_handshake(CALL_TEST_BRIDGE, "call_test_bridge")
    results.append(print_result("test_bridge_mcp_handshake", ok, tools))

    ok, detail = await stdio_guard(CALL_TEST_BRIDGE, "call_test_bridge")
    results.append(print_result("test_bridge_stdio_guard", ok, detail))

    code, output = run_test_bridge_metadata_dry_run()
    bridge_metadata_ok = (
        code == 0
        and '"dry_run": true' in output
        and '"command": "Metadata"' in output
        and "catalogs" in output
    )
    results.append(print_result("test_bridge_metadata_probe", bridge_metadata_ok, output[:700]))

    critic_prompt = (
        "КОНТЕКСТ:\nПроверка конвейера.\n\n"
        "КОД:\nПроцедура Тест()\n\tСообщить(\"OK\");\nКонецПроцедуры"
    )
    critic_env = _selftest_env()
    critic_env["OMVL_FORCE_CRITIC_STATUS"] = "503"
    code, output = run_direct(CALL_CRITIC, critic_prompt, env=critic_env)
    critic_ok = (
        code == 0
        and "CASCADE_USED: openrouter_paid_fallback" in output
        and "deepseek/deepseek-v4-pro" in output
        and "qwen/qwen3.6-plus" in output
        and "Traceback" not in output
    )
    results.append(print_result("critic_cascade_qwen_after_503", critic_ok, output[:700]))

    critic_shield_env = _selftest_env()
    critic_shield_env["OMVL_AGENTSHIELD_ECHO_PROMPT"] = "1"
    code, output = run_direct(CALL_CRITIC, shield_prompt, env=critic_shield_env)
    critic_shield_ok = (
        code == 0
        and "[MASKED_BY_AGENTSHIELD]" in output
        and "LDS_PROVIDER_TOKEN_A" not in output
        and "test-secret" not in output
        and "pg-secret" not in output
        and "inline-secret" not in output
    )
    results.append(print_result("critic_agentshield_masks_prompt", critic_shield_ok, output[:700]))

    ok, detail = test_kb_manager_fsm_transition()
    results.append(print_result("kb_manager_fsm_transition", ok, detail))

    ok, detail = test_kb_manager_locking()
    results.append(print_result("kb_manager_file_locking", ok, detail))

    passed = sum(1 for item in results if item)
    print(f"ИТОГО успешно={passed} всего={len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
