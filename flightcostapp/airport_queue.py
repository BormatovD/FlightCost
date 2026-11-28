"""Small owner-managed queue shared by the admin service and tariff agent."""

import fcntl
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ICAO = re.compile(r"[A-Z]{4}")
MAX_ITEMS = 100
MAX_ITEM_BYTES = 1024


def _read_item(path: Path) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as file:
            details = os.fstat(file.fileno())
            if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_ITEM_BYTES:
                return None
            item = json.loads(file.read(MAX_ITEM_BYTES + 1))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(item, dict) or item.get("icao") != path.stem:
        return None
    if item.get("deferred") is True:
        return {"icao": path.stem, "deferred": True}
    city, added_at, priority_at = (item.get(key) for key in ("city", "added_at", "priority_at"))
    if not isinstance(city, str) or not isinstance(added_at, str):
        return None
    clean = {"icao": path.stem, "city": city, "added_at": added_at}
    request_id = item.get("request_id")
    if isinstance(request_id, str):
        clean["request_id"] = request_id
    if type(priority_at) is int and priority_at > 0:
        clean["priority_at"] = priority_at
    return clean


def _queue_paths(directory: Path):
    return sorted(path for path in directory.glob("*.json") if ICAO.fullmatch(path.stem))


def queue_airports(directory: Path) -> tuple[list[dict], list[str]]:
    manual, deferred = [], []
    for path in _queue_paths(directory)[:MAX_ITEMS]:
        item = _read_item(path)
        if item is None:
            continue
        if item.get("deferred"):
            deferred.append(item["icao"])
        else:
            manual.append(item)
    manual.sort(key=lambda row: (-row.get("priority_at", 0), row["added_at"], row["icao"]))
    return manual, deferred


def pending_airports(directory: Path) -> list[dict]:
    return queue_airports(directory)[0]


@contextmanager
def _write_lock(directory: Path):
    path = directory / ".lock"
    if not os.path.lexists(path):
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".airport-lock-") as temporary:
            os.fchmod(temporary.fileno(), 0o660)
            try:
                os.link(temporary.name, path)
            except FileExistsError:
                pass
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Invalid airport queue lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _write(path: Path, item: dict):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".airport-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(item, file, ensure_ascii=False)
            file.flush()
            os.fchmod(file.fileno(), 0o660)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _validate_icao(icao: str):
    if not ICAO.fullmatch(icao):
        raise ValueError("Укажите четырёхбуквенный код ИКАО.")


def _check_space(directory: Path, dest: Path):
    if not os.path.lexists(dest) and len(_queue_paths(directory)) >= MAX_ITEMS:
        raise ValueError("Очередь достигла 100 аэропортов.")


def _new_request(icao: str, city: str) -> dict:
    return {"icao": icao, "city": city, "added_at": datetime.now(timezone.utc).isoformat(),
            "request_id": uuid4().hex}


def request_identity(request: dict) -> str:
    return request.get("request_id", request["added_at"])


def add_airport(directory: Path, icao: str, city: str) -> bool:
    _validate_icao(icao)
    if len(city) > 60 or any(not (c.isalnum() or c in " .-’'()") for c in city):
        raise ValueError("Укажите название аэропорта или города длиной до 60 символов.")
    dest = directory / f"{icao}.json"
    with _write_lock(directory):
        if os.path.lexists(dest):
            return False
        _check_space(directory, dest)
        _write(dest, _new_request(icao, city))
    return True


def edit_airport(directory: Path, icao: str, action: str) -> bool:
    _validate_icao(icao)
    if action not in {"prioritize", "remove", "defer", "restore"}:
        raise ValueError("Выберите действие для аэропорта.")
    dest = directory / f"{icao}.json"
    with _write_lock(directory):
        item = _read_item(dest)
        deferred = bool(item and item.get("deferred"))
        if action == "prioritize":
            if deferred:
                raise ValueError("Сначала верните аэропорт в автоматическую очередь.")
            _check_space(directory, dest)
            manual, _ = queue_airports(directory)
            priority = max((row.get("priority_at", 0) for row in manual), default=0)
            if item and item.get("priority_at", 0) == priority and priority:
                return False
            updated = item or _new_request(icao, "")
            updated["priority_at"] = priority + 1
            _write(dest, updated)
        elif action == "defer":
            if item is not None:
                return False
            _check_space(directory, dest)
            _write(dest, {"icao": icao, "deferred": True})
        elif item is not None and deferred == (action == "restore"):
            dest.unlink()
        else:
            return False
    return True


def consume_airport(directory: Path, request: dict) -> None:
    """Remove only the request whose work ended, even if the airport was re-added."""
    with _write_lock(directory):
        dest = directory / f"{request['icao']}.json"
        current = _read_item(dest)
        if (current and not current.get("deferred")
                and request_identity(current) == request_identity(request)):
            dest.unlink()
