#!/usr/bin/env python3
"""Измеряет primary GPT2-кодер без fallback и без сохранения текста модели."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "scripts" / "omvl_llm_runtime.py"
DEFAULT_OUTPUT = ROOT / "temp" / "gpt2_coder_live_probe.json"


def load_runtime() -> Any:
    spec = importlib.util.spec_from_file_location("omvl_runtime_gpt2_probe", RUNTIME_PATH)
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


def quality_checks(text: str) -> dict[str, bool]:
    folded = text.casefold()
    return {
        "sorting": bool(re.search(r"сорт|упорядоч", folded)),
        "next_free_race": bool(re.search(r"гонк|race|параллел|конкурент", folded)),
        "independent_stages": bool(
            re.search(r"одн.{0,40}функц|единый.{0,40}этап|не.{0,25}независим|общ.{0,25}функц", folded)
        ),
        "business_canon_rule": sum(
            token in folded for token in ("актив", "лицев", "услуг", "максим", "момент", "изменен")
        ) >= 4,
        "read_only": bool(re.search(r"запис|изменен.*баз|read.only", folded)),
    }


async def request_primary(
    runtime: Any,
    client: httpx.AsyncClient,
    route: dict[str, str],
    messages: list[dict[str, str]],
    max_tokens: int,
) -> tuple[float, str]:
    started = time.monotonic()
    response = await client.post(
        f"{route['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {route['api_key']}"},
        json={
            "model": route["model"],
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": False,
        },
    )
    elapsed = time.monotonic() - started
    response.raise_for_status()
    result = runtime._ensure_usable_coder_result(response.json())
    content = str(result["choices"][0]["message"]["content"]).strip()
    return elapsed, content


async def probe(output: Path, include_quality: bool) -> dict[str, Any]:
    runtime = load_runtime()
    primary, _ = runtime.coder_failover_routes()
    result: dict[str, Any] = {
        "status": "running",
        "mode": "primary_only_no_fallback",
        "model": primary["model"],
        "started_at_utc": datetime.now(UTC).isoformat(),
        "response_timeout_seconds": runtime.coder_response_timeout(),
    }
    save(output, result)
    try:
        async with httpx.AsyncClient(**runtime.coder_httpx_client_kwargs()) as client:
            catalog_started = time.monotonic()
            catalog_response = await client.get(
                f"{primary['base_url']}/models",
                headers={"Authorization": f"Bearer {primary['api_key']}"},
            )
            catalog_elapsed = time.monotonic() - catalog_started
            catalog = catalog_response.json() if catalog_response.status_code == 200 else {}
            entries = catalog.get("data", []) if isinstance(catalog, dict) else []
            result["catalog"] = {
                "http_status": catalog_response.status_code,
                "seconds": round(catalog_elapsed, 3),
                "configured_model_listed": any(
                    isinstance(item, dict) and item.get("id") == primary["model"] for item in entries
                ),
            }
            save(output, result)

            brief_seconds, brief = await request_primary(
                runtime,
                client,
                primary,
                [{"role": "user", "content": "Верни только слово READY."}],
                8,
            )
            result["brief"] = {
                "seconds": round(brief_seconds, 3),
                "usable": bool(brief),
                "response_sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest(),
            }
            save(output, result)

            if include_quality:
                prompt = (
                    "Проведи строгое ревью миграционного алгоритма и назови только обязательные STOP-условия. "
                    "Выбор следующего свободного номера читает записи без явной сортировки и строит номер как "
                    "количество записей плюс один. Три заявленных независимых этапа «сбор», «нормализация» "
                    "и «применение» вызывают одну и ту же функцию ВыполнитьЕдиныйЭтап с разными флагами. "
                    "Для выбора канонической записи предложено «взять первую с непустым Идентификатором». "
                    "Бизнес-контракт требует выбирать только активную запись того же лицевого счёта и той же услуги "
                    "с максимальным моментом изменения; при отсутствии такой записи нужен STOP. "
                    "Не предлагай запись в БД."
                )
                quality_seconds, quality = await request_primary(
                    runtime,
                    client,
                    primary,
                    [
                        {"role": "system", "content": "Ты старший ревьюер кода. Отвечай по-русски, сжато и доказательно."},
                        {"role": "user", "content": prompt},
                    ],
                    260,
                )
                checks = quality_checks(quality)
                result["quality"] = {
                    "seconds": round(quality_seconds, 3),
                    "usable": bool(quality),
                    "checks": checks,
                    "score": f"{sum(checks.values())}/{len(checks)}",
                    "response_sha256": hashlib.sha256(quality.encode("utf-8")).hexdigest(),
                }
            result["status"] = "pass"
    except Exception as exc:
        result["status"] = "fail"
        result["error_class"] = type(exc).__name__
    result["finished_at_utc"] = datetime.now(UTC).isoformat()
    save(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quality", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(probe(args.output, args.quality))
    print(
        f"status={result['status']} timeout={result['response_timeout_seconds']} "
        f"catalog={result.get('catalog', {}).get('http_status', 'n/a')} "
        f"quality={result.get('quality', {}).get('score', 'not_run')}"
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
