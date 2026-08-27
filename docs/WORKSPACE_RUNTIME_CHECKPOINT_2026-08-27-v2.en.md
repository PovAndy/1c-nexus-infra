# Working Environment Infrastructure Checkpoint — 2026-08-27 v2

Previous public checkpoint: `docs/WORKSPACE_RUNTIME_CHECKPOINT_2026-08-27.md`.
Russian version: `docs/WORKSPACE_RUNTIME_CHECKPOINT_2026-08-27-v2.md`.

## Scope

This document records only portable and anonymized facts about repository
configuration, validators, hooks, and publication policy.

## Changes

- Added a fail-closed validator for local `.env`: it checks file permissions,
  variable duplicates, `target/path` consistency, and read-only guards without
  outputting secret values.
- `SessionStart` now performs the env-contract check first, then Reality
  Reconciliation, and non-blockingly schedules a Graph V2 update.
- Hygiene checks now block any virtualenvs with the `.venv` prefix and
  code-index artifacts from entering Git.
- Added anonymized unit tests for the validator and a hook-order test.
- `.gitignore` rules continue to protect local env/IDE/agent files and
  diagnostic artifacts.

## Checks

- `py_compile` of infrastructure scripts;
- unit tests for validator and hooks;
- hygiene check of tracked artifacts;
- `diff --check` and standard Git hooks;
- Graph V2 deep-check.

## Public Boundary

Only infrastructure scripts, rules, hooks, tests, and this documentation are
included in the publication. Local `.env` files, keys, passwords,
RAG/`knowledge_base.json`, Graph/runtime indexes, databases, BSL/SQL sources,
logs, and build artifacts are excluded.

## Evidentiary Limitations

This public checkpoint does not prove availability or correctness of a remote
1C database, HTTP publication, or physical SQL schema. It records only
statically verifiable tools and policies of the local working environment.
