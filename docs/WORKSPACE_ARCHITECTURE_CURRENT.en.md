# Current workspace architecture: English overview

This is the English navigation companion to the detailed Russian architecture
reference: [WORKSPACE_ARCHITECTURE_CURRENT.md](WORKSPACE_ARCHITECTURE_CURRENT.md).
The Russian document remains canonical when details differ.

## Purpose and safety boundary

`1c-nexus-infra` is a portable infrastructure repository for a 1C development
workspace. It provides static code navigation, RAG lifecycle tooling, BSL
candidate evaluation, validation utilities, and MCP bridge helpers. It does
not authorize database writes, mass corrections, direct production SQL writes,
or deployment by itself.

## Source-of-truth map

| Area | Primary artifact |
|---|---|
| Workspace architecture | `docs/WORKSPACE_ARCHITECTURE_CURRENT.md` |
| RAG seed and lifecycle tools | `data/knowledge_base.seed.json`, `scripts/kb_manager.py`, `scripts/rag_lifecycle_manager.py` |
| Static navigation | `scripts/map_workspace_graph_v2.py`, `scripts/workspace_graph_v2_manager.py` |
| BSL candidate checks | `scripts/eval_bsl_candidate.py` |
| MCP bridges | `scripts/call_test_bridge.py`, `scripts/rsvdata_http_mcp_proxy.py` |
| Workspace checks | `scripts/check_workspace_hygiene.py`, `scripts/validate_prompt_contracts.py` |

## Operating flow

1. Identify the active runtime profile and the target environment.
2. Run a local RAG pre-flight and use Graph V2 or focused navigation.
3. Inspect before changing 1C XML; validate after structural changes.
4. Separate read-only diagnostics from any write operation and obtain explicit
   authorization for writes.
5. Use path-scoped Git staging, validate staged content, scan it for secrets,
   then commit and verify the remote result.

## Security and reproducibility

- Secrets belong only in ignored local environment files; they must never be
  embedded in scripts, logs, RAG records, documentation, or commits.
- Graph artifacts, virtual environments, runtime caches, and generated logs
  are local operational data, not project source by default.
- A health check or static validation does not prove a live 1C deployment.

## GitHub snapshot

At the audit on 2026-08-21, `main` was
`91994799d39d6757874e51cba981c0fdcde802f9`. See the bilingual repository
audit for release boundaries and the paired x17 project:
[GITHUB_REPOSITORY_AUDIT_2026-08-21.md](GITHUB_REPOSITORY_AUDIT_2026-08-21.md).
