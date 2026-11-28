"""Accept owner changes to the collector's queue without opening its database."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .ticket_controls import MAX_OVERRIDES, ROUTE, TICKET_CONTROL, read_ticket_controls

_MESSAGES = {
    "prioritize": "Маршрут получит приоритет среди готовых к сбору.",
    "normal": "Восстановлен обычный приоритет маршрута.",
    "defer": "Маршрут отложен.",
    "restore": "Маршрут возвращён в очередь.",
}


def edit_ticket_queue(*, path, snapshot, body):
    route, action = body.get("route"), body.get("action")
    if (set(body) != {"route", "action"} or not isinstance(route, str)
            or not isinstance(action, str) or action not in _MESSAGES):
        raise ValueError("Укажите маршрут и действие с очередью.")
    route = route.strip().upper()
    if not ROUTE.fullmatch(route) or route[:3] == route[4:]:
        raise ValueError("Укажите маршрут из двух кодов ИАТА через дефис.")
    prioritized, deferred = read_ticket_controls(path)
    if route not in prioritized and route not in deferred:
        with snapshot.open("rb") as stream:
            data = stream.read(256 * 1024 + 1)
        try:
            if len(data) > 256 * 1024:
                raise ValueError
            planned = json.loads(data)["tickets"]["planned"]
            known = any(row["route"] == route for row in planned)
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            raise OSError("ticket queue snapshot unavailable") from exc
        if not known:
            raise ValueError("Обновите очередь и выберите маршрут из списка.")
    old = (prioritized[:], deferred[:])
    if action != "normal" and route in deferred:
        deferred.remove(route)
    if action != "restore" and route in prioritized:
        prioritized.remove(route)
    if action == "prioritize":
        prioritized.insert(0, route)
    if action == "defer":
        deferred.append(route)
    if len(prioritized) + len(deferred) > MAX_OVERRIDES:
        raise ValueError("Достигнут лимит ручных изменений очереди.")
    changed = old != (prioritized, deferred)
    if changed:
        with NamedTemporaryFile(dir=path.parent, prefix=".overrides-", delete=False) as stream:
            temp = Path(stream.name)
            try:
                stream.write(json.dumps({"prioritized": prioritized, "deferred": deferred}).encode())
                stream.flush()
                os.fchmod(stream.fileno(), 0o640)
                os.fsync(stream.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
    return {"changed": changed, "prioritized": prioritized, "deferred": deferred,
            "message": _MESSAGES[action] if changed else "Очередь уже в этом состоянии."}
