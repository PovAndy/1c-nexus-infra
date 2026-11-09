# Acceptance Ledger: 1C-Nexus Operational Gates

Каждая команда исполняется `scripts/gate_check.py` без shell-интерпретации. Доказательство сохраняет только метаданные и хеш ограниченного результата. Изменение команды или ожидания требует новой перепроверки.

## GATE-1-rag-preflight
CHECK: python3 scripts/silent_runner.py --expect-regex '^RAG_SEARCH_PASS' -- python3 scripts/kb_manager.py --search "epf pipeline verifier deployment"
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-1-rag-preflight.json

## GATE-2-server-deployment
CHECK: python3 scripts/silent_runner.py --expect-regex '^DEPLOY_SHA256_MATCH' -- python3 scripts/verify_epf_pipeline.py --check-deploy
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-2-server-deployment.json

## GATE-3-bsl-linter
CHECK: python3 scripts/silent_runner.py --expect-regex '^BSL_AUTO_LINT_PASS.*cost=0' -- python3 scripts/eval_bsl_candidate.py --auto
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-3-bsl-linter.json

## GATE-4-ledger-self-test
CHECK: python3 scripts/silent_runner.py --expect-regex 'PASS gate-check self-test' -- python3 scripts/gate_check.py --self-test
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-4-ledger-self-test.json

## GATE-5-prompt-contract
CHECK: python3 scripts/silent_runner.py --expect-regex 'PASS prompt-contract' -- python3 scripts/validate_prompt_contracts.py
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-5-prompt-contract.json

## GATE-6-infra-unit-tests
CHECK: python3 scripts/silent_runner.py --expect-regex OK -- python3 -m unittest scripts.test_gate_check scripts.test_kb_manager scripts.test_verify_epf_pipeline scripts.test_mask_payload scripts.test_distill_sessions scripts.test_rsvdata_http_mcp_proxy scripts.test_hooks scripts.test_prompt_contracts scripts.test_reconcile_reality scripts.test_zcl_protocol scripts.test_zcl_latency_policy scripts.test_context_governance
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-6-infra-unit-tests.json

## GATE-7-infra-syntax
CHECK: python3 scripts/silent_runner.py -- python3 -m py_compile scripts/gate_check.py scripts/kb_manager.py scripts/verify_epf_pipeline.py scripts/test_verify_epf_pipeline.py scripts/mask_payload.py scripts/rsvdata_http_mcp_proxy.py scripts/distill_sessions.py scripts/validate_prompt_contracts.py scripts/prompt_contract_runtime.py scripts/test_prompt_contracts.py scripts/reconcile_reality.py scripts/hooks/stop_hook_gate_check.py scripts/silent_runner.py scripts/session_breaker.py scripts/test_zcl_protocol.py scripts/verify_zcl_latency.py scripts/test_zcl_latency_policy.py scripts/context_governance.py scripts/test_context_governance.py
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-7-infra-syntax.json

## GATE-8-rag-integrity
CHECK: python3 scripts/silent_runner.py --expect-regex 'OK kb_manager' -- python3 scripts/kb_manager.py --validate
EXPECT: exitcode=0; regex=^\[PASS\] Exit: 0 \|
EVIDENCE: temp/gates/gate-8-rag-integrity.json

### GATE 4: Full Regression Reverify

- CHECK — `python3 scripts/silent_runner.py python3 scripts/gate_check.py --reverify`
- EXPECT — exit code `0` после повторного запуска всех исполняемых ворот выше.
- EVIDENCE — `temp/gates/*.json`; trace RAG — `temp/rag_preflight_trace.json`.

### BSL candidate-specific check

- Для конкретного BSL-кандидата запускать `python3 scripts/silent_runner.py python3 scripts/eval_bsl_candidate.py <Candidate.bsl>`.
- Нулевая стоимость (`Cost=0`) обязательна для приемки; отсутствие OneScript или ненулевая стоимость означает `STOP`.
- В общий ledger включён детерминированный regression-тест evaluator’а, потому что один общий tracked-кандидат для всех задач отсутствует.

### ZCL latency acceptance (отдельно от 8 функциональных ворот)

Политика: `.codex/zcl_latency_policy.json`. CLI с коротким выводом: дополнительные расходы p95 ≤ 30 мс и p99 ≤ 50 мс; механизм внутри процесса: p99 ≤ 15 мс. Время команды исключается; большие логи требуют отдельного профиля. Проверка отклоняет старые (>24 часов), неполные или не соответствующие SHA-256 перехватчика измерения.

```bash
python3 scripts/silent_runner.py --expect-regex "^ZCL_LATENCY_PASS" -- python3 scripts/verify_zcl_latency.py
```

English: latency acceptance is independent of the eight functional gates. Small-output CLI added p95 ≤ 30 ms, p99 ≤ 50 ms; in-process added p99 ≤ 15 ms. Command duration is excluded; large-output profiles are separately calibrated.
