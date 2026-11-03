"""Минимальный клиент Telegram Bot API — только стандартная библиотека.

Бот опрашивает Телеграм сам (getUpdates, длинный опрос), поэтому входящий
порт на сервере не нужен. Токен приходит из файла (systemd
LoadCredential), а не из переменной окружения: окружение видно в
/proc у процессов того же пользователя и попадает в отчёты о падениях.

Токен никогда не печатается: в тексте ошибки адрес запроса заменяется.
"""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API = "https://api.telegram.org"
# Предел getFile у облачного Bot API — 20 МБ; больше бот скачать не может.
MAX_DOWNLOAD = 20 * 1024 * 1024


class TgError(RuntimeError):
    pass


def load_token(path: str | os.PathLike | None = None) -> str:
    """Токен из файла: явный путь, $CREDENTIALS_DIRECTORY/bot-token или FCA_BOT_TOKEN_FILE."""
    cands = [path, os.environ.get("FCA_BOT_TOKEN_FILE")]
    cd = os.environ.get("CREDENTIALS_DIRECTORY")
    if cd:
        cands.append(Path(cd) / "bot-token")
    for c in cands:
        if c and Path(c).is_file():
            tok = Path(c).read_text("utf-8").strip()
            if tok:
                return tok
    raise TgError("нет токена бота: файл /etc/fca/bot.token (LoadCredential=bot-token) пуст или не найден")


class Bot:
    def __init__(self, token: str, *, timeout: int = 60, opener=None):
        self._token = token
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    # ── транспорт ───────────────────────────────────────────────────────
    def _redact(self, s: str) -> str:
        return s.replace(self._token, "<token>")

    def call(self, method: str, **params):
        data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                for k, v in params.items() if v is not None}
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(f"{API}/bot{self._token}/{method}", data=body)
        return self._send(req, method, params.get("timeout", 0))

    def _send(self, req, method, long_poll=0):
        try:
            with self._open(req, timeout=self.timeout + int(long_poll or 0)) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read())
            except Exception:                                  # noqa: BLE001
                raise TgError(f"{method}: HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise TgError(self._redact(f"{method}: {e.reason}")) from None
        except (OSError, http.client.HTTPException, ValueError) as e:
            # Обрыв соединения, таймаут чтения, битый ответ: это сеть, а не
            # ошибка бота — цикл повторит запрос, процесс не падает.
            raise TgError(self._redact(f"{method}: {type(e).__name__}: {e}")) from None
        if not out.get("ok"):
            raise TgError(f"{method}: {out.get('error_code')} {out.get('description', '')}")
        return out["result"]

    def upload(self, method: str, field: str, path: Path, data: bytes | None = None, **params):
        """multipart/form-data для sendDocument. `data` — уже прочитанное
        содержимое (бот читает вложения сам, без перехода по ссылкам)."""
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in params.items():
            if v is None:
                continue
            v = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                      f'filename="{path.name}"\r\nContent-Type: {ctype}\r\n\r\n').encode()
                     + (path.read_bytes() if data is None else data) + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(f"{API}/bot{self._token}/{method}", data=b"".join(parts))
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        return self._send(req, method)

    # ── методы, которыми пользуется бот ─────────────────────────────────
    def updates(self, offset: int | None, wait: int = 50):
        return self.call("getUpdates", offset=offset, timeout=wait,
                         allowed_updates=["message", "callback_query"])

    def send(self, chat_id, text: str, buttons=None, **kw):
        markup = {"inline_keyboard": buttons} if buttons else None
        # Телеграм режет сообщение на 4096 символах — длинное режем сами.
        return self.call("sendMessage", chat_id=chat_id, text=text[:4000],
                         reply_markup=markup, disable_web_page_preview=True, **kw)

    def edit(self, chat_id, message_id, text: str, buttons=None):
        markup = {"inline_keyboard": buttons} if buttons else {"inline_keyboard": []}
        try:
            return self.call("editMessageText", chat_id=chat_id, message_id=message_id,
                             text=text[:4000], reply_markup=markup, disable_web_page_preview=True)
        except TgError as e:            # «message is not modified» — не ошибка
            if "not modified" not in str(e):
                raise

    def answer(self, callback_id: str, text: str = ""):
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:180])
        except TgError:
            pass

    def send_file(self, chat_id, path: Path, caption: str = "", data: bytes | None = None):
        return self.upload("sendDocument", "document", Path(path), data, chat_id=chat_id,
                           caption=caption[:1000])

    def download(self, file_id: str, dest: Path, limit: int = MAX_DOWNLOAD) -> int:
        info = self.call("getFile", file_id=file_id)
        size = info.get("file_size") or 0
        if size > limit:
            raise TgError(f"файл больше {limit // 2**20} МБ")
        req = urllib.request.Request(f"{API}/file/bot{self._token}/{info['file_path']}")
        try:
            with self._open(req, timeout=self.timeout) as r:
                blob = r.read(limit + 1)
        except urllib.error.URLError as e:
            raise TgError(self._redact(f"скачивание: {getattr(e, 'reason', e)}")) from None
        except (OSError, http.client.HTTPException) as e:
            raise TgError(self._redact(f"скачивание: {type(e).__name__}: {e}")) from None
        if len(blob) > limit:
            raise TgError(f"файл больше {limit // 2**20} МБ")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        return len(blob)
