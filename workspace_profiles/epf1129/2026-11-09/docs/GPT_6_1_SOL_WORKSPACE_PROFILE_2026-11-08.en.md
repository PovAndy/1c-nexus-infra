# GPT-6.1 Sol workspace profile and safe cleanup

Both workspace Codex profiles now explicitly select `gpt-6.1-sol` with `high`
reasoning. The global user profile already selected this model; workspace
values make new-session behavior explicit. Existing role routing is preserved.

Local model metadata reports a 500000-token window with a 95% effective share
(475000 tokens). No manual `model_context_window` override is introduced.
The official model page distinguishes its larger API window from the default
500k Codex window. Growth compaction stays at 160000, `body_after_prefix`,
with a 1024-token tool-history budget. These are operating choices, not a
proven global cost optimum. API input above 272k has a full-request surcharge;
subscription Codex usage does not have that surcharge. Growth is not total input.

Sources:

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/codex/config-reference

Git's local untracked cache was enabled after its filesystem test passed.
Only generated/reference paths `/context/config-dumps/` and `/temp/tool_logs/`
were added to local `.git/info/exclude`. Files are retained, shared ignore
rules are unchanged, and new source/configuration/documentation remain visible.
VS Code watcher and repository-scan exclusions match those reference roots.

The full inventory found 109472 untracked files, including 91743 configuration
dump files; the earlier 829 count represented grouped status entries. Source
files are not garbage-collected to satisfy a status-count target. Measured Git
status improved from 16.532 seconds to 0.8588/0.3673/0.3494 seconds. Cache warm-up
and changing filesystem state prevent treating this as a universal 95% guarantee.
Staged content was fingerprinted and preserved.

Cleanup follows existing textual references from active gates and handovers,
handles cycles, protects explicit evidence and open files, and archives only
old disposable outputs. Source files, binaries, locks and audit/gate namespaces
are retained. Archive verification checks every SHA-256 before original-copy
removal, with inode/mtime/hash revalidation. Current manifests are in
`temp/audit/TEMP_SANITATION_PLAN.json` and `TEMP_SANITATION_REPORT.json`.

Preserving known inputs is not sufficient to prove all external state is stable.
Actual gates therefore run again. `gate_check.py --reverify --evidence-run NAME`
writes a new `temp/gates/NAME/` evidence set without altering original records.
Unsafe/reused names are rejected; old PASS evidence cannot mask a new failure.
The original canonical handover remains unchanged as explicitly requested.

The user explicitly requested termination of Extension Host PID 14084. Before
SIGTERM the helper checks boot ID, PID, process start time, UID, executable and
host type. This host owns the active Codex session, so a detached delayed
worker acts only after evidence is saved. No SIGKILL or unrelated process
termination is used. Its result is recorded in
`temp/audit/EXTENSION_HOST_RESTART_RESULT.json`.

Restarting a process does not guarantee a new RSS below 512 MiB. A V8 old-space
limit for filesystem MCP is not an Extension Host RSS cap. Unobserved replacement
hosts do not count as successful low-memory measurements. The report records
`PARTIAL_PRESERVED_WORK` when source preservation or runtime limits prevent
full convergence, rather than inventing success or evidence corruption.

External models and Block [28] remain paused. 1C databases and the EPF are unchanged.

Русская версия: [GPT_6_1_SOL_WORKSPACE_PROFILE_2026-11-08.md](GPT_6_1_SOL_WORKSPACE_PROFILE_2026-11-08.md).
