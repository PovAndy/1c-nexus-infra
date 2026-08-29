# 1c-nexus-infra

> Автономная инфраструктура рабочей среды 1С-разработчика: Graph V2, RAG FSM 2.0, prompt-контракт, Best-of-N BSL-оценка и MCP-мосты. Standalone, portable, без хардкод-путей и секретов.

## Состав (Composition)

| Компонент | Назначение |
|---|---|
| **Graph V2** | Статическая навигация по кодовой базе: `map_workspace_graph_v2.py` — построение графа, `workspace_graph_v2_manager.py` — менеджер/вызовы, `query_workspace_graph_v2.py` — поиск вызовов и контр-контролей |
| **RAG FSM 2.0** | Жизненный цикл решений: `kb_manager.py` — единый писатель `knowledge_base.json` (fcntl lock, схема 2.0, seed-инициализация), `rag_lifecycle_manager.py` — статусы FSM (`under_review`/`unstable`/`success`/`failed`/`partial`) |
| **Prompt Cache Contract** | Неизменный developer-префикс `OMVL_STATIC_PREFIX_V1` в `.clinerules`, `.cursorrules`, `AGENTS.md`, `system_prompt.md`; проверка `validate_prompt_contracts.py` |
| **Best-of-N BSL** | `eval_bsl_candidate.py` — оценка BSL-кандидатов; запасные роли через `omvl_llm_runtime.py`, `omvl_resilience.py`, `research_advisor.py` |
| **MCP-мосты** | `rsvdata_http_mcp_proxy.py` (RSV Data), `call_test_bridge.py` (CodexTestBridge), `silent_metadata_cache.py`; окружение Code Index в `tools/code-index-mcp/` |
| **Среда** | `check_workspace_hygiene.py`, `data/knowledge_base.seed.json`, тесты `scripts/test_*.py` |

## Быстрый старт (Quick start)

```bash
export NEXUS_WORKSPACE_ROOT="$(pwd)"        # корень фреймворка (если не задан — берётся каталог модуля)
python3 -m pip install -e .
python3 scripts/validate_prompt_contracts.py # проверка байт-идентичности OMVL-префикса
python3 scripts/kb_manager.py --task "seed" --status under_review
```

## Файлы (Layout)

```
1c-nexus-infra/
├── .clinerules / .cursorrules / AGENTS.md / system_prompt.md   # байт-идентичный OMVL-префикс
├── data/knowledge_base.seed.json                                # RAG-сид (схема 2.0)
├── scripts/                                                     # все скрипты и тесты
├── docs/                                                        # архитектура и протоколы
├── opencode.example.json                                         # sanitized Wan25 aliases
├── tools/code-index-mcp/                                        # конфиг демона Code Index
└── .github/hooks/omvl-workspace.json                            # пример hooks VS Code
```

## Переменные окружения (Environment)

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `NEXUS_WORKSPACE_ROOT` | Корень фреймворка | каталог модуля |
| `NEXUS_KB_PATH` | Путь к БЗ RAG | `knowledge_base.json` |
| `RSVDATA_MCP_URL` | Endpoint RSV Data MCP | `http://127.0.0.1:8080/hs/rsvdata/mcp` |
| `LDS_1C_BRIDGE_URL` | Endpoint CodexTestBridge | `http://127.0.0.1:18080/test-bridge` |
| `LDS_NETWORK_PROXY_IP` | Прокси для WSL без Mirrored Networking | — |
| `NEXUS_FORM_VALIDATOR` / `NEXUS_PYTHON_BIN` | Внешние валидаторы (опционально) | — |
| `WAN25_GATEWAY_ENABLED` | Единый gateway для OMVL; `0` сохраняет role-specific routes | `0` |
| `WAN25_API_KEY` | Локальный секрет общего gateway | — |
| `CODER_API_BASE_URL` | OpenAI-compatible WAN25 endpoint | `https://apiai.wan-2-5.pro/v1` |
| `WAN25_RPM_LIMIT` / `WAN25_MIN_INTERVAL_SECONDS` | Общий лимит и минимальный интервал | `10` / `6.0` |

Секреты задаются только в `.env` (не коммитится); в репозитории — заглушка `.env.example`.
URL gateway, имена моделей и sanitized placeholders разрешены в примерах. Текущий
проверенный срез и runbook: [RU checkpoint](docs/WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.md)
и [EN checkpoint](docs/WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.en.md).

## Верификация (Verification)

```bash
python3 -m py_compile scripts/*.py
python3 scripts/validate_prompt_contracts.py
python3 -m pytest scripts -q
```

## Лицензия

MIT, Copyright (c) 2026 PovAndy. Подробнее — `LICENSE`.

## WAN25 gateway (English)

The sanitized `.env.example` and `opencode.example.json` may contain the public
gateway URL, provider model IDs, aliases, and empty placeholders. They must not
contain real API keys, passwords, tokens, private endpoints, or runtime data.
`WAN25_GATEWAY_ENABLED=1` enables one shared gateway/key for OMVL; `0` keeps
role-specific rollback routes. The shared limiter enforces 10 RPM and at least
6 seconds between calls, with bounded `429` retries and fallback routing.

Current verified bilingual snapshot and Codex runbook:
[Russian checkpoint](docs/WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.md) and
[English checkpoint](docs/WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.en.md).

---

# 1c-nexus-infra (English)

> Standalone 1C developer workspace infrastructure: Graph V2, RAG FSM 2.0, prompt-cache contract, Best-of-N BSL evaluator and MCP bridges. No hardcoded paths, no secrets in source.

## Components

- **Graph V2** — static call-graph navigation (`map_workspace_graph_v2.py`, `workspace_graph_v2_manager.py`, `query_workspace_graph_v2.py`).
- **RAG FSM 2.0** — decision lifecycle with a single locked writer `kb_manager.py` (schema 2.0, seed bootstrap) and FSM statuses via `rag_lifecycle_manager.py`.
- **Prompt Cache Contract** — byte-identical `OMVL_STATIC_PREFIX_V1` prefix across the four consumer files, validated by `validate_prompt_contracts.py`.
- **Best-of-N BSL** — `eval_bsl_candidate.py` BSL candidate evaluation with fallback roles (`omvl_llm_runtime.py`, `omvl_resilience.py`, `research_advisor.py`).
- **MCP bridges** — `rsvdata_http_mcp_proxy.py`, `call_test_bridge.py`, `silent_metadata_cache.py`; Code Index daemon config under `tools/code-index-mcp/`.
- **Hygiene** — `check_workspace_hygiene.py`, seed `data/knowledge_base.seed.json`, tests `scripts/test_*.py`.

## Quick start

```bash
export NEXUS_WORKSPACE_ROOT="$(pwd)"   # framework root (defaults to the module dir)
python3 -m pip install -e .
python3 scripts/validate_prompt_contracts.py
python3 scripts/kb_manager.py --task "seed" --status under_review
```

## License

MIT, Copyright (c) 2026 PovAndy.
