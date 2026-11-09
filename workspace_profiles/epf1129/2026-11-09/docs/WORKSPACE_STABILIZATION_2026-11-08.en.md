# Workspace stabilization — 2026-11-08

## Applied changes

The changes affect development infrastructure. They do not modify 1C
databases, BSL/XML sources, or `build/compiled.epf`.

- BSL diagnostics run `onSave`, using supported parameter names
  `complexityThreshold` and `maxLineLength` with thresholds 25/20/140.
  `skipSupport` uses the supported string value `withSupport`.
- Project and parent VS Code settings exclude generated files, logs, Git
  internals and virtual environments from file watching. Auto-save, Git
  autorefresh, C/C++ IntelliSense and BSL trace are disabled.
- VS Code MCP configuration uses `servers`, exposing only `filesystem`.
  Its `NODE_OPTIONS` caps V8 old-space at 512 MiB for that MCP process.
  This does not impose a 512 MiB RSS limit on the IDE Extension Host.
- Both Codex workspace profiles use a 160000-token growth threshold with
  `body_after_prefix`. The tool-history budget remains 1024 tokens. Local
  overrides disable `mempalace` and `sequential-thinking` for new sessions;
  unrelated global settings remain intact.
- The existing token-worker role now uses an absolute configuration path.
  This resolves the observed Codex CLI 0.139.0 error involving relative
  `AbsolutePathBuf` deserialization. The role's model and permissions are
  preserved. CLI startup was tested after the change.
- Context governance and the dynamic rule sections are aligned; the protected
  static prefix is preserved.

## Lossless archive

`archive/cleanup_20261106T050709377745Z.tar.gz` contains 4158 tool-log and
gate-evidence files older than 24 hours at cleanup time. Recent files and
active outputs were retained. Every member was SHA-256 verified before its
original local copy was removed, and reverified on 2026-11-08.

- Original size: 1,427,281,664 bytes.
- Archive size: 7,046,043 bytes.
- SHA-256: `40386411ce3e53bb7da7a22b15dbd6818e97e23d9bd2ec9e0483ce5002ff4ad7`.
- Original paths and hashes are recorded in the archived `MANIFEST.json`.

Restore exact required members into a separate directory and verify their
hashes. Restored historical gate evidence does not replace a fresh gate run.
Configuration backups and the action ledger are in `temp/audit/backups_*`
and `temp/audit/STABILIZATION_ACTIONS.json`.

## Verification and remaining limits

Read-only configuration and runtime reporting:

```bash
.venv-gemini-bridge/bin/python scripts/silent_runner.py .venv-gemini-bridge/bin/python -m scripts.stabilize_workspace
```

Exit 2 with `PARTIAL_RETRY_REQUIRED` preserves observations outside the target
bounds instead of inventing success. Existing work is not deleted to meet a
Git-status count. Successful gates do not imply Extension Host RSS ≤512 MiB.
An unobserved host is not proof of a low-memory running host.

No supported workspace setting establishing a hard 512 MiB Extension Host RSS
limit was confirmed in the installed VS Code. A V8 heap limit is a different
quantity and can cause OOM if set too low. Running IDE and session-owned MCP
processes were not terminated. Cleanup is limited to named MCP candidates with
PPID 1 inside this workspace, after PID/start-time revalidation; none were
found in the executed runs.

Kernel caches were not dropped. The credited `reclaimed_memory_mb=0` is a
conservative zero, not a measured causal memory saving. Neither a CPU ceiling
of 8% nor global token-cost optimality at 160k is established.

After saving work, run VS Code's `Developer: Reload Window`, start a new Codex
session, and repeat measurements. Use `Developer: Show Running Extensions`
and an Extension Host profile to investigate remaining memory growth. The
script does not automatically restart or close the active IDE.

Current evidence is in `temp/audit/STABILIZATION_REPORT.json`; archive checks
are in `temp/audit/STABILIZATION_ARCHIVE_REVERIFY.json`. Run the regression
checks with `python -m unittest scripts.test_stabilize_workspace -q` using
the project interpreter and `silent_runner.py`. Fresh eight-gate acceptance
is required before session handover. The compiled EPF hash is compared with
`docs/ACTIVE_HANDOVER.md`; matching provenance is not rewritten.

External models and Block [28] remain paused.

Русская версия: [WORKSPACE_STABILIZATION_2026-11-08.md](WORKSPACE_STABILIZATION_2026-11-08.md).
