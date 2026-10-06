# Workspace Checkpoint — 2026-10-06

Russian companion: [WORKSPACE_CHECKPOINT_2026-10-06.md](WORKSPACE_CHECKPOINT_2026-10-06.md).

## Purpose and publication boundary

This document records the verified infrastructure layer of `epf1129` as of the
checkpoint date and provides a safe Codex pre-flight runbook. It is not a full
workspace dump and does not prove EPF deployment. The public version contains
only infrastructure code, templates, and this sanitized documentation. BSL/XML
business sources, databases, build artifacts, logs, RAG/runtime state, local
server registries, real `.env` files, and private addresses are excluded.

## Architecture and operating rules

- **Codex** coordinates work: identify the active model profile and target,
  search local RAG first, then navigate with Graph V2.
- **Graph V2** provides local source navigation; an index is not proof of code
  execution.
- **RAG FSM 2.0** stores reviewed solutions and lifecycle state. Search before
  changes and validate the store with `scripts/kb_manager.py --validate`.
- **OMVL / WAN25** routes cloud roles through an OpenAI-compatible gateway.
  Public templates may contain URLs and model names, never API keys.
- **MCP contours** provide test-bridge, RSV Data, and metadata navigation.
  Local database selection and endpoints live outside public templates.
- **Gates/hooks** prevent unsafe completion and must not be weakened to obtain a
  PASS. Database writes, deployment, publication, and risky service operations
  require separate explicit approval.

Default safety model: read-only diagnostics are permitted on designated
read-only targets; code edits remain unverified until tests pass; database
writes, EPF deployment, and server maintenance require separate authorization.
All 17 `x1_XX` source databases remain read-only.

## Verified state

The local `base02` contour is intended for read-only diagnostics. Passwords,
local database registries, and host addresses stay in protected local
configuration. Never copy these values into prompts, documentation, logs, or Git.

| Check | Checkpoint result | Limitation |
|---|---|---|
| COM and constant query | PASS | Diagnostic only |
| Web publication | HTTP 200 for bootstrap page | Interactive login was not tested |
| CodexTestBridge | Health, Metadata, and read-only query PASS | Does not prove other methods |
| RSV Data MCP | Initialization and constant read-only query PASS | Only the tested target route |
| OData | `$metadata` is valid | No EntitySet; data reads are unproven |
| PostgreSQL | Target database confirmed, read-only transaction, SELECT allowed | DML, DDL, and administration are not allowed |
| 1c-live-index MCP | Fresh process completed a diagnostic query | Existing MCP processes require restart |

Overall gate-check: **7/8 PASS**. **GATE 2 remains FAIL**: SMB authorization
denied access to the historical deployment directory. EPF deployment is not
claimed; a local artifact does not replace server-side evidence. Reality
Reconciliation is **WARN**: the built EPF hash and checkpoint fields differ
from the handover. This is not a current baseline.

Other automated checks at the checkpoint: env contract — PASS for 8 targets;
prompt contract — 16,996 bytes across 4 consumers; Graph V2 — fresh, 378 files;
full GATE 6 suite — 33 tests PASS. These are historical observations: rerun the
commands below before release. A prior PASS is not evidence of current state.

The public checkpoint intentionally omits the local server registry,
target-specific adapters containing internal endpoints, and local MCP/hook
wiring. The live results above record checks in the source workspace; they do
not claim every contour can be reproduced from this public clone without local
configuration.

## Configure through Codex

### 1. Prepare local settings

Start from `.env.example`. Copy it to an ignored local file such as
`.env.openrouter.local`, set permissions to `600`, and fill secrets locally.
Never print key values or pass them as CLI arguments. Keep credentials separate
by role and contour.

For the shared WAN25 gateway, use the public URL
`https://apiai.wan-2-5.pro/v1`, set `WAN25_GATEWAY_ENABLED=1`, and provide
`WAN25_API_KEY` only in the local secret file. Set the flag to `0` to disable
the shared gateway and retain per-role routes. Do not run a live smoke test until
the user has entered the key and explicitly requested the test.

### 2. Initial read-only prompt

```text
Run a read-only pre-flight of the current workspace. Search local RAG first,
then identify the active model profile and target database. Check the env
contract, Graph V2, prompt contract, and required MCP availability. Do not read
or print secrets; do not change files, databases, or services. Separate current
evidence from historical evidence and report PASS/WARN/FAIL with commands. Do
not claim successful deployment without server-side evidence.
```

### 3. Local verification commands

Run from the project root with the project Python interpreter:

```bash
PY=.venv-gemini-bridge/bin/python
$PY scripts/validate_env_contract.py
$PY scripts/workspace_graph_v2_manager.py check --deep
$PY scripts/validate_prompt_contracts.py
$PY scripts/kb_manager.py --validate
$PY scripts/gate_check.py --reverify
```

GATE 2 may remain blocked until deployment-share permissions are corrected. Do
not bypass it with a local file, change the target, or weaken the gate. For 1C
forms, inspect with `form-info`, make a focused `form-edit`, then run structural
validation and the EPF pipeline. Before BSL edits, inspect the target module and
metadata; do not read the entire `ObjectModule.bsl`.

### 4. Minimal live smoke after key entry

```text
Run one minimal live smoke for the required cloud roles through the standard
OMVL runtime and shared rate limiter. Do not print the key, headers, full model
output, or private endpoint. Report only each role, alias, route, and PASS/FAIL.
Do not retry manually after 429; respect Retry-After and the local limiter.
```

### 5. Git and publication

Before committing, check `git diff --check`, the staged diff, secrets, and the
RU/EN documentation pair. Stage an exact infrastructure allowlist only. Never
use `git add .`, `git add -A`, or `git commit -a`; exclude `src/`, databases,
RAG/runtime data, logs, built EPFs, and local env files. Before pushing, verify
the remote SHA and ensure the branch contains no business history.

## Checkpoint update criteria

Update both language versions together. Record the date, evidence, and limits;
do not copy secrets or local topology. Run tests and gates in the current
environment. Do not promote a RAG record to `success` without actual
confirmation. After publication, verify the remote SHA and inspect a fresh
clone. Exclude `Archive`/`archive` directories from navigation and audit.
