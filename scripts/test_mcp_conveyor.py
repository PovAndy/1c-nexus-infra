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
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BASE_DIR = Path(__file__).resolve().parents[1]
_PROJECT_PYTHON = BASE_DIR / ".venv-gemini-bridge" / "bin" / "python"
PYTHON = _PROJECT_PYTHON if _PROJECT_PYTHON.is_file() else Path(sys.executable)
ENV_FILE = BASE_DIR / ".env.openrouter.local"
CALL_OWL = BASE_DIR / "scripts" / "call_owl.py"
CALL_CRITIC = BASE_DIR / "scripts" / "call_critic.py"
RUN_CODE_INDEX = BASE_DIR / "scripts" / "run_code_index_mcp.py"
CALL_TEST_BRIDGE = BASE_DIR / "scripts" / "call_test_bridge.py"
KB_MANAGER = BASE_DIR / "scripts" / "kb_manager.py"


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["OPENROUTER_ENV_FILE"] = str(ENV_FILE)
    return env


def _selftest_env() -> dict[str, str]:
    env = _base_env()
    env["OMVL_CASCADE_SELFTEST"] = "1"
    env["WAN25_GATEWAY_ENABLED"] = "1"
    env["WAN25_API_KEY"] = "selftest-wan25-key"
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


def run_kb_manager(args: list[str], *, kb_file: Path, timeout: int = 60) -> tuple[int, str]:
    completed = subprocess.run(
        [str(PYTHON), str(KB_MANAGER), *args, "--kb", str(kb_file)],
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


def _new_test_kb(path: Path) -> None:
    data = {
        "schema_version": "2.0",
        "version": "2.0",
        "taxonomy": {
            "x17_recovery": {}, "validation": {}, "environment_setup": {},
            "anti_patterns": {}, "1c_logic": {},
        },
        "error_solution_table": [],
        "indexes": {"by_topic": {}, "by_subtopic": {}, "by_kind": {}, "by_mem_room": {}},
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_kb_table(kb_file: Path) -> list[dict[str, object]]:
    data = json.loads(kb_file.read_text(encoding="utf-8"))
    table = data.get("error_solution_table", [])
    if not isinstance(table, list):
        raise ValueError("error_solution_table не является массивом")
    return [item for item in table if isinstance(item, dict)]


def _find_kb_entry(kb_file: Path, entry_id: str) -> dict[str, object] | None:
    for entry in _load_kb_table(kb_file):
        if entry.get("id") == entry_id:
            return entry
    return None


def check_kb_manager_fsm_transition() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temporary:
        kb_file = Path(temporary) / "knowledge_base.json"
        _new_test_kb(kb_file)
        marker = f"OMVL FSM self-test {os.getpid()} {time.time_ns()}"
        code, output = run_kb_manager(["--task", marker, "--status", "under_review"], kb_file=kb_file)
        entry_id = _entry_id_from_output(output)
        if code != 0 or not entry_id:
            return False, output[:700]

        for status in ("unstable", "success"):
            code, output = run_kb_manager(["--id", entry_id, "--status", status], kb_file=kb_file)
            if code != 0:
                return False, output[:700]

        entries = [entry for entry in _load_kb_table(kb_file) if entry.get("id") == entry_id]
        if len(entries) != 1:
            return False, f"ожидалась одна запись, найдено {len(entries)}"
        entry = entries[0]
        ok = entry.get("fsm_status") == "success" and entry.get("status") == "удачно" and bool(entry.get("updated_at"))
        return ok, f"id={entry_id} status={entry.get('status')} fsm={entry.get('fsm_status')}"


def check_kb_manager_locking() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temporary:
        kb_file = Path(temporary) / "knowledge_base.json"
        _new_test_kb(kb_file)
        marker = f"OMVL flock self-test {os.getpid()} {time.time_ns()}"
        processes: list[subprocess.Popen[str]] = []
        for index in range(5):
            processes.append(
                subprocess.Popen(
                    [str(PYTHON), str(KB_MANAGER), "--task", f"{marker} #{index}", "--status", "under_review", "--kb", str(kb_file)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(BASE_DIR.parent),
                )
            )

        ids: list[str] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            output = (stdout + stderr).strip()
            if process.returncode != 0:
                return False, output[:700]
            entry_id = _entry_id_from_output(output)
            if not entry_id:
                return False, output[:700]
            ids.append(entry_id)

        table = _load_kb_table(kb_file)
        present = {entry.get("id") for entry in table if entry.get("id") in set(ids)}
        ok = len(present) == len(ids)
        return ok, f"parallel_writes={len(ids)} present={len(present)}"


def test_kb_manager_fsm_transition() -> None:
    ok, detail = check_kb_manager_fsm_transition()
    assert ok, detail


def test_kb_manager_locking() -> None:
    ok, detail = check_kb_manager_locking()
    assert ok, detail


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
        "ORCHESTRATOR_MODEL": "openai/gpt-5.6-sol",
        "CODER_LUNA_MODEL": "openai/gpt-5.6-luna",
        "CODER_LUNA_FALLBACK_MODEL": "claude-3-7-sonnet",
        "CRITIC_MODEL": "vanchin/deepseek-v4-pro",
        "CRITIC_FALLBACK_MODEL": "zhipu/glm-5-3",
        "LIBRARIAN_MODEL": "moonshot/kimi-k3",
        "LIBRARIAN_FALLBACK_MODEL": "qwen/qwen3.6-plus",
        "SCRIBE_MODEL": "qwen/qwen3.6-flash",
    }
    model_ok = all(values.get(key) == value for key, value in expected_models.items())
    results.append(print_result("env_models_wan25", model_ok, "модели WAN25 сверены"))

    gateway_config_ok = (
        values.get("WAN25_GATEWAY_ENABLED") in {"0", "1"}
        and values.get("WAN25_RPM_LIMIT") == "10"
        and values.get("WAN25_MIN_INTERVAL_SECONDS") == "6.0"
        and values.get("CODER_API_BASE_URL") == "https://apiai.wan-2-5.pro/v1"
    )
    results.append(print_result("wan25_gateway_switch", gateway_config_ok, "gateway включаем и отключаем через WAN25_GATEWAY_ENABLED"))

    limiter_ok = (
        Path(BASE_DIR / "scripts" / "openrouter_rate_limit.py").exists()
        and _file_contains(CALL_OWL, "acquire_openrouter_slot")
        and _file_contains(CALL_CRITIC, "acquire_openrouter_slot")
    )
    results.append(print_result("wan25_limiter_active", limiter_ok, "лимитер подключен к прокси"))

    prompt = "Проверка каскада OMVL. Верни короткий ответ."
    code, output = run_direct(CALL_OWL, prompt, env=_selftest_env())
    results.append(
        print_result(
            "owl_cascade_wan25_primary",
            code == 0 and "CASCADE_USED: role_gateway" in output and "moonshot/kimi-k3" in output,
            output[:500],
        )
    )

    paid_env = _selftest_env()
    code, output = run_direct(CALL_OWL, prompt, env=paid_env)
    results.append(
        print_result(
            "owl_cascade_wan25_primary_repeat",
            code == 0
            and "CASCADE_USED: role_gateway" in output
            and "moonshot/kimi-k3" in output,
            output[:500],
        )
    )

    fallback_env = _selftest_env()
    fallback_env["OMVL_FORCE_OPENROUTER_STATUS"] = "429"
    code, output = run_direct(CALL_OWL, prompt, env=fallback_env)
    results.append(
        print_result(
            "owl_cascade_qwen_after_kimi_429",
            code == 0
            and "CASCADE_USED: role_gateway_fallback" in output
            and "moonshot/kimi-k3" in output
            and "qwen/qwen3.6-plus" in output,
            output[:500],
        )
    )

    shield_env = _selftest_env()
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
        and "CASCADE_USED: role_gateway_fallback" in output
        and "vanchin/deepseek-v4-pro" in output
        and "zhipu/glm-5-3" in output
        and "Traceback" not in output
    )
    results.append(print_result("critic_cascade_glm_after_503", critic_ok, output[:700]))

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

    ok, detail = check_kb_manager_fsm_transition()
    results.append(print_result("kb_manager_fsm_transition", ok, detail))

    ok, detail = check_kb_manager_locking()
    results.append(print_result("kb_manager_file_locking", ok, detail))

    passed = sum(1 for item in results if item)
    print(f"ИТОГО успешно={passed} всего={len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
