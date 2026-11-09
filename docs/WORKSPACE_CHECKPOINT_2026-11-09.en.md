# Local workspace checkpoint — workspace-2026.11.09

This checkpoint stores settings, infrastructure utilities, regression tests and
documentation. Live workspace checks are distinct from snapshot validation.
Existing 1C business changes are not part of this commit.

## Contents and restoration

- [Settings and utility snapshot](../workspace_profiles/epf1129/2026-11-09/README.md).
- [Machine-readable error/solution catalog](../data/workspace_error_solution_catalog.json).
- [RAG record identifiers](../data/workspace_error_solution_rag_receipts.json).

The snapshot is bound to the existing epf1129 environment and retains original
absolute paths in Codex configuration. It is an archive, not an installed
Python package or a claim of portability to any directory. Map paths to the
target workspace before restoration. Global authentication and secrets remain
local and are not included.

The infrastructure package remains at 1.0.1. Workspace-checkpoint versioning
is independent of the Python package version. This task does not publish to GitHub.

## Verified changes

Profile: GPT-6.1 Sol, high reasoning, 160000 growth tokens with body_after_prefix,
and a 4096-token tool-history budget. The distinct project (15632 bytes) and
infrastructure (17016 bytes) static prefixes are preserved, not substituted.

Fixes cover dynamic Windows WSL gateway resolution, the target-specific
RSVDATA_MCP_URL_BASE02, and semantic validation of refreshed receipts while
retaining immutable artifact checks. MCP initialize/tools-list verifies the
protocol and exposed tools without invoking business tools.

Relevant checks comprise 19 regression tests, eight functional gates, prompt
parity, Python syntax, snapshot-manifest integrity, and RAG schema/index
validation. Actual checkpoint results are recorded in
`workspace_profiles/epf1129/2026-11-09/verification.json`.

## Error and solution ledger

RAG lifecycle `under_review` means technically checked and awaiting user
acceptance; `partial` identifies a remaining limitation. These are not 1C
database-write statuses. Repeatable technical errors have regression tests and
guards; RAG storage alone cannot guarantee an agent's future behavior.

| ID | Error | Solution | RAG lifecycle |
|---|---|---|---|
| NEXUS-ENV-001 | A refreshed execution receipt was treated as an immutable contract | Hash static sources/EPF; validate receipts by PASS, command, artifact and time. Reject invalid receipts while permitting valid refreshes. | under_review |
| NEXUS-ENV-002 | SCHEDULED was confused with a completed restart | Read the result after a background action and record structured STOP on errors. Do not attribute a later PID disappearance to a failed worker. | under_review |
| NEXUS-ENV-003 | A static Windows address became stale after WSL networking changed | Resolve the route at MCP startup, confirm the Windows WSL adapter, and bind the cache to gateway plus boot ID. | under_review |
| NEXUS-ENV-004 | TCP reachability and default gateway alone do not prove Windows host identity | Do not redirect authenticated endpoints without Windows-adapter confirmation; reject ambiguous routing and check the HTTP service separately. | under_review |
| NEXUS-ENV-005 | The generic RSV URL was ignored for the BASE02 target | Resolve RSVDATA_MCP_URL_BASE02 before proxy startup; preserve the base02 path and database guard. | under_review |
| NEXUS-ENV-006 | Codex CLI 0.139.0 failed to load a relative role path in merged configuration | Use an existing absolute config_file in this environment, preserve role model/sandbox, and test startup in both workspace directories. | under_review |
| NEXUS-ENV-007 | Unsupported Codex sections and flags copied from a prompt example | Use documented model/reasoning and top-level compaction/tool keys; verify with the installed CLI. | under_review |
| NEXUS-ENV-008 | Unknown BSL extension keys and invalid diagnostic parameter names/types | Use language-1c-bsl.*, complexityThreshold, maxLineLength and string-valued skipSupport; validate against the full JSON Schema. | under_review |
| NEXUS-ENV-009 | VS Code MCP configuration used mcpServers instead of servers | Respect client-specific formats: VS Code servers versus Codex mcp_servers. Validate cross-client configuration changes. | under_review |
| NEXUS-ENV-010 | A 512 MiB V8 old-space limit was treated as a total RSS cap | Do not infer RSS/GC/CPU guarantees from a heap flag; distinguish filesystem MCP from Extension Host and measure each process. | partial |
| NEXUS-ENV-011 | A stale PID could identify a different process | Before SIGTERM verify boot ID, UID, start ticks, executable and host type; do not apply an old PID-specific instruction to a replacement. | under_review |
| NEXUS-ENV-012 | Grouped Git status entries were mistaken for temporary-file counts | Distinguish status entries from git ls-files -z counts; classify untracked content and retain sources/configuration/docs and staged content. | under_review |
| NEXUS-ENV-013 | Local excludes were expected to shrink tracked differences | Do not use skip-worktree, deletion or source rollback to meet a metric. Large tracked diffs require a separate reviewed preservation decision. | partial |
| NEXUS-ENV-014 | Temporary cleanup could remove active evidence or unique work | Traverse referenced evidence with a visited set, retain open/recent/source files, and verify the full archive plus inode/mtime before removal. | under_review |
| NEXUS-ENV-015 | A copy-like filename does not prove duplicate content | Remove a copy only after matching an existing original and archiving it; retain unique contents. | under_review |
| NEXUS-ENV-016 | Compaction frequency and output-token share were mistaken for monetary savings | Account for input, cached input and output separately; do not double-count reasoning or assert a 160k optimum without prices and comparable telemetry. | under_review |
| NEXUS-ENV-017 | Unmeasured formulas were used to promise 350 ms/0.1 s/95% bounds | Separate assumptions from measurements; Git cache warm-up and reading a handover do not measure full client startup. | partial |
| NEXUS-ENV-018 | An assumed 1024 budget contradicted the existing 4096 values in both profiles | Re-read configuration before changes, preserve the user's budget and align only dynamic hints below the prefix boundary. | under_review |
| NEXUS-ENV-019 | Pydantic v1 syntax and regex anchors did not match installed v2 | Use pattern= and model_dump(); anchor complete regex alternatives and use supported ^/$ syntax. | under_review |
| NEXUS-ENV-020 | System Python or direct test-file execution could not resolve dependencies/scripts | Use the active .venv-gemini-bridge interpreter and -m unittest. Resolve Log against silent_runner's actual root rather than assuming the test cwd. | under_review |
| NEXUS-ENV-021 | Transport closed or a wrong index alias could be mistaken for a missing file | Distinguish transport failure from file absence; use known repository aliases and a bounded read-only fallback instead of retry loops. | partial |
| NEXUS-ENV-022 | Large search/JSON outputs inflated context | Save full results locally and extract relevant fields only; wrap CLI commands with silent_runner's three-line protocol. | under_review |

## Evidence boundaries

Large tracked differences, retained untracked source and unknown full-client
startup latency remain visible. Ignore rules cannot shrink tracked diffs.
A scheduled restart or a V8 old-space flag does not establish runtime success.
Historical PASS is not a substitute for current verification.

Private knowledge_base.json, runtime logs, EPF binaries, archives, business
sources and .env values are excluded. External models and Block [28] remain paused.

[Русская версия](WORKSPACE_CHECKPOINT_2026-11-09.md)
