#!/usr/bin/env python3
"""Управляет свежестью и событийным обновлением Workspace Graph V2."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import logging.handlers
import os
import queue
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

import map_workspace_graph_v2 as mapper


КОРЕНЬ_ПРОЕКТА = Path(os.getenv("NEXUS_WORKSPACE_ROOT", Path(__file__).resolve().parent.parent))
ГЕНЕРАТОР = КОРЕНЬ_ПРОЕКТА / "scripts" / "map_workspace_graph_v2.py"
ИМЯ_ГРАФА = "workspace_graph_v2.json"
ИМЯ_СОСТОЯНИЯ = "workspace_graph_v2.state.json"
ИМЯ_БЛОКИРОВКИ = "workspace_graph_v2.lock"
ИМЯ_DIRTY = "workspace_graph_v2.dirty"
ИМЯ_БЛОКИРОВКИ_WATCHER = "workspace_graph_v2_watcher.lock"
ИМЯ_СТАТУСА_WATCHER = "workspace_graph_v2_watcher.status.json"
ИМЯ_ЛОГА_WATCHER = "workspace_graph_v2_watcher.log"
ВЕРСИЯ_СОСТОЯНИЯ = "1.0"


@dataclass(frozen=True)
class Инвентаризация:
    """Краткий снимок состава и stat-атрибутов исходников."""

    digest: str
    файлов: int
    последний_mtime_ns: int


@dataclass(frozen=True)
class Пути:
    """Все runtime-пути одного экземпляра менеджера."""

    корень: Path
    граф: Path
    состояние: Path
    блокировка: Path
    dirty: Path
    блокировка_watcher: Path
    статус_watcher: Path
    лог_watcher: Path


def сейчас_iso() -> str:
    """Возвращает UTC-время без микросекунд."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def построить_пути(корень: Path, граф: Path | None = None) -> Пути:
    """Формирует runtime-пути относительно выбранного проекта."""
    корень = корень.expanduser().resolve()
    путь_графа = (
        граф.expanduser().resolve()
        if граф is not None
        else корень / "temp" / ИМЯ_ГРАФА
    )
    runtime = путь_графа.parent
    return Пути(
        корень=корень,
        граф=путь_графа,
        состояние=runtime / ИМЯ_СОСТОЯНИЯ,
        блокировка=runtime / ИМЯ_БЛОКИРОВКИ,
        dirty=runtime / ИМЯ_DIRTY,
        блокировка_watcher=runtime / ИМЯ_БЛОКИРОВКИ_WATCHER,
        статус_watcher=runtime / ИМЯ_СТАТУСА_WATCHER,
        лог_watcher=runtime / ИМЯ_ЛОГА_WATCHER,
    )


def записать_json_атомарно(путь: Path, данные: dict[str, Any]) -> None:
    """Записывает небольшой служебный JSON атомарной заменой."""
    путь.parent.mkdir(parents=True, exist_ok=True)
    дескриптор, имя = tempfile.mkstemp(
        prefix=f".{путь.name}.",
        suffix=".tmp",
        dir=путь.parent,
        text=True,
    )
    временный = Path(имя)
    try:
        with os.fdopen(дескриптор, "w", encoding="utf-8") as поток:
            json.dump(данные, поток, ensure_ascii=False, indent=2)
            поток.write("\n")
            поток.flush()
            os.fsync(поток.fileno())
        временный.replace(путь)
    except BaseException:
        временный.unlink(missing_ok=True)
        raise


