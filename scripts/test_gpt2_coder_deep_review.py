#!/usr/bin/env python3
"""Выполняет реальный primary-only тест GPT2-кодера и сохраняет результаты локально."""

from __future__ import annotations

import asyncio
import argparse
import hashlib
import importlib.util
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "scripts" / "omvl_llm_runtime.py"
DEFAULT_OUTPUT = ROOT / "temp" / "gpt2_coder_deep_review.json"


def load_runtime() -> Any:
    spec = importlib.util.spec_from_file_location("omvl_runtime_deep_review", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить OMVL runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def score(text: str, expected: dict[str, tuple[str, ...]]) -> dict[str, bool]:
    folded = text.casefold()
    return {name: any(token in folded for token in tokens) for name, tokens in expected.items()}


async def primary_request(
    runtime: Any,
    client: httpx.AsyncClient,
    route: dict[str, str],
    prompt: str,
    max_tokens: int,
) -> tuple[float, str]:
    started = time.monotonic()
    response = await client.post(
        f"{route['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {route['api_key']}"},
        json={
            "model": route["model"],
            "messages": [
                {"role": "system", "content": "Ты старший ревьюер 1С. Отвечай по-русски и не предлагай записи в БД."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": False,
        },
    )
    elapsed = time.monotonic() - started
    response.raise_for_status()
    result = runtime._ensure_usable_coder_result(response.json())
    return elapsed, str(result["choices"][0]["message"]["content"]).strip()


async def run(output: Path, selected_case: str | None = None) -> dict[str, Any]:
    runtime = load_runtime()
    primary, _ = runtime.coder_failover_routes()
    result: dict[str, Any] = {
        "status": "running",
        "mode": "primary_only_no_fallback",
        "model": primary["model"],
        "started_at_utc": datetime.now(UTC).isoformat(),
        "primary_timeout_seconds": runtime.coder_response_timeout(),
        "cases": [],
    }
    save(output, result)
    cases = [
        (
            "readiness",
            "Верни строго READY.",
            8,
            {"ready": ("ready",)},
        ),
        (
            "algorithm_integrity",
            "Найди обязательные STOP-условия в псевдо-BSL: список регистраторов читается без сортировки; "
            "следующий номер вычисляется как количество строк плюс один; три независимых этапа Сбор, Нормализация "
            "и Применение вызывают одну функцию ВыполнитьЕдиныйЭтап с разными флагами. "
            "Нужен сжатый вердикт: риски, обязательные проверки и почему Preview должен оставаться без записи.",
            80,
            {
                "sorting": ("сорт", "упорядоч"),
                "next_free": ("количеств", "следующ", "свободн"),
                "concurrency": ("гонк", "параллел", "конкурент", "блокиров"),
                "independent_stages": ("единый", "независим", "одн", "раздел"),
                "read_only": ("без записи", "read-only", "не запис"),
            },
        ),
        (
            "donor_canon",
            "Проверь правило выбора донора: «взять первую запись с непустым Идентификатором». "
            "Контракт требует выбрать только активную запись того же лицевого счёта и той же услуги "
            "с максимальным моментом изменения. При отсутствии, конфликте или нескольких равных кандидатах нужен STOP. "
            "Дай только проверяемые критерии Preview и запреты.",
            80,
            {
                "active": ("актив"),
                "account": ("лицев", "счет"),
                "service": ("услуг",),
                "latest": ("максим", "последн", "момент", "изменен"),
                "ambiguity_stop": ("конфликт", "неоднознач", "нескольк", "равн"),
                "absence_stop": ("отсутств", "не найден", "нет кандидат"),
            },
        ),
        (
            "x17_numbering_next_stage",
            "Выбери следующий безопасный этап восстановления нумерации x17 после успешного адресного пилота. "
            "Факты: на репетиционной ServedBase два документа группы "
            "Документ.икВводНачальныхПоказанийПриборовУчета + 00-00000001 + 2020 "
            "получили номера 03-00000001 и 08-00000001; независимый контроль подтвердил неизменность "
            "реквизитов, табличных частей и движений. Повторный полный ReadOnly дал стабильный MD5 "
            "3D8A64C9D85AA915F1BABFB599337808, 2645 групп, 16220 документов плана, "
            "READY=14684, REVIEW=1522, STOP=14. Следующая минимальная полная READY-группа того же типа: "
            "00-00000002 + 2020, ровно два UUID cb8b7bee-95a8-11ea-329d-000c29ecaafa и "
            "cb143470-aa08-11ea-889b-000c29a58bb5, точные цели 03-00000002 и 08-00000002. "
            "Сравни три варианта: отдельный ReadOnly Preview этой группы; сразу малая партия; "
            "пилот другого типа документа. Выдай один выбор и обязательные контрольные ворота. "
            "Не выбирай произвольный первый документ, не предлагай запуск базы или запись до успешного Preview; "
            "исходные x1_XX допускаются только для чтения.",
            180,
            {
                "single_choice": ("выбор", "рекоменд", "следующий этап"),
                "readonly_preview": ("readonly", "read-only", "preview", "без записи"),
                "full_group": ("полная групп", "ровно два", "оба uuid", "2 uuid"),
                "baseline_md5": ("3d8a64c9d85aa915f1babfb599337808", "md5"),
                "target_free": ("свобод", "незанят", "занятост"),
                "invariants": ("инвариант", "табличн", "движен"),
                "transaction_gate": ("транзакц", "откат", "после успешного preview"),
                "source_read_only": ("x1_xx", "исходн", "только для чтения"),
            },
        ),
    ]
    if selected_case:
        cases = [case for case in cases if case[0] == selected_case]
        if not cases:
            raise RuntimeError(f"Неизвестный сценарий: {selected_case}")
    try:
        async with httpx.AsyncClient(**runtime.coder_httpx_client_kwargs()) as client:
            for name, prompt, max_tokens, expected in cases:
                seconds, response = await primary_request(runtime, client, primary, prompt, max_tokens)
                checks = score(response, expected)
                result["cases"].append(
                    {
                        "name": name,
                        "seconds": round(seconds, 3),
                        "response": response,
                        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                        "checks": checks,
                        "score": f"{sum(checks.values())}/{len(checks)}",
                    }
                )
                save(output, result)
        result["status"] = "pass"
    except Exception as exc:
        result["status"] = "fail"
        result["error_class"] = type(exc).__name__
    result["finished_at_utc"] = datetime.now(UTC).isoformat()
    save(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=("readiness", "algorithm_integrity", "donor_canon", "x17_numbering_next_stage"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = asyncio.run(run(args.output, args.case))
    summary = "; ".join(f"{item['name']}={item['score']}" for item in result.get("cases", []))
    print(f"status={result['status']} {summary}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
