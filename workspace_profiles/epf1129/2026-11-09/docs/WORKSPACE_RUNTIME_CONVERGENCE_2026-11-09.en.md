# GPT-6.1 Sol workspace verification — 2026-11-09

The continuation ingested the 852-byte `temp/TASK_HANDOVER.md`; historical
rollouts were not read. Editing workspace files cannot clear history already
loaded by the client. Full startup latency needs client measurement, not just
the time required to read a small handover file.

The EPF baseline remains
`67976fa92cb140f9f6627ec1fcc61dd99a230fce636a80cc4d99c2ec2ddb79fd`,
matching both handovers. BSL/XML sources and the binary are static contracts.
Execution receipts are mutable and require semantic validation.

The previous delayed restart failed before SIGTERM because it incorrectly
treated refreshed deployment/gate JSON as immutable. PID 14084 subsequently
disappeared independently; the script does not claim to have terminated it.
The receipt validator now accepts valid refreshes and rejects FAIL, command
mismatches, artifact drift, stale verification, and changed static sources.
The background helper records contract errors in its result file.

The current route gateway is `192.168.32.1`, independently confirmed as a
Windows `vEthernet (WSL)` address. The target endpoint responded through
Microsoft IIS with HTTP 401. TCP reachability alone was not treated as host
identity proof. MCP launchers resolve the default route on startup and bind
their Windows-host cache to gateway and Linux boot ID; a changed route is
revalidated against Windows adapters. Unverified redirection fails closed.

Local root/project Codex configuration wraps the existing RSV and CodexTestBridge
commands. Original global commands were checked and retained; credentials,
read-only controls and `/base02/...` paths are preserved. CodexTestBridge keeps
localhost as primary and receives a dynamic IP fallback. Running MCP processes
need a fresh launch to consume these settings.

RSV's BASE02-specific `RSVDATA_MCP_URL_BASE02` takes precedence over its generic
URL. The launcher now resolves that target-specific host too, before the server
loads its env file, while retaining the BASE02 path guard. Protocol preflight
passed `initialize/tools/list`: RSV exposed 8 tools and CodexTestBridge 1.
No business tool was invoked.

Local Git exclusions cover only requested generated/reference paths, EPF
artifacts, ADS sidecars and copies. The shared ignore file is unchanged.
Untracked sidecars and unreferenced logs are archived with verified member
hashes before removal. Copy artifacts are removed only when identical to an
existing original; unique content is preserved. Existing archives, environments,
Git internals and package/index caches are excluded from duplicate discovery.

The initial audit found 358 tracked changes, about 42 MB of text diff and
69 MB of binary diff. Local ignore rules cannot shrink tracked differences.
The task does not commit, revert, or use skip-worktree to conceal that work.

The profile remains `gpt-6.1-sol`, reasoning `high`, 160000 growth tokens,
`body_after_prefix`, and the existing 4096-token tool-history budget, with no manual
context-window override. The official model reference distinguishes API
capacity and the default 500k Codex window:
https://developers.openai.com/api/docs/models/gpt-6.1-sol

The prompt's equations do not establish a 350 ms startup or 0.1 s Git bound
without measured coefficients and client telemetry. Current state is recorded
in `temp/audit/FINAL_CONVERGENCE_STATUS.json`; archive and gateway evidence are
in `FINAL_SANITATION_ARCHIVE.json` and `HOST_GATEWAY_CACHE.json` in that folder.
`FINAL_CONVERGENCE_VERIFIED.json` is emitted only when every acceptance condition
is actually met, including client confirmation of clean startup.

Start the next Codex chat from the handover and current status, then measure
startup and MCP connectivity. External models and Block [28] remain paused;
a new business stage requires separate instructions.

Русская версия: [WORKSPACE_RUNTIME_CONVERGENCE_2026-11-09.md](WORKSPACE_RUNTIME_CONVERGENCE_2026-11-09.md).
