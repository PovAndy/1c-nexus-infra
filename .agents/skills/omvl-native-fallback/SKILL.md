---
name: omvl-native-fallback
description: Продолжение задачи OMVL нативным custom agent Codex после CodexFallbackRequired, requires_native_codex или появления pending work order в runtime/omvl-resilience. Использовать для безопасного принятия, выполнения и закрытия fallback без повторного внешнего запроса.
---

# Нативный fallback OMVL

1. Выполнить через проектный venv `scripts/omvl_native_fallback.py list`.
2. Прочитать только выбранный work order командой `show --task-id`. Не загружать соседние задания.
3. Проверить `schema_version`, `request_digest`, ограничения и критерии приёмки. При повреждении или недостаточном контексте оставить задание pending и вернуть STOP.
4. Принять задание командой `claim`, указав ровно `recommended_agent`.
5. Запустить одноимённый project custom agent из `.codex/agents/`. Передать только поля work order и необходимые узкие Graph/RAG-ссылки; не передавать `.env`, ключи, сырые данные 1С или персональные данные.
6. Не повторять внешний SeekAI-запрос. Не запускать вложенный Codex CLI.
7. Проверить результат локальными детерминированными воротами. Для BSL сохранять `[UNVERIFIED_DRAFT]`; запись в 17 исходных баз и доступ к SQL/x17 запрещены.
8. После успешной проверки выполнить `finish --status complete --evidence-ref <локальная ссылка>`. При доказательном STOP завершить со статусом `stop`.

Если custom agent недоступен, не менять checkpoint и явно сообщить о незавершённом pending-задании.
