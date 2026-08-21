# GitHub audit: project and workspace / Аудит GitHub: проект и рабочая среда

**Audit date / Дата аудита:** 2026-08-21. This is a read-only snapshot of the
default branches available on GitHub. It does not claim that uncommitted local
files were uploaded.

Это read-only снимок default-веток, доступных на GitHub. Он не утверждает,
что локальные незакоммиченные файлы были опубликованы.

| Scope / Контур | Repository / Репозиторий | Verified remote `main` / Подтверждённый удалённый `main` | Version and boundary / Версия и граница |
|---|---|---|---|
| 1C x17 project / Проект 1С x17 | [`PovAndy/1c-x17-consolidator`](https://github.com/PovAndy/1c-x17-consolidator) | `29cc956e1ac9f38c3c4b4dbf28edd32625caa187`, 2026-08-19 21:11:17 +03:00 | Source declares `v25-123.03`. The local `epf1129` source declares `v25-123.06` and has uncommitted changes in the object module and the main form; it is not proven uploaded. |
| Workspace infrastructure / Инфраструктура рабочей среды | [`PovAndy/1c-nexus-infra`](https://github.com/PovAndy/1c-nexus-infra) | `91994799d39d6757874e51cba981c0fdcde802f9`, 2026-08-20 11:22:38 +03:00 | The remote repository is present and its checked-out clone is clean. This audit does not equate it with arbitrary files in another local worktree. |

## Documentation and repository descriptions / Документация и описания репозиториев

- `1c-nexus-infra` has a bilingual README, while its current architecture
  document is Russian-only.
- `1c-x17-consolidator` has an English GitHub description and a README whose
  main technical content is Russian; a complete English counterpart was not
  found in the audited remote documentation.
- The GitHub description of `1c-nexus-infra` is empty. GitHub descriptions are
  repository settings and cannot be changed by a documentation commit alone.

- В `1c-nexus-infra` README двуязычный, но актуальный архитектурный документ
  только на русском.
- У `1c-x17-consolidator` GitHub-описание на английском, а основное техническое
  содержание README на русском; полного английского аналога в проверенной
  удалённой документации не найдено.
- GitHub-описание `1c-nexus-infra` пусто. Оно является настройкой репозитория и
  не меняется одним commit документации.

## Proposed GitHub descriptions / Предлагаемые GitHub-описания

- **1c-x17-consolidator:** `Консолидация и безопасное восстановление базы 1С x17 / Safe consolidation and recovery tooling for a 1C x17 database.`
- **1c-nexus-infra:** `Инфраструктура рабочей среды 1С: Graph, RAG, BSL и MCP / 1C workspace infrastructure: Graph, RAG, BSL and MCP.`

These are proposed bilingual repository settings; they are not yet confirmed
as applied on GitHub. Это предлагаемые двуязычные настройки репозиториев; их
применение на GitHub пока не подтверждено.

## Safe completion criteria / Критерии безопасного завершения

1. Reconcile the local x17 source with a reviewed, clean commit; do not include
   virtual environments, credentials, generated logs, or index databases.
2. Push that reviewed commit to `1c-x17-consolidator/main`, then re-check that
   the remote source version matches the intended release.
3. Add complete Russian and English repository overview documentation in each
   repository, and set bilingual GitHub descriptions through repository settings.
4. Re-run this audit after the push and settings update.

1. Свести локальные исходники x17 к проверенному чистому commit; не включать
   виртуальные окружения, учётные данные, генерируемые логи и базы индекса.
2. Отправить проверенный commit в `1c-x17-consolidator/main`, затем повторно
   подтвердить совпадение удалённой версии исходников с целевым релизом.
3. Добавить полную русскую и английскую обзорную документацию в каждый
   репозиторий и задать двуязычные GitHub-описания через настройки репозиториев.
4. Повторить аудит после push и изменения настроек.
