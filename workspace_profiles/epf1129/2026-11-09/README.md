# Снимок workspace / Workspace snapshot — 2026-11-09

Версия / Version: `workspace-2026.11.09`.

Это побайтовый снимок настроек и изменённых инфраструктурных инструментов
существующего workspace epf1129. Он не применяется автоматически. Модель,
права ролей, gateway guard и ограничения записи сохранены.

This is a byte-identical snapshot of settings and changed infrastructure tools
from the existing epf1129 workspace. It is not automatically applied. Model,
role permissions, gateway guards and database-write boundaries are retained.

## Структура / Layout

- `manifest.json`: SHA-256 и исходная область каждого файла / per-file hashes and source scope.
- `.codex/`, `.vscode/`, `.bsl-language-server.json`: project settings.
- `parent_workspace/`: parent workspace configuration.
- `git-local/info-exclude`: local Git artifact rules.
- `scripts/`: infrastructure helpers and fixture-based regression tests.
- `docs/`: original bilingual change records.
- `verification.json`: fresh verification results and remaining limits.

Исходные файлы правил содержат проектный префикс 15632 байта. Корневые
правила 1c-nexus-infra сохраняют собственный префикс 17016 байт. Не заменять
один контракт другим.

Snapshot rules use the 15632-byte project prefix. Repository-root rules retain
their own 17016-byte infrastructure prefix. These contracts are not interchangeable.

## Ограничения / Requirements

Конфигурации содержат исходные абсолютные пути и рассчитаны на существующий
workspace. Глобальные credentials, бизнес-источники, EPF и кэши проверок
не включены. Часть команд GATES.md зависит от существующей инфраструктуры
основного workspace. Не запускать здесь команды исправления или deployment.

Configuration retains original absolute paths and assumes an existing workspace.
Global credentials, business sources, EPF and verification caches are excluded.
Some GATES.md commands depend on the original workspace infrastructure.
Do not run repair/deployment commands from this snapshot directory.

Регрессионные тесты снимка выполняются из этого каталога интерпретатором
основного `.venv-gemini-bridge`; они используют временные fixtures.
Snapshot regression tests run from this directory using the original project's
`.venv-gemini-bridge` interpreter and isolated fixtures:

```bash
python -m unittest scripts.test_workspace_runtime_receipts scripts.test_sol_workspace_optimization scripts.test_stabilize_workspace -q
```

`python` в примере означает выбранный интерпретатор проектного venv,
а не системный Python. The example means the selected project-venv
interpreter, not the system Python.

Каталог ошибок / Error catalog:
[RU](../../../docs/WORKSPACE_CHECKPOINT_2026-11-09.md) ·
[EN](../../../docs/WORKSPACE_CHECKPOINT_2026-11-09.en.md).
