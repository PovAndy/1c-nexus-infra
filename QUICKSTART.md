# QUICKSTART

## 1. Клонирование / расположение

```bash
git clone https://github.com/PovAndy/1c-nexus-infra.git
cd 1c-nexus-infra
```

## 2. Окружение

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .          # ставит entrypoints: 1c-graph, 1c-rag, 1c-eval, 1c-prompt-check
cp .env.example .env                # заполните свои значения (секреты — только локально)
```

Корень фреймворка:

```bash
export NEXUS_WORKSPACE_ROOT="$(pwd)"   # если не задан — берётся каталог модуля
```

## 3. Проверка контракта и здоровья

```bash
python3 scripts/validate_prompt_contracts.py    # OMVL-префикс байт-идентичен во всех 4 потребителях
python3 scripts/check_workspace_hygiene.py      # чистота каталога (пути, секреты, артефакты)
python3 -m py_compile scripts/*.py              # синтаксис
python3 -m pytest scripts -q                    # тесты
```

## 4. RAG: инициализация и жизненный цикл

```bash
python3 scripts/kb_manager.py --task "seed" --status under_review   # создаёт knowledge_base.json из seed (схема 2.0)
# статусы FSM: under_review / unstable / success / failed / partial
# подтверждение пользователя закрывает цикл:
#   "Заработало"/"OK"  -> --status success
#   "Ошибка"           -> --status failed
```

## 5. Graph V2

```bash
python3 scripts/map_workspace_graph_v2.py           # построение графа
python3 scripts/workspace_graph_v2_manager.py --help
python3 scripts/query_workspace_graph_v2.py --func "СформироватьПакетныйЗапрос"
```

## 6. BSL-оценка кандидатов

```bash
python3 scripts/eval_bsl_candidate.py --help
```

## 7. MCP-мосты (опционально)

```bash
python3 scripts/rsvdata_http_mcp_proxy.py --help
python3 scripts/call_test_bridge.py --help
```

## 8. Code Index daemon

```bash
export CODE_INDEX_HOME="$(pwd)/tools/code-index-mcp"
code-index daemon status --json      # health; порт из daemon.json (по умолчанию 44369)
```

## 9. Секреты и публикация

- `.env` и `.env.*.local` в git не попадают — используйте `.env.example`.
- Никогда не коммитьте API-ключи, пароли, токены, raw-ответы 1С и персональные данные.
- Перед push: `python3 scripts/check_workspace_hygiene.py` и повтор `validate_prompt_contracts.py`.