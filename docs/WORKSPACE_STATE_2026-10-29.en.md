# Workspace state: version 1.0.1

## Purpose and snapshot boundary

This document records the portable state of the `1c-nexus-infra`
infrastructure repository on **2026-10-29**. It supports reproducible setup of
a local 1C development environment; it is not a database, deployment, or
dependent workspace-source snapshot.

The repository excludes secrets, local `.env` files, tokens, runtime caches,
logs, virtual environments, Graph V2 artifacts, and EPF source artifacts.
Those data are local or require a separate controlled transfer process.

## Release

| Field | Value |
|---|---|
| Package | `1c-nexus-infra` |
| Version | `1.0.1` |
| License | MIT |
| Required Python | `>=3.10` |
| Base branch | `main` |
| Remote repository | `https://github.com/PovAndy/1c-nexus-infra.git` |
| Previous verified commit | `c6ad066dbff22ae4e94ec1bb46c7b729e2ac5105` |

## Inventory

| Component | Responsibility |
|---|---|
| Graph V2 | Static source graph build and queries: `map_workspace_graph_v2.py`, `workspace_graph_v2_manager.py`, `query_workspace_graph_v2.py` |
| RAG | Knowledge writing and lifecycle: `kb_manager.py`, `rag_lifecycle_manager.py`, `data/knowledge_base.seed.json` |
| Prompt contract | Aligned rules in `.clinerules`, `.cursorrules`, `AGENTS.md`, `system_prompt.md`; checked by `validate_prompt_contracts.py` |
| BSL | Local candidate evaluation: `eval_bsl_candidate.py` |
| MCP | RSV Data and CodexTestBridge helpers, metadata cache, and Code Index configuration |
| Hygiene | `check_workspace_hygiene.py`, `scripts/test_*.py`, and safe configuration examples |

## Verified state

| Check | Result | Meaning |
|---|---|---|
| Prompt contract | PASS | Four consumers share a static prefix: SHA-256 `38aebec83ab7ffc5e6c3c677cae78c35214c2e79bb3ec77369a48b9f8435915b`, 17,016 UTF-8 bytes |
| Git hygiene | PASS | `.venv-gemini-bridge/`, `.code-index/`, and `docs/.code-index/` are not tracked |
| Branch before release | CLEAN | `main` matched `origin/main` before this release's changes |
| Verification host | INFO | WSL2 Linux `6.6.114.1-microsoft-standard-WSL2`, `x86_64`; system Python `3.12.3`; Git `2.43.0` |
| Full pytest | BLOCKED | The system `python3` does not have the `pytest` module; this is neither a test result nor evidence of a source defect |

The checks above establish local configuration and index hygiene. They do not
establish external MCP availability, 1C server health, EPF delivery, or
database-write authorization.

## Operating sequence

1. Clone the repository and install dependencies in a separate Python
   environment; never add that environment to Git.
2. Copy `.env.example` into an ignored local file only when needed; never
   publish key values.
3. Run `python3 scripts/validate_prompt_contracts.py` and
   `python3 scripts/check_workspace_hygiene.py`.
4. Run a RAG pre-flight and focused Graph V2 navigation before broad source
   searches.
5. Use path-scoped Git staging, diff review, and secret scanning for changes.
   Change 1C data only through an authorized application workflow.

## Known limitations

- This local snapshot does not replace checking active client versions, model
  provider state, or remote services at runtime.
- `tool_output_token_limit` and prompt-contract rules constrain local process;
  they do not prove token savings or remote model behavior.
- Running tests requires an interpreter with the dependencies from
  `pyproject.toml`; the system Python at snapshot time does not provide them.

Russian version: [WORKSPACE_STATE_2026-10-29.md](WORKSPACE_STATE_2026-10-29.md).
