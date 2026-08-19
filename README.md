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

Секреты задаются только в `.env` (не коммитится); в репозитории — заглушка `.env.example`.

## Верификация (Verification)

```bash
python3 -m py_compile scripts/*.py
python3 scripts/validate_prompt_contracts.py
python3 -m pytest scripts -q
```

## Лицензия

MIT, Copyright (c) 2026 PovAndy. Подробнее — `LICENSE`.

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