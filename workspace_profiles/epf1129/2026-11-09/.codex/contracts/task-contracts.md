# Demand-loaded task contracts / Контракты по запросу

Load only the section matching the explicit task kind. This file is not an
automatically registered Agent Skill: installed skills retain their own SKILL.md
metadata, triggers and required references. Do not load this complete catalogue
for a simple question. Runtime facts belong below PROMPT_CACHE_BOUNDARY.

## infrastructure

Goal: deliver scoped, reproducible infrastructure changes. Preserve user edits,
secrets, database targets, role authentication and provider routing unless the
request explicitly includes their modification. Resolve the active project and
its .venv-gemini-bridge interpreter from the actual filesystem. Inspect the model
profile without assuming it describes the already-running session. Reality
Reconciliation findings remain visible; historical PASS is not current evidence.
Acceptance: focused diff, relevant tests, prompt parity when applicable, Graph
freshness for Python/MCP changes, and current gate results with blockers reported.
No automatic Git staging or publication unless requested; then exact allowlists
only, excluding secrets, business sources and private RAG exports. Public
documentation is bilingual Russian/English. Archive and archive are excluded.

## bsl

Goal: verified, metadata-grounded BSL changes within assigned files. Inspect XML
through the relevant installed inspect skill; use form-edit for form changes and
corresponding validators after structural edits. Do not read ObjectModule.bsl in
full. Metadata cache/bridge is the truth anchor. Server procedures and server
modules forbid Состояние, Предупреждение, Вопрос, ОткрытьФорму, Показать* and
Сигнал. Use .Ссылка, КАК and external query parameters; forbid .Ref, SQL AS,
Запрос.Выполнить(Параметры) and unsafe dynamic Выполнить(). Destroy temporary
tables immediately after last use. Unverified code remains [UNVERIFIED_DRAFT].
Acceptance: eval_bsl_candidate.py --auto Cost=0, applicable validators and build
proof, current gate results. Missing syntax/metadata evidence blocks acceptance.
Candidate generation is not a prescribed hidden reasoning trace; use evaluator
findings rather than arbitrary counts of internal alternatives.

## epf

Goal: reproducible EPF delivery from approved sources. Apply bsl constraints when
BSL changes; use epf-build and epf-validate skills when their triggers match.
For requested server delivery establish intended target and authorized transport.
Acceptance: source/build/server hashes verified by verify_epf_pipeline.py and
all relevant gates reverified. A local build does not prove deployment; denied
SMB access is a blocker, not a reason to weaken the gate or fabricate evidence.
Do not perform business-data writes as part of deploying an artifact.

## database

Goal: target-specific diagnosis. Establish actual target, bridge_url and
current_database() before claims; distinguish active contour from historical
copies. All x1_XX sources are read-only. Health, Metadata, Describe, Query and
Preview must have no side effects. Live writes, DML/DDL, posting, TestAndFix,
production target changes and destructive operations require explicit approval.
Acceptance: target-matched evidence, read-only Preview, stated ambiguity and
separate authority for any repair. Successful fallback is not target proof.

## research

Goal: resolve public factual uncertainty using primary sources. Only sanitized
questions reach external helpers. No private Graph/RAG, source code, local
topology, database contents, secrets or raw logs leave the local contour.
Acceptance: links support each externally grounded claim, inference is labelled,
and public guidance is distinguished from actual local behavior. Use official
OpenAI documentation for OpenAI product/model claims. A cache marker in Markdown
is not an API cache breakpoint and local parity cannot prove cache hits.

## review

Goal: independent read-only judgment of the supplied diff and evidence. Do not
inherit the implementer's conclusions or edit files. Report material defects,
missing proof, severity and checkable acceptance gates. Restrict delegation to
independent scoped work; unavailable helpers are disclosed, not blockers for
safe local evidence collection. Acceptance never follows from helper confidence.

## documentation

Goal: accurate bilingual durable documentation. Request a sanitized Scribe draft
when available, without sending internal instructions or confidential data.
On timeout/429/invalid response, record the reason and continue locally. Describe
current commands, artifacts, limitations and recovery rather than copying stale
PASS statements. RAG lifecycle uses kb_manager.py only: under_review for draft,
unstable for verified implementation, success after explicit user confirmation.
Acceptance: Russian and English coverage, no secrets, no unverified claims.
