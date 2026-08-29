# Контрольная точка инфраструктуры — 2026-08-29

Актуальная русская документация публичного инфраструктурного checkpoint.
English companion: [WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.en.md](WORKSPACE_RUNTIME_CHECKPOINT_2026-08-29.en.md).

## Что опубликовано

Публичный репозиторий содержит обезличенный инфраструктурный слой: Graph V2,
RAG FSM, prompt contract, resilience runtime, WAN25 limiter, sanitized env и
OpenCode example. Локальный workspace `epf1129` не публикуется целиком.

Разрешено публиковать URL gateway, provider model IDs, OpenCode aliases и пустые
placeholders. Запрещены реальные API keys, пароли, токены, private endpoints,
RAG/runtime state, базы 1С, логи и приватная топология.

## WAN25 routing

`WAN25_GATEWAY_ENABLED=1` направляет OMVL-роли через единый
`https://apiai.wan-2-5.pro/v1` и `WAN25_API_KEY`. Значение `0` оставляет каждой
роли собственный rollback endpoint и credential slot. Шаблоны находятся в
`.env.example` и `opencode.example.json`.

| Role | Primary | Fallback |
|---|---|---|
| Orchestrator | `openai/gpt-5.6-sol` | `openai/gpt-5.6-luna` |
| Coder Luna | `openai/gpt-5.6-luna` | `claude-3-7-sonnet` |
| Critic | `vanchin/deepseek-v4-pro` | `zhipu/glm-5-3` |
| Librarian | `moonshot/kimi-k3` | `qwen/qwen3.6-plus` |
| Scribe | `qwen/qwen3.6-flash` | `qwen/qwen3.6-plus` |
| Forensics | `qwen/qwen3.6-plus` | `zhipu/glm-5-3` |

Общий limiter использует атомарное состояние и межпроцессную блокировку:
максимум 10 RPM, интервал не менее 6 секунд, `429` retry через 7/14 секунд,
переход на fallback при переполнении очереди.

## Подтвержденное состояние источника

Локальный `epf1129` commit:
`78e86c5b03c4663890313cf4649f6be102053dff`. Проверены 21 тест resilience/MCP,
prompt contract 16 996 байт, env contract, hooks, hygiene и RAG schema 2.0.
Авторизованный WAN25 smoke прошел для Orchestrator, Coder Luna, Critic,
Librarian, Scribe и Forensics. Это evidence локального источника, а не обещание
доступности gateway для каждого будущего окружения.

## Runbook через Codex

Команды запускаются из клонированного публичного репозитория. Секреты не
передаются Codex в prompt или CLI arguments.

```bash
export NEXUS_WORKSPACE_ROOT="$(pwd)"
PY=python3
$PY scripts/validate_prompt_contracts.py
$PY scripts/kb_manager.py --validate
$PY scripts/workspace_graph_v2_manager.py check --deep
```

Prompt read-only pre-flight:

```text
Проведи read-only pre-flight текущей рабочей среды. Выполни локальный поиск по RAG, затем проверь env contract, Graph V2 и prompt contract. Не читай и не выводи значения секретов. Раздели PASS/WARN/FAIL и не меняй файлы.
```

Заполнение выполняется локально на основе `.env.example`:

```bash
cp .env.example .env
${EDITOR:-vi} .env
chmod 600 .env
```

Для WAN25 заполнить `WAN25_API_KEY` в локальном `.env` и установить
`WAN25_GATEWAY_ENABLED=1`. Для rollback установить `0`. После изменения
перезапустить Codex/MCP/OpenCode.

Prompt live-smoke:

```text
Проведи минимальный live-smoke настроенных OMVL-ролей через штатный runtime и общий limiter. Не выводи ключ, полный ответ модели или приватные заголовки. Покажи только role, model alias, primary/fallback route и PASS/FAIL. Не повторяй запрос вручную вне limiter.
```

Codex CLI:

```bash
codex exec -C "$NEXUS_WORKSPACE_ROOT" "Проведи read-only аудит конфигурации WAN25 и верни PASS/WARN/FAIL без раскрытия секретов"
```

Публикация выполняется только через exact allowlist и после свежего clone:

```bash
git diff --check
git status --short
git add -- <точный-allowlist-файлов>
git diff --cached --check
git commit -m "checkpoint(workspace): publish bilingual WAN25 runtime state"
git push origin main
```

Перед push проверить staged secret scan, bilingual links, `git fsck --full`,
remote SHA и fresh clone. Локальный RAG и Graph state не копируются в public repo.