def прочитать_json(путь: Path) -> dict[str, Any] | None:
    """Безопасно читает JSON-объект либо возвращает отсутствие состояния."""
    try:
        данные = json.loads(путь.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return данные if isinstance(данные, dict) else None


def sha256_файла(путь: Path) -> str:
    """Вычисляет контрольную сумму файла потоково."""
    digest = hashlib.sha256()
    with путь.open("rb") as поток:
        for блок in iter(lambda: поток.read(1024 * 1024), b""):
            digest.update(блок)
    return digest.hexdigest()


def инвентаризировать(корень: Path) -> Инвентаризация:
    """Считает быстрый digest путей, размеров и mtime поддерживаемых файлов."""
    digest = hashlib.sha256()
    файлов = 0
    последний_mtime_ns = 0
    for путь, язык in mapper.исходные_файлы(корень):
        try:
            stat = путь.stat()
        except OSError:
            continue
        относительный = путь.relative_to(корень).as_posix()
        строка = (
            f"{относительный}\0{язык}\0{stat.st_size}\0{stat.st_mtime_ns}\n"
        )
        digest.update(строка.encode("utf-8", errors="surrogateescape"))
        файлов += 1
        последний_mtime_ns = max(последний_mtime_ns, stat.st_mtime_ns)
    return Инвентаризация(
        digest=digest.hexdigest(),
        файлов=файлов,
        последний_mtime_ns=последний_mtime_ns,
    )


def проверить_граф(путь: Path, корень: Path) -> dict[str, int]:
    """Проверяет JSON-контракт и возвращает краткие агрегаты."""
    try:
        данные = json.loads(путь.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"граф не читается: {exc}") from exc
    if not isinstance(данные, dict) or данные.get("schema_version") != "2.0":
        raise RuntimeError("граф не соответствует schema_version 2.0")
    if Path(str(данные.get("root", ""))).resolve() != корень:
        raise RuntimeError("root графа не соответствует текущему проекту")
    узлы = данные.get("nodes")
    ребра = данные.get("edges")
    if not isinstance(узлы, list) or not isinstance(ребра, list):
        raise RuntimeError("граф не содержит массивы nodes и edges")
    идентификаторы = {
        узел.get("id")
        for узел in узлы
        if isinstance(узел, dict) and isinstance(узел.get("id"), str)
    }
    if len(идентификаторы) != len(узлы):
        raise RuntimeError("узлы графа имеют пустые или повторяющиеся id")
    допустимые_ребра = {"DEFINES", "CALLS", "EXPOSES_TOOL"}
    for ребро in ребра:
        if not isinstance(ребро, dict):
            raise RuntimeError("ребро графа должно быть объектом")
        if ребро.get("type") not in допустимые_ребра:
            raise RuntimeError("граф содержит неизвестный тип ребра")
        if (
            ребро.get("source") not in идентификаторы
            or ребро.get("target") not in идентификаторы
        ):
            raise RuntimeError("ребро графа ссылается на отсутствующий узел")
    ошибки_разбора = данные.get("parse_errors", [])
    if not isinstance(ошибки_разбора, list):
        raise RuntimeError("диагностика ошибок разбора должна быть массивом")
    if данные.get("parse_error_files") != len(ошибки_разбора):
        raise RuntimeError("счетчик ошибок разбора не соответствует диагностике")
    for ошибка in ошибки_разбора:
        if not isinstance(ошибка, dict) or not all(
            isinstance(ошибка.get(поле), str) and ошибка[поле]
            for поле in ("file", "reason")
        ):
            raise RuntimeError("диагностика ошибки разбора имеет неверный контракт")
    return {
        "узлов": len(узлы),
        "ребер": len(ребра),
        "ошибок_разбора": int(данные.get("parse_error_files", 0)),
    }


@contextmanager
def файловая_блокировка(путь: Path, timeout: float) -> Iterator[None]:
    """Получает эксклюзивную flock-блокировку с ограниченным ожиданием."""
    путь.parent.mkdir(parents=True, exist_ok=True)
    with путь.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"таймаут блокировки: {путь}")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def причины_устаревания(
    пути: Пути,
    инвентаризация: Инвентаризация,
    *,
    глубокая_проверка: bool = False,
) -> list[str]:
    """Возвращает причины перестроения без изменения файлов."""
    причины: list[str] = []
    состояние = прочитать_json(пути.состояние)
    if not пути.граф.is_file():
        причины.append("граф отсутствует")
    if состояние is None:
        причины.append("состояние отсутствует или повреждено")
        return причины
    if состояние.get("state_version") != ВЕРСИЯ_СОСТОЯНИЯ:
        причины.append("изменилась версия состояния")
    if состояние.get("inventory_digest") != инвентаризация.digest:
        причины.append("изменился состав или stat исходников")
    if состояние.get("source_count") != инвентаризация.файлов:
        причины.append("изменилось количество исходников")
    if пути.граф.is_file():
        stat = пути.граф.stat()
        if состояние.get("graph_size") != stat.st_size:
            причины.append("изменился размер графа")
        if состояние.get("graph_mtime_ns") != stat.st_mtime_ns:
            причины.append("изменился mtime графа")
        if stat.st_mtime_ns < инвентаризация.последний_mtime_ns:
            причины.append("граф старше исходников")
        if глубокая_проверка:
            try:
                проверить_граф(пути.граф, пути.корень)
                if состояние.get("graph_sha256") != sha256_файла(пути.граф):
                    причины.append("не совпадает SHA-256 графа")
            except RuntimeError as exc:
                причины.append(str(exc))
    return sorted(set(причины))


