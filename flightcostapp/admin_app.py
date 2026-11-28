"""Owner-only Telegram Mini App. HTTP requests never query the main databases."""

import hashlib
import hmac
import json
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .airport_queue import add_airport, edit_airport, queue_airports
from .tg import load_token
from .ticket_admin import edit_ticket_queue
from .ticket_controls import TICKET_CONTROL

ROOT = Path(__file__).with_name("web")
SNAPSHOT = Path("/var/lib/fca-admin-snapshot/status.json")
QUEUE = Path("/srv/fca/agent/queue/airport-admin")
ORIGIN = "https://flightcost.app"
MAX_BODY = 1024
MAX_INIT_DATA = 4096
MAX_SNAPSHOT = 256 * 1024
INIT_DATA_AGE = 3600

STATIC = {
    "/bot-admin/": ("admin.html", "text/html; charset=utf-8"),
    "/bot-admin/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
    "/bot-admin/admin.css": ("admin.css", "text/css; charset=utf-8"),
}
CSP = ("default-src 'none'; script-src 'self' https://telegram.org; "
       "style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'self' https://*.telegram.org")


def telegram_owner(init_data: str, secret: bytes, owner: int, now: int) -> bool:
    if not 0 < len(init_data) <= MAX_INIT_DATA:
        return False
    try:
        fields = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True,
                           max_num_fields=20, errors="strict")
        values = dict(fields)
        if len(values) != len(fields):
            return False
        received = values.pop("hash", "")
        if not re.fullmatch(r"[0-9a-f]{64}", received):
            return False
        check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received, expected):
            return False
        age = now - int(values["auth_date"])
        if not -30 <= age <= INIT_DATA_AGE:
            return False
        user_id = json.loads(values["user"])["id"]
        return type(user_id) is int and user_id == owner
    except (KeyError, ValueError, TypeError, UnicodeError, RecursionError):
        return False


class AdminServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, *, token, owner, snapshot=SNAPSHOT, queue=QUEUE, ticket_control=TICKET_CONTROL,
                 editorial_control=None):
        self.secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        self.owner = owner
        self.snapshot = snapshot
        self.queue = queue
        self.ticket_control = ticket_control
        self.editorial_control = editorial_control or os.environ.get("FCA_EDITORIAL_CONTROL")
        self.slots = threading.BoundedSemaphore(4)
        self.manage = threading.Lock()
        self.last_run_request = float("-inf")
        super().__init__(address, AdminHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(4)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def request_run(self):
        now = time.monotonic()
        if now - self.last_run_request < 45:
            return False
        try:
            fd = os.open(self.queue / ".run", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
        except FileExistsError:
            return False
        os.close(fd)
        self.last_run_request = now
        return True


class AdminHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def reply(self, status, **value):
        self.respond(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def authorized(self):
        scheme, _, data = self.headers.get("Authorization", "").partition(" ")
        return scheme == "tma" and telegram_owner(data, self.server.secret, self.server.owner, int(time.time()))

    def do_GET(self):
        path = urlsplit(self.path).path
        asset = STATIC.get(path)
        if asset:
            filename, content_type = asset
            return self.respond(HTTPStatus.OK, (ROOT / filename).read_bytes(), content_type)
        if path != "/bot-admin/api/status":
            return self.reply(HTTPStatus.NOT_FOUND, error="Страница не найдена.")
        if not self.authorized():
            return self.reply(HTTPStatus.FORBIDDEN, error="Откройте панель из Telegram под учётной записью владельца.")
        try:
            with self.server.snapshot.open("rb") as stream:
                data = stream.read(MAX_SNAPSHOT + 1)
            if len(data) > MAX_SNAPSHOT:
                raise OSError("oversized snapshot")
        except OSError:
            return self.reply(HTTPStatus.SERVICE_UNAVAILABLE, error="Снимок статуса пока недоступен.")
        if self.server.editorial_control:
            control = Path(self.server.editorial_control)
            if control.is_dir():
                snapshot = json.loads(data)
                snapshot["journalist"] = {"paused": (control / "paused").exists()}
                return self.reply(HTTPStatus.OK, **snapshot)
        return self.respond(HTTPStatus.OK, data, "application/json; charset=utf-8")

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/bot-admin/api/run", "/bot-admin/api/airports", "/bot-admin/api/airports/edit",
                        "/bot-admin/api/tickets/edit", "/bot-admin/api/journalist"):
            return self.reply(HTTPStatus.NOT_FOUND, error="Действие не найдено.")
        if self.headers.get("Origin") != ORIGIN or not self.authorized():
            return self.reply(HTTPStatus.FORBIDDEN, error="Действие доступно владельцу в Telegram.")
        try:
            size = int(self.headers.get("Content-Length", ""))
            if not 0 < size <= MAX_BODY or self.headers.get_content_type() != "application/json":
                raise ValueError
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, OSError, RecursionError):
            return self.reply(HTTPStatus.BAD_REQUEST, error="Некорректные данные.")
        try:
            with self.server.manage:
                if path == "/bot-admin/api/journalist":
                    if set(data) != {"paused"} or type(data["paused"]) is not bool:
                        raise ValueError("Укажите состояние журналиста.")
                    if not self.server.editorial_control or not Path(self.server.editorial_control).is_dir():
                        return self.reply(HTTPStatus.SERVICE_UNAVAILABLE, error="Редакционный агент недоступен.")
                    marker = Path(self.server.editorial_control) / "paused"
                    if data["paused"]:
                        marker.touch(mode=0o640)
                    else:
                        marker.unlink(missing_ok=True)
                    return self.reply(HTTPStatus.OK, paused=marker.exists())
                if path.endswith("/run"):
                    if data:
                        raise ValueError("Запуск не принимает параметров.")
                    queued = self.server.request_run()
                    return self.reply(HTTPStatus.ACCEPTED, already_queued=not queued, message=(
                        "Запрос на запуск передан." if queued else "Недавний запрос на запуск уже передан."))
                if path == "/bot-admin/api/tickets/edit":
                    result = edit_ticket_queue(path=self.server.ticket_control, snapshot=self.server.snapshot, body=data)
                    return self.reply(HTTPStatus.OK, **result)
                icao = data.get("icao")
                if path.endswith("/edit"):
                    action = data.get("action")
                    if set(data) != {"icao", "action"} or not isinstance(icao, str) or not isinstance(action, str):
                        raise ValueError("Укажите код ИКАО и действие.")
                    changed = edit_airport(self.server.queue, icao.strip().upper(), action)
                    message = {
                        "prioritize": "Аэропорт перенесён в начало очереди.",
                        "remove": "Аэропорт удалён из ручной очереди.",
                        "defer": "Аэропорт отложен.",
                        "restore": "Аэропорт возвращён в автоматическую очередь.",
                    }[action]
                    result = dict(changed=changed, message=message if changed else "Очередь не изменилась.")
                else:
                    city = data.get("city", "")
                    if set(data) - {"icao", "city"} or not isinstance(icao, str) or not isinstance(city, str):
                        raise ValueError("Укажите код ИКАО и при необходимости название.")
                    added = add_airport(self.server.queue, icao.strip().upper(), city.strip())
                    result = dict(already_queued=not added, message=(
                        "Аэропорт добавлен в очередь." if added else "Аэропорт уже в очереди."))
                manual, deferred = queue_airports(self.server.queue)
                return self.reply(HTTPStatus.OK, manual=manual, deferred=deferred, **result)
        except ValueError as exc:
            return self.reply(HTTPStatus.BAD_REQUEST, error=str(exc))
        except OSError:
            return self.reply(HTTPStatus.SERVICE_UNAVAILABLE, error="Очередь временно недоступна.")


def main():
    owner = int(os.environ["FCA_BOT_OWNER"])
    if owner <= 0:
        raise ValueError("Панель требует идентификатор владельца Telegram.")
    with AdminServer(("127.0.0.1", 8014), token=load_token(), owner=owner) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
