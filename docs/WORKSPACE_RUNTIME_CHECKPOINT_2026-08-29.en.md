# Infrastructure Workspace Checkpoint — 2026-08-29

Current English documentation for the public infrastructure checkpoint.
Russian companion: [WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.md](WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.md).

## Published scope

The public repository contains a sanitized infrastructure layer: Graph V2, RAG
FSM, prompt contract, resilience runtime, WAN25 limiter, sanitized environment,
and an OpenCode example. The complete local `epf1129` workspace is not published.

Gateway URLs, provider model IDs, OpenCode aliases, and empty placeholders may
be published. Real API keys, passwords, tokens, private endpoints, RAG/runtime
state, 1C databases, logs, and private topology must not be published.

## WAN25 routing

`WAN25_GATEWAY_ENABLED=1` routes OMVL roles through the shared
`https://apiai.wan-2-5.pro/v1` endpoint and `WAN25_API_KEY`. `0` keeps each role's
own rollback endpoint and credential slot. Templates are in `.env.example` and
`opencode.example.json`.

| Role | Primary | Fallback |
|---|---|---|
| Orchestrator | `openai/gpt-5.6-sol` | `openai/gpt-5.6-luna` |
| Coder Luna | `openai/gpt-5.6-luna` | `claude-3-7-sonnet` |
| Critic | `vanchin/deepseek-v4-pro` | `zhipu/glm-5-3` |
| Librarian | `moonshot/kimi-k3` | `qwen/qwen3.6-plus` |
| Scribe | `qwen/qwen3.6-flash` | `qwen/qwen3.6-plus` |
| Forensics | `qwen/qwen3.6-plus` | `zhipu/glm-5-3` |

The shared limiter uses atomic state and an inter-process lock: maximum 10 RPM,
at least 6 seconds between calls, `429` retries at 7/14 seconds, and fallback on
queue overflow.

## Verified source state

Local `epf1129` commit:
`78e86c5b03c4663890313cf4649f6be102053dff`. The source was checked with 21
resilience/MCP tests, a 16,996-byte prompt contract check, env contract, hooks,
hygiene, and RAG schema 2.0 validation. Authorized WAN25 smoke passed for
Orchestrator, Coder Luna, Critic, Librarian, Scribe, and Forensics. This is local
source evidence, not a guarantee that a future environment can reach the gateway.

## Codex runbook

Run commands from a clone of the public repository. Never pass secrets to Codex
in prompts or CLI arguments.

```bash
export NEXUS_WORKSPACE_ROOT="$(pwd)"
PY=python3
$PY scripts/validate_prompt_contracts.py
$PY scripts/kb_manager.py --validate
$PY scripts/workspace_graph_v2_manager.py check --deep
```

Read-only pre-flight prompt:

```text
Run a read-only pre-flight of the current workspace. Search local RAG first, then check the env contract, Graph V2, and prompt contract. Do not read or print secret values. Report PASS/WARN/FAIL separately and do not modify files.
```

Fill the local environment from the example:

```bash
cp .env.example .env
${EDITOR:-vi} .env
chmod 600 .env
```

Set `WAN25_API_KEY` only in the local `.env` and set
`WAN25_GATEWAY_ENABLED=1`. Set it to `0` for rollback. Restart Codex/MCP/OpenCode
after changing environment values.

Live-smoke prompt:

```text
Run a minimal live smoke for the configured OMVL roles through the standard runtime and shared limiter. Do not print the key, full model output, or private headers. Report only role, model alias, primary/fallback route, and PASS/FAIL. Never retry manually outside the limiter.
```

Codex CLI:

```bash
codex exec -C "$NEXUS_WORKSPACE_ROOT" "Run a read-only WAN25 configuration audit and return PASS/WARN/FAIL without exposing secrets"
```

Publish only through an exact allowlist and after a fresh-clone check:

```bash
git diff --check
git status --short
git add -- <exact-allowlist-files>
git diff --cached --check
git commit -m "checkpoint(workspace): publish bilingual WAN25 runtime state"
git push origin main
```

Before push, run a staged secret scan, verify bilingual links, `git fsck --full`,
the remote SHA, and a fresh clone. Do not copy local RAG or Graph state into the
public repository.