def быстрое_состояние_живого_watcher(пути: Пути) -> dict[str, Any] | None:
    """Возвращает state без stat-обхода, если watcher гарантирует отсутствие событий."""
    if пути.dirty.exists():
        return None
    статус = прочитать_json(пути.статус_watcher)
    состояние = прочитать_json(пути.состояние)
    if статус is None or состояние is None:
        return None
    pid = int(статус.get("pid", 0) or 0)
    if статус.get("state") != "running" or not процесс_жив(pid):
        return None
    if состояние.get("state_version") != ВЕРСИЯ_СОСТОЯНИЯ:
        return None
    if not пути.граф.is_file():
        return None
    stat = пути.граф.stat()
    if (
        состояние.get("graph_size") != stat.st_size
        or состояние.get("graph_mtime_ns") != stat.st_mtime_ns
    ):
        return None
    return состояние


def сгенерировать(
    пути: Пути,
    инвентаризация: Инвентаризация,
    причина: str,
) -> dict[str, Any]:
    """Запускает генератор, валидирует результат и сохраняет freshness-state."""
    команда = [
        sys.executable,
        str(ГЕНЕРАТОР),
        "--root",
        str(пути.корень),
        "--output",
        str(пути.граф),
    ]
    результат = subprocess.run(
        команда,
        cwd=пути.корень,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
        check=False,
    )
    if результат.returncode != 0:
        деталь = (результат.stderr or результат.stdout).strip().splitlines()
        хвост = деталь[-1] if деталь else "без диагностического сообщения"
        raise RuntimeError(
            f"генератор завершился с кодом {результат.returncode}: {хвост}"
        )

    агрегаты = проверить_граф(пути.граф, пути.корень)
    stat = пути.граф.stat()
    состояние: dict[str, Any] = {
        "state_version": ВЕРСИЯ_СОСТОЯНИЯ,
        "graph_schema_version": "2.0",
        "root": str(пути.корень),
        "graph": str(пути.граф),
        "generated_at": сейчас_iso(),
        "reason": причина,
        "inventory_digest": инвентаризация.digest,
        "source_count": инвентаризация.файлов,
        "source_latest_mtime_ns": инвентаризация.последний_mtime_ns,
        "graph_size": stat.st_size,
        "graph_mtime_ns": stat.st_mtime_ns,
        "graph_sha256": sha256_файла(пути.граф),
        **агрегаты,
    }
    записать_json_атомарно(пути.состояние, состояние)
    пути.dirty.unlink(missing_ok=True)
    return состояние


def обеспечить_актуальность(
    пути: Пути,
    *,
    причина: str,
    принудительно: bool = False,
    глубокая_проверка: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """Перестраивает граф только при фактическом устаревании."""
    if not принудительно and not глубокая_проверка:
        быстрое = быстрое_состояние_живого_watcher(пути)
        if быстрое is not None:
            return False, быстрое
    with файловая_блокировка(пути.блокировка, timeout=120):
        if not принудительно and not глубокая_проверка:
            быстрое = быстрое_состояние_живого_watcher(пути)
            if быстрое is not None:
                return False, быстрое
        инвентаризация = инвентаризировать(пути.корень)
        причины = причины_устаревания(
            пути,
            инвентаризация,
            глубокая_проверка=глубокая_проверка,
        )
        if принудительно:
            причины.append("принудительное обновление")
        if not причины:
            состояние = прочитать_json(пути.состояние)
            if состояние is None:
                raise RuntimeError("состояние графа исчезло во время проверки")
            пути.dirty.unlink(missing_ok=True)
            return False, состояние
        состояние = сгенерировать(
            пути,
            инвентаризация,
            f"{причина}: {', '.join(sorted(set(причины)))}",
        )
        return True, состояние


def поддерживаемый_путь(корень: Path, путь: str) -> bool:
    """Фильтрует событие watcher по тем же правилам, что и генератор."""
    кандидат = Path(путь)
    try:
        относительный = кандидат.resolve(strict=False).relative_to(корень)
    except (OSError, ValueError):
        return False
    части = относительный.parts
    if not части:
        return False
    if any(mapper.каталог_игнорируется(часть) for часть in части[:-1]):
        return False
    return Path(части[-1]).suffix.lower() in mapper.РАСШИРЕНИЯ


class ОбработчикСобытий(FileSystemEventHandler):
    """Передает только релевантные события в очередь с последующим debounce."""

    ИЗМЕНЯЮЩИЕ_СОБЫТИЯ = {"created", "modified", "deleted", "moved"}

    def __init__(
        self,
        корень: Path,
        события: queue.Queue[str],
        dirty: Path,
    ) -> None:
        super().__init__()
        self.корень = корень
        self.события = события
        self.dirty = dirty

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in self.ИЗМЕНЯЮЩИЕ_СОБЫТИЯ:
            return
        пути = [event.src_path]
        путь_назначения = getattr(event, "dest_path", "")
        if путь_назначения:
            пути.append(путь_назначения)
        if any(поддерживаемый_путь(self.корень, путь) for путь in пути):
            self.dirty.parent.mkdir(parents=True, exist_ok=True)
            self.dirty.touch(exist_ok=True)
            self.события.put(event.event_type)


def процесс_жив(pid: int) -> bool:
    """Проверяет существование процесса без отправки рабочего сигнала."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def настроить_логирование(путь: Path) -> logging.Logger:
    """Создает ротационный локальный лог watcher без вывода исходников."""
    путь.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("workspace_graph_v2_watcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.handlers.RotatingFileHandler(
        путь,
        maxBytes=1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def обновить_статус_watcher(
    пути: Пути,
    *,
    состояние: str,
    запущен: str,
    последнее_событие: str = "",
    последний_успех: str = "",
    ошибка: str = "",
) -> None:
    """Сохраняет короткий машинный статус watcher."""
    записать_json_атомарно(
        пути.статус_watcher,
        {
            "state": состояние,
            "pid": os.getpid(),
            "started_at": запущен,
            "updated_at": сейчас_iso(),
            "last_event_at": последнее_событие,
            "last_success_at": последний_успех,
            "error": ошибка[:500],
        },
    )


def запустить_watcher(пути: Пути, debounce: float) -> int:
    """Запускает единственный событийный watcher до SIGTERM или SIGINT."""
    logger = настроить_логирование(пути.лог_watcher)
    события: queue.Queue[str] = queue.Queue()
    stop = False
    запущен = сейчас_iso()
    последнее_событие = ""
    последний_успех = ""

    def остановить(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, остановить)
    signal.signal(signal.SIGINT, остановить)

    try:
        with файловая_блокировка(пути.блокировка_watcher, timeout=0.2):
            обновлен, _ = обеспечить_актуальность(
                пути,
                причина="watcher:start",
                глубокая_проверка=True,
            )
            последний_успех = сейчас_iso()
            observer = Observer(timeout=0.5)
            observer.schedule(
                ОбработчикСобытий(пути.корень, события, пути.dirty),
                str(пути.корень),
                recursive=True,
            )
            observer.start()
            обновить_статус_watcher(
                пути,
                состояние="running",
                запущен=запущен,
                последний_успех=последний_успех,
            )
            logger.info("watcher запущен; initial_update=%s", обновлен)
            print("WORKSPACE_GRAPH_V2_WATCHER_READY", flush=True)
            try:
                while not stop:
                    try:
                        тип_события = события.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    последнее_событие = сейчас_iso()
                    deadline = time.monotonic() + debounce
                    типы = {тип_события}
                    while time.monotonic() < deadline:
                        try:
                            типы.add(
                                события.get(
                                    timeout=max(0.01, deadline - time.monotonic())
                                )
                            )
                        except queue.Empty:
                            break
                    try:
                        обновить_статус_watcher(
                            пути,
                            состояние="updating",
                            запущен=запущен,
                            последнее_событие=последнее_событие,
                            последний_успех=последний_успех,
                        )
                        обновлен, _ = обеспечить_актуальность(
                            пути,
                            причина=f"watcher:{','.join(sorted(типы))}",
                        )
                        последний_успех = сейчас_iso()
                        logger.info(
                            "событие обработано; types=%s update=%s",
                            ",".join(sorted(типы)),
                            обновлен,
                        )
                        обновить_статус_watcher(
                            пути,
                            состояние="running",
                            запущен=запущен,
                            последнее_событие=последнее_событие,
                            последний_успех=последний_успех,
                        )
                    except Exception as exc:
                        logger.exception("ошибка обновления графа")
                        обновить_статус_watcher(
                            пути,
                            состояние="error",
                            запущен=запущен,
                            последнее_событие=последнее_событие,
                            последний_успех=последний_успех,
                            ошибка=str(exc),
                        )
            finally:
                observer.stop()
                observer.join(timeout=10)
                обновить_статус_watcher(
                    пути,
                    состояние="stopped",
                    запущен=запущен,
                    последнее_событие=последнее_событие,
                    последний_успех=последний_успех,
                )
                logger.info("watcher остановлен")
    except TimeoutError:
        print("WORKSPACE_GRAPH_V2_WATCHER_ALREADY_RUNNING", flush=True)
        return 0
    return 0


def показать_статус(пути: Пути) -> int:
    """Печатает компактный статус watcher и freshness графа."""
    статус = прочитать_json(пути.статус_watcher) or {}
    pid = int(статус.get("pid", 0) or 0)
    инвентаризация = инвентаризировать(пути.корень)
    причины = причины_устаревания(пути, инвентаризация)
    watcher = "running" if процесс_жив(pid) else "stopped"
    freshness = "fresh" if not причины else "stale"
    print(
        f"watcher={watcher} pid={pid or '-'} graph={freshness} "
        f"sources={инвентаризация.файлов} "
        f"reason={'; '.join(причины) if причины else '-'}"
    )
    return 0 if watcher == "running" and freshness == "fresh" else 1


def разобрать_аргументы() -> argparse.Namespace:
    """Разбирает команды ensure, force, check, watch и status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("ensure", "force", "check", "watch", "status"),
    )
    parser.add_argument("--root", type=Path, default=КОРЕНЬ_ПРОЕКТА)
    parser.add_argument("--graph", type=Path, default=None)
    parser.add_argument("--reason", default="manual")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--debounce", type=float, default=1.2)
    return parser.parse_args()


def main() -> int:
    """Выполняет выбранную операцию менеджера."""
    args = разобрать_аргументы()
    пути = построить_пути(args.root, args.graph)
    if not пути.корень.is_dir():
        raise SystemExit(f"Корень проекта не найден: {пути.корень}")

    if args.command == "watch":
        return запустить_watcher(пути, max(0.1, args.debounce))
    if args.command == "status":
        return показать_статус(пути)

    if args.command == "check":
        инвентаризация = инвентаризировать(пути.корень)
        причины = причины_устаревания(
            пути,
            инвентаризация,
            глубокая_проверка=args.deep,
        )
        if причины:
            if not args.quiet:
                print(f"Граф устарел: {'; '.join(причины)}")
            return 1
        if not args.quiet:
            print(f"Граф актуален: файлов={инвентаризация.файлов}")
        return 0

    обновлен, состояние = обеспечить_актуальность(
        пути,
        причина=args.reason,
        принудительно=args.command == "force",
        глубокая_проверка=args.deep,
    )
    if not args.quiet:
        действие = "обновлен" if обновлен else "актуален"
        print(
            f"Граф {действие}: файлов={состояние['source_count']} "
            f"узлов={состояние['узлов']} ребер={состояние['ребер']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
