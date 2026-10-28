"""Локальный сервер: ядро за JSON, один процесс, никакого облака.

ПОЧЕМУ СЕРВЕР, А НЕ ПРЕДГЕНЕРАЦИЯ. Витрина интерактивна: любые два
аэропорта, любой тип, ползунки загрузки и чека. Предгенерировать это
нельзя — и не из-за объёма (пар аэропортов полторы тысячи, это полбеды), а
потому что модель кусочно-нелинейна: минимальные сборы, полосы по массе,
ступени стоянки дают изломы. Интерполяция соврала бы ровно на них, то есть
там, где инструмент и нужен. Из-за тех же изломов `solve` пришлось делать
численным.

ПОЧЕМУ ЭТО НЕ ЗАМЕНЯЕТ `fca explain`. Два артефакта отвечают на разные
вопросы: разбор пересылают и прикладывают к письму, витрину крутят руками.
Статический разбор переживает и машину, и версию проекта; интерактивная
страница без процесса за ней мертва. Пытаться сделать один артефакт обоими
— то же самое, что делать один вид карты и показом, и проверкой.

ЗАМЕР, РАДИ КОТОРОГО ЭТО ВОЗМОЖНО. Первый расчёт 4,95 с — холодные
импорты. Повторные 14 мс, дальний маршрут 61 мс. Живой пересчёт по
ползунку возможен при одном условии: процесс живёт и прогрет. При запуске
процесса на каждый запрос пять секунд платились бы каждый раз.

ТРИ ТРЕБОВАНИЯ К ГРАНИЦЕ, которые легко потерять при переходе:

  происхождение доезжает до JSON. Если конечная точка отдаст голые числа,
  штриховка на столбике исчезнет, а с ней главное отличие продукта;

  «нельзя» — ответ, а не код ошибки (решение 93). FRA–SIN на A320
  возвращается со статусом 200 и разбором предела;

  локально. Хранилище остаётся файлом, страницы открываются без сети.
  Сервер этого не меняет и слушает только петлевой адрес.
"""

from __future__ import annotations

import json
from html import escape as html_escape
import re
import threading
import time
import traceback
import sqlite3
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
# Геометрия — ДАННЫЕ, а не ресурс пакета: лежит рядом с базой,
# собирается рецептом, в репозиторий не идёт (решение 1). Путь объявлен
# в `inventory.py`, потому что витрина данных должна показывать состояние
# того же файла, который отдаёт глобус; второе объявление разошлось бы с
# первым молча (решение 87).
from .inventory import GEO
from .guest import DOC_KINDS, GuestDB, GuestStore, valid_key
from . import seo

try:
    from .econ import COST_RU as _COST_RU
    from .econ import pax_count as _pax_count
except ImportError:            # подписей нет — показываем ключи как есть
    _COST_RU = {}

    def _pax_count(seats, lf):
        return int(seats * lf + 0.5 + 1e-9)


def _jsonable(x):
    if isinstance(x, set):
        return sorted(x)
    if hasattr(x, "__dict__") and not isinstance(x, type):
        return {k: _jsonable(v) for k, v in vars(x).items()}
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


def result_json(res) -> dict:
    """Единственный сериализатор `Result`. Им пользуются и CLI, и сервер.

    Не «добавить --json к выводу»: второй формат разойдётся с первым так
    же молча, как разошлись два отпечатка состава. Поля перечислены явно,
    а не через `vars()`, потому что добавленное в модель поле должно
    попадать сюда осознанно — иначе фронт однажды получит величину, о
    которой никто не думал, что она уедет наружу.
    """
    return {
        "route": {"origin": res.origin, "destination": res.destination,
                  "aircraft": res.aircraft, "distance_nm": res.distance_nm,
                  "block_h": res.block_h, "fuel_kg": res.fuel_kg,
                  # Кресла — решение перевозчика, а не свойство типа
                  # (решение 44). Фронт делил на 170, зашитые в двух
                  # местах: CASK у E195 считался на креслах A320.
                  "seats": int(res.inputs.get("seats") or 0),
                  # То же целое, что считало ядро (решение 229): round()
                  # Питона банковский и на 144,5 дал бы 144, а ядро — 145.
                  "pax": _pax_count(res.inputs.get("seats") or 0,
                                    float(res.inputs.get("load_factor") or 0))},
        "answer": {
            "breakeven_fare_eur": res.breakeven_fare_eur,
            "breakeven_lf": res.breakeven_lf,
            "cost_total": sum(res.cost.values()),
            "max_pax": res.max_pax,
            # Решение 93: «нельзя» доходит до интерфейса ответом, а не
            # отсутствием ответа и не кодом ошибки.
            "feasible": res.feasible,
            "feasibility": res.feasibility,
        },
        # Происхождение идёт РЯДОМ с величиной, а не отдельной таблицей:
        # разъехаться они могут только если лежат порознь.
        # Ключ и подпись — разные вещи (решение 27): ключ остаётся
        # английским и годится в идентификатор поля формы, подпись берётся
        # из `COST_RU` в `econ.py`. Свой словарь подписей здесь разошёлся
        # бы с тем так же молча, как два отпечатка состава.
        "cost": [{"item": k, "label": _COST_RU.get(k, k), "eur": v,
                  "prov": res.cost_prov.get(k, "?")}
                 for k, v in sorted(res.cost.items(), key=lambda x: -x[1])],
        "default_share": res.default_share(),
        "override_share": res.override_share(),
        "trace": [{"n": s.n, "group": s.group, "label": s.label,
                   "formula": s.formula, "subst": s.subst, "value": s.value,
                   "unit": s.unit, "prov": s.prov, "node": s.node,
                   "src": s.src,
                   # Адрес факта: по нему открывается сама запись. `None`
                   # означает «шаг не стоит на факте» — это ответ, а не
                   # пробел (решение 67).
                   "ref": s.ref} for s in res.trace],
        "charge_lines": res.charge_lines,
        # `None` и `{}` здесь значат разное, и сериализатор обязан это
        # сохранить: «не считалось» против «считалось, пропусков нет».
        "charge_gaps": res.charge_gaps,
        "caveats": res.caveats,
        "warnings": list(res.warnings),
        "degraded": res.degraded,
        "sources": list(res.sources),
        "currencies_seen": sorted(res.currencies_seen or []),
        "inputs": _jsonable(res.inputs),
        "trade": _jsonable(res.trade),
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "fca"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _client_ip(self) -> str:
        # За обратным прокси адрес клиента — в X-Forwarded-For; доверяем
        # ему, потому что витрина слушает только петлю, и заголовок ставит
        # наш же Caddy.
        fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return fwd or self.client_address[0]

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False,
                                    default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _public(self, body: bytes, ctype: str, code: int = 200) -> None:
        """Страница для поисковика: кэш на час вместо no-store."""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str, code: int = 301) -> None:
        self.send_response(code)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _pref_lang(self) -> str:
        """Язык для перехода с адреса без языка: первый из Accept-Language, иначе en."""
        for part in (self.headers.get("Accept-Language") or "").split(","):
            lg = part.strip()[:2].lower()
            if lg in seo.LANGS:
                return lg
        return "en"

    def _seo(self, u) -> bool:
        """Языковые адреса и служебные файлы. True — ответ отправлен."""
        ctx = self.server.ctx
        if u.path == "/robots.txt":
            self._public(seo.robots().encode(), "text/plain; charset=utf-8")
            return True
        if u.path == f"/{seo.INDEXNOW_KEY}.txt":
            self._public(seo.INDEXNOW_KEY.encode(), "text/plain; charset=utf-8")
            return True
        if u.path in ("/sitemap.xml", "/llms.txt"):
            types = ctx.seo_types()
            if u.path == "/sitemap.xml":
                self._public(seo.sitemap(types).encode(), "application/xml; charset=utf-8")
            else:
                self._public(seo.llms(types).encode(), "text/plain; charset=utf-8")
            return True
        if u.path in ("/og.png", "/favicon.svg"):
            f = WEB / u.path.lstrip("/")
            if not f.is_file():
                return False
            self._public(f.read_bytes(), "image/png" if u.path.endswith(".png") else "image/svg+xml")
            return True
        if u.path in ("/about", "/types"):
            self._redirect(f"/{self._pref_lang()}{u.path}", 302)
            return True
        m = seo.LANG_PATH.match(u.path)
        if not m:
            return False
        lang, tail = m.group(1), m.group(2) or ""
        if tail == "":
            self._redirect(f"/{lang}/" + (f"?{u.query}" if u.query else ""))
            return True
        html_t = "text/html; charset=utf-8"
        if tail == "/":
            self._send(200, seo.home(lang, _page().decode("utf-8")).encode("utf-8"), html_t)
            return True
        if tail in ("/about", "/about/"):
            self._public(seo.about_page(lang).encode("utf-8"), html_t)
            return True
        if tail in ("/types", "/types/"):
            self._public(seo.types_index(lang, ctx.seo_types()).encode("utf-8"), html_t)
            return True
        mt = re.match(r"^/type/([A-Za-z0-9]{2,4})/?$", tail)
        if mt:
            icao = mt.group(1).upper()
            if mt.group(1) != icao:
                self._redirect(f"/{lang}/type/{icao}")
                return True
            types = ctx.seo_types()
            entry = next((x for x in seo.public_types(types) if x["icao"] == icao), None)
            if entry is not None:
                info = ctx.aircraft_type({"icao": icao})
                self._public(seo.type_page(lang, info, entry, types).encode("utf-8"), html_t)
                return True
        self._send(404, seo.not_found(lang).encode("utf-8"), html_t)
        return True

    def log_message(self, fmt, *args):        # тише: страница делает много запросов
        if "200" not in (fmt % args):
            super().log_message(fmt, *args)

    # ── рабочее место гостя (решение 148) ──────────────────────────────
    COOKIE = "fca_ws"

    def _ws_key(self) -> str | None:
        """Ключ места из cookie. Валидность — по форме; существование
        проверяет `GuestDB.touch`."""
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == self.COOKIE and valid_key(v):
                return v.strip().lower()
        return None

    def _cookie(self, key: str | None) -> str:
        """Set-Cookie: год жизни, только свой сайт. Скрипту страницы cookie
        видна нарочно: ссылку на место надо показывать и после создания,
        а сервер её не хранит — только хеш. `Secure` — на домене;
        локальная витрина ходит по http. Политика конфиденциальности
        называет эти же сроки и флаги — меняете здесь, меняйте там."""
        base = f"{self.COOKIE}={key or ''}; Path=/; SameSite=Lax"
        if key is None:
            base += "; Max-Age=0"
        else:
            base += "; Max-Age=31536000"
        if self.server.ctx.public:
            base += "; Secure"
        return base

    def _ctx(self):
        """Контекст запроса: общий — или с наложенным слоем гостя."""
        return self.server.ctx.for_request(self._ws_key())

    def _json_cookie(self, obj, cookie: str, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                                    # noqa: N802
        """Запись — только своих типов ВС, и только через тот же парсер и
        гейт, что у файла в каталоге. У владельца сервер пишет файл сам:
        каталог остаётся источником (решение 1), база — производной от
        него. У гостя то же разбор ложится в его слой (решение 148).
        """
        u = urllib.parse.urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return self._json({"error": "тело запроса больше 1 МБ"}, 413)
            body = json.loads(self.rfile.read(n) or b"{}")
            ctx = self._ctx()
            if u.path == "/api/aircraft/save":
                return self._json(ctx.aircraft_save(body))
            if u.path == "/api/aircraft/delete":
                return self._json(ctx.aircraft_delete(body))
            if u.path.startswith("/api/ws"):
                return self._ws_post(u.path, body, ctx)
            return self._send(404, b"not found", "text/plain")
        except Exception as exc:                          # noqa: BLE001
            return self._json({"error": f"{type(exc).__name__}: {exc}",
                               "trace": traceback.format_exc()}, 400)

    def _ws_post(self, path: str, body: dict, ctx):
        gdb = self.server.ctx.gdb
        if gdb is None:
            return self._json({"error": "рабочие места на этой витрине выключены"}, 404)
        if path == "/api/ws/new":
            try:
                key = gdb.create(self._client_ip())
            except PermissionError as exc:
                return self._json({"error": str(exc)}, 429)
            w = gdb.touch(key)
            return self._json_cookie({"ok": True, "key": key, **gdb.info(w)},
                                     self._cookie(key))
        if path == "/api/ws/open":
            # Вход по ссылке /w#<ключ>: ключ приходит телом POST, а не
            # адресом — в журналах запросов (Caddy, витрина) его нет.
            key = str(body.get("key") or "").strip().lower()
            w = gdb.touch(key) if valid_key(key) else None
            if w is None:
                return self._json({"error": "такого места нет: ссылка устарела, место "
                                            "удалено или не открывалось больше года",
                                   "code": "missing"}, 404)
            return self._json_cookie({"ok": True, **gdb.info(w)}, self._cookie(key))
        if path == "/api/ws/forget":
            return self._json_cookie({"ok": True}, self._cookie(None))
        if not ctx.ws:
            return self._json({"error": "нет рабочего места: откройте ссылку или "
                                        "создайте место"}, 404)
        if path == "/api/ws/rotate":
            key = gdb.rotate(ctx.ws)
            return self._json_cookie({"ok": True, "key": key}, self._cookie(key))
        if path == "/api/ws/delete":
            gdb.delete(ctx.ws)
            return self._json_cookie({"ok": True}, self._cookie(None))
        if path == "/api/ws/import":
            st = gdb.import_(ctx.ws, body.get("data") or body,
                             merge=bool(body.get("merge", True)))
            return self._json({"ok": True, **st, **gdb.info(ctx.ws)})
        if path == "/api/ws/doc":
            gdb.put_doc(ctx.ws, body.get("kind", ""), body.get("name", ""), body.get("body"))
            return self._json({"ok": True, "docs": gdb.list_docs(ctx.ws)})
        if path == "/api/ws/doc/delete":
            ok = gdb.delete_doc(ctx.ws, body.get("kind", ""), body.get("name", ""))
            return self._json({"ok": ok, "docs": gdb.list_docs(ctx.ws)})
        return self._json({"error": "нет такого адреса", "path": path}, 404)

    def _ws_get(self, u, q: dict, ctx):
        gdb = self.server.ctx.gdb
        if u.path == "/w" or u.path.startswith("/w/"):
            # Ссылка на место — /w#<ключ>. Часть после «#» до сервера не
            # доходит, поэтому здесь просто витрина: ключ прочитает её
            # скрипт и отдаст телом POST /api/ws/open.
            return self._send(200, _page(), "text/html; charset=utf-8")
        if gdb is None:
            return self._json({"enabled": False})
        if u.path == "/api/ws":
            info = gdb.info(ctx.ws) if ctx.ws else {"exists": False}
            return self._json({"enabled": True, **info})
        if not ctx.ws:
            return self._json({"error": "нет рабочего места"}, 404)
        if u.path == "/api/ws/export":
            body = json.dumps(gdb.export(ctx.ws), ensure_ascii=False, indent=1).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition",
                             f'attachment; filename="fca-workspace-{date.today()}.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/api/ws/docs":
            return self._json({"docs": gdb.list_docs(ctx.ws, q.get("kind") or None)})
        if u.path == "/api/ws/doc":
            doc = gdb.get_doc(ctx.ws, q.get("kind", ""), q.get("name", ""))
            return self._json({"body": doc} if doc is not None else {"error": "нет такого документа"})
        return self._json({"error": "нет такого адреса", "path": u.path}, 404)

    # Страницы, просмотры которых считаются (не API и не файлы оформления).
    PAGES = {"/": "/", "/index.html": "/", "/map": "/map", "/data": "/data", "/report": "/report",
             "/impressum": "/impressum", "/datenschutz": "/datenschutz", "/w": "/w"}

    def _count(self, path: str) -> None:
        page = self.PAGES.get(path) or ("/w" if path.startswith("/w/") else None)
        m = seo.LANG_PATH.match(path)
        if page is None and m:
            # Языковые страницы — по виду, а не по адресу: страница типа одна
            # строка «/en/type», чтобы перебор адресов не раздувал таблицу.
            tail = (m.group(2) or "/").rstrip("/")
            kind = {"": "/", "/about": "/about", "/types": "/types"}.get(tail)
            if kind is None and tail.startswith("/type/"):
                kind = "/type"
            page = f"/{m.group(1)}{kind}".replace("//", "/") if kind else None
        v = getattr(self.server.ctx, "visits", None)
        if page and v is not None:
            try:
                v.hit(page, self._client_ip(), self.headers.get("User-Agent") or "")
            except sqlite3.Error:                   # счётчик не должен ронять страницу
                pass

    def do_GET(self):                                     # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self._count(u.path)
        try:
            if u.path == "/w" or u.path.startswith("/w/") or u.path.startswith("/api/ws"):
                return self._ws_get(u, q, self._ctx())
            ctx = self._ctx()
            if u.path == "/healthz":
                # Что сейчас на сервере: версия кода и дата снимка
                # справочника. По ней проверяет себя выкладка и ей
                # проверяете вы — «на домене то, что я думаю».
                return self._json(self.server.ctx.health())
            if self._seo(u):
                return
            if u.path in ("/api/solve", "/api/compare") and not self.server.ctx.allow(
                    self._client_ip()):
                return self._json({"error": "слишком часто: тяжёлые расчёты — не чаще "
                                            f"{self.server.ctx.HEAVY_PER_MIN} в минуту с адреса"},
                                  429)
            if u.path in ("/impressum", "/datenschutz"):
                return self._send(200, _legal_page(u.path.lstrip("/")),
                                  "text/html; charset=utf-8")
            if u.path in ("/", "/index.html"):
                return self._send(200, seo.home(None, _page().decode("utf-8")).encode("utf-8"),
                                  "text/html; charset=utf-8")
            if u.path == "/api/airports":
                return self._json(ctx.airports())
            if u.path == "/api/fx":
                return self._json(ctx.fx(q))
            if u.path == "/api/fleetbench":
                return self._json(ctx.fleet_bench(q))
            if u.path == "/api/network":
                return self._json(ctx.network(q, ip=self._client_ip()))
            if u.path == "/api/netcompare":
                return self._json(ctx.net_compare(q, ip=self._client_ip()))
            if u.path == "/report":
                code, page = ctx.fleet_report_html(q, ip=self._client_ip(), theme="dark")
                return self._send(code, page.encode("utf-8"), "text/html; charset=utf-8")
            if u.path == "/api/fleetreport.pdf":
                code, page = ctx.fleet_report_html(q, ip=self._client_ip(), theme="light")
                if code != 200:
                    return self._send(code, page.encode("utf-8"), "text/html; charset=utf-8")
                from .fleetreport_pdf import html_to_pdf
                try:
                    body = html_to_pdf(page)
                except RuntimeError as exc:
                    return self._json({"error": str(exc)}, 501)
                base = re.sub(r"[^A-Za-z0-9]", "", str(q.get("base") or ""))
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="fca-fleet-{base}.pdf"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path == "/api/fleetreport":
                return self._json(ctx.fleet_report(q, ip=self._client_ip())[0])
            if u.path == "/api/fleetreport.xlsx":
                rep, results = ctx.fleet_report(q, ip=self._client_ip())
                if results is None or rep.get("error"):
                    return self._json(rep, 202 if rep.get("pending") else 400)
                from .fleetreport_xlsx import build_xlsx
                body = build_xlsx(rep, results)
                base = re.sub(r"[^A-Za-z0-9]", "", str((rep.get("context") or {}).get("base") or ""))
                tys = "-".join(re.sub(r"[^A-Za-z0-9]", "", t["icao"]) for t in rep["types"])[:60]
                name = f"fca-fleet-{base}-{tys}.xlsx"
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-"
                                 "officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path == "/api/route":
                return self._json(ctx.route(q))
            if u.path == "/api/fact":
                return self._json(ctx.fact(q))
            if u.path == "/ui.css" or u.path.startswith("/fonts/"):
                # Оформление и шрифты — файлами из web/: один источник с
                # статическими страницами, которые вшивают то же самое.
                # Имя шрифта проверяется по списку файлов, а не склеивается
                # из пути: `..` в адресе не должен выходить из каталога.
                if u.path == "/ui.css":
                    from .ui import css
                    return self._send(200, css(inline_fonts=False).encode("utf-8"),
                                      "text/css; charset=utf-8")
                name = u.path.rsplit("/", 1)[-1]
                f = WEB / "fonts" / name
                if not name.endswith(".woff2") or not f.is_file():
                    return self._json({"error": f"нет {u.path}"}, 404)
                return self._send(200, f.read_bytes(), "font/woff2")
            if u.path in ("/geo.js", "/globe.js"):
                # Модули отдаются как есть, а не вшиваются: у `serve`
                # процесс живой, и правка geo.js видна по обновлению
                # страницы. Вшивание нужно статическому разбору, который
                # открывается без сервера, — там оно и остаётся.
                f = WEB / u.path.lstrip("/")
                if not f.exists():
                    return self._json({"error": f"нет {u.path}"}, 404)
                return self._send(200, f.read_bytes(),
                                  "text/javascript; charset=utf-8")
            if u.path == "/api/geo":
                return self._json(ctx.geo())
            if u.path == "/api/bench":
                return self._json(ctx.bench(q))
            if u.path == "/api/node":
                return self._json(ctx.node(q))
            if u.path == "/api/data":
                return self._json(ctx.data())
            if u.path == "/api/browse":
                return self._json(ctx.browse(q))
            if u.path == "/data":
                return self._send(200, _page("data.html"), "text/html; charset=utf-8")
            if u.path == "/map":
                return self._send(200, ctx.map_page(), "text/html; charset=utf-8")
            if u.path == "/api/aircraft":
                return self._json(ctx.aircraft())
            if u.path == "/api/solve":
                return self._json(ctx.solve(q))
            if u.path == "/api/compare":
                return self._json(ctx.compare(q))
            if u.path == "/api/aircraft/type":
                return self._json(ctx.aircraft_type(q))
            if u.path == "/api/aircraft/draft":
                # Заготовка JSON для каталога своих типов: сервер НЕ пишет
                # в хранилище, файл кладёт человек, заводит refresh, принимает
                # review — тот же путь, что у тарифов (решение 4).
                body = json.dumps(ctx.aircraft_draft(q),
                                  ensure_ascii=False, indent=1).encode()
                name = (q.get("as") or "user_type").replace(":", "_") + ".json"
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json({"error": "нет такого адреса", "path": u.path}, 404)
        except KeyError as exc:
            # Неизвестный аэропорт — ошибка ЗАПРОСА, а не поломка. Три
            # разных исхода нельзя валить в один: 400 «вы просите то, чего
            # нет», 500 «у нас сломалось» и 200 «нельзя, вот предел»
            # (решение 93). Пятисотка на опечатку в коде аэропорта учит
            # не верить пятисоткам.
            self._json({"error": str(exc).strip("'"), "kind": "bad_request"}, 400)
        except Exception as exc:                          # noqa: BLE001
            # Отказ расчёта — это НЕ «нельзя»: первое дефект, второе ответ.
            # Здесь честная пятисотка с трассировкой, а невыполнимый рейс
            # приходит с 200 и разбором предела.
            self._json({"error": f"{type(exc).__name__}: {exc}",
                        "kind": "server_error",
                        "traceback": traceback.format_exc().splitlines()[-6:]},
                       500)


class Context:
    """Прогретое ядро и единственная точка доступа к хранилищу.

    Замок нужен потому, что соединение SQLite не потокобезопасно, а сервер
    многопоточный: страница шлёт несколько запросов сразу. Расчёт занимает
    14 мс, так что очередь под замком незаметна, а гонка — заметна.
    """

    # Порог и пересчёт `solve` и `compare` — секунды процессора; в публичном
    # режиме цикл в браузере положил бы сервер. Локально ограничения нет.
    HEAVY_PER_MIN = 6

    def allow(self, ip: str) -> bool:
        if not self.public:
            return True
        import collections
        import time
        now = time.monotonic()
        with self._rl_lock:
            q = self._rl.setdefault(ip, collections.deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.HEAVY_PER_MIN:
                return False
            q.append(now)
            # Адрес нужен ровно на окно в минуту. Раз в минуту выметаем
            # всех, чьё последнее обращение старше окна: политика
            # конфиденциальности обещает, что полный адрес живёт в памяти
            # не дольше двух минут, и это обещание держит этот код.
            if now - self._rl_swept > 60:
                self._rl_sweep(now)
            return True

    def _rl_sweep(self, now: float) -> None:
        """Забыть адреса, чьё последнее обращение старше окна. Под `_rl_lock`."""
        for k in [k for k, v in self._rl.items() if not v or now - v[-1] > 60]:
            del self._rl[k]
        self._rl_swept = now

    def health(self) -> dict:
        import os
        out = {"ok": True, "public": self.public}
        vf = os.environ.get("FCA_VERSION_FILE")
        if vf and os.path.exists(vf):
            out["version"] = open(vf, encoding="utf-8").read().strip()
        with self.lock:
            db = self.store.db
            has = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                             "AND name='publish_meta'").fetchone()
            if has:
                out["snapshot"] = {k: v for k, v in db.execute(
                    "SELECT key, value FROM publish_meta")}
            if self._facts_n is None:
                self._facts_n = db.execute(
                    "SELECT COUNT(*) FROM facts WHERE valid_to IS NULL").fetchone()[0]
        out["facts"] = self._facts_n
        if self.gdb is not None:
            with self.gdb.lock:
                out["workspaces"] = self.gdb.db.execute(
                    "SELECT COUNT(*) FROM workspaces").fetchone()[0]
        missing = [k for k in LEGAL_FIELDS if not _legal_values().get(k)]
        if missing:
            # Не роняет `ok`: выкладка кода не должна ждать юридического
            # текста. Но видно и вам, и тестовому прогону.
            out["legal_missing"] = missing
        return out

    def __init__(self, store, registry, public: bool = False, gdb: GuestDB | None = None):
        self.store, self.registry = store, registry
        self.lock = threading.Lock()
        self._apts = None
        # Слой гостя (решение 148): база мест и — у копии контекста на
        # запрос — ключ места. У общего контекста `ws` пуст.
        self.gdb, self.ws = gdb, None
        # Публичная витрина: запись в общее хранилище закрыта. Свои типы
        # гостей — слой сценария (решение 33), ему нужна своя область
        # видимости по автору; пока её нет, сохранение честно отказывает.
        self.public = public
        self._rl, self._rl_lock, self._rl_swept = {}, threading.Lock(), 0.0
        self._pruned = 0.0
        self._facts_n = None
        self._net_cache: dict = {}
        self._net_jobs: dict = {}
        # Плечи и обходы — по концам и типу, переживают смену состава.
        self._leg_cache: dict = {}
        self._detour_cache: dict = {}
        if public:
            # Метла по часам, а не только по запросам: на тихом сайте
            # следующего тяжёлого запроса можно ждать часами, а политика
            # обещает «не дольше двух минут» (окно 60 с + шаг 30 с).
            def _sweeper():
                import time
                while True:
                    time.sleep(30)
                    with self._rl_lock:
                        self._rl_sweep(time.monotonic())
                    # Места, не открытые год, — раз в сутки (решение 148)
                    if self.gdb is not None and time.monotonic() - self._pruned > 86400:
                        try:
                            n = self.gdb.prune()
                            self._pruned = time.monotonic()
                            if n:
                                print(f"рабочие места: удалено {n}, не открывали год")
                        except Exception as exc:                 # noqa: BLE001
                            print(f"чистка мест не удалась: {exc}")
            threading.Thread(target=_sweeper, daemon=True, name="rl-sweep").start()

    def for_request(self, key: str | None):
        """Контекст запроса. С ключом существующего места — мелкая копия
        с наложенным хранилищем: замок, кэши и ограничитель общие, своё
        только `store` и `ws`. Без места — сам общий контекст."""
        if self.gdb is None or not key:
            return self
        ws = self.gdb.touch(key)
        if ws is None:
            return self
        import copy
        c = copy.copy(self)
        c.store, c.ws = GuestStore(self.store, self.gdb, ws), ws
        return c

    def _settings_overrides(self) -> list[str]:
        """Ставки флота и прочие переопределения из документа `settings`
        места — строками вида `fleet_economics.A321.lease_eur_month=380000`,
        тем же слоем сценария, что `--set` (решение 10)."""
        if not self.ws:
            return []
        doc = self.gdb.get_doc(self.ws, "settings", "default") or {}
        ov = doc.get("overrides") or {}
        return [f"{k}={v}" for k, v in ov.items() if v not in ("", None)]

    # Валюты, в которых витрина ПОКАЗЫВАЕТ деньги. Считается всё в евро;
    # пересчёт — только на экране, курсом с датой и провенансом рядом.
    # Нет курса — валюта остаётся в списке выключенной, а не исчезает:
    # «нет курса» — состояние, а не поломка (решение 70).
    DISPLAY_CURRENCIES = ("EUR", "USD", "RUB", "INR", "CNY")

    def fx(self, q: dict) -> dict:
        from .fx import quote
        as_of = q.get("as_of") or date.today().isoformat()
        with self.lock:
            rates = {c: quote(self.store, c, as_of) for c in self.DISPLAY_CURRENCIES}
        return {"base": "EUR", "as_of": as_of, "rates": rates}

    def fleet_bench(self, q: dict) -> dict:
        """Полоса бенчмарка по типу для панели «Флот» (M11), деньги в евро.

        Только то, что показывается рядом с полями ввода: налёт, владение
        по балансу, ТОиР и лётный экипаж на блок-час — медиана и p25–p75,
        число перевозчиков и плечо выборки. Подробности — `fca bench`.
        """
        from . import bench as B
        icao = (q.get("ac") or "").upper()
        if not icao:
            return {"error": "нужен ac"}
        with self.lock:
            b = B.type_bench(self.store, icao)
            rate = B.usd_per_eur(self.store, b["year"])[0] if b else None
        if not b or not b.get("bands") or not rate:
            return {"icao": icao, "available": False}
        k = {"util_h_month": 1.0, "block_per_dep": 1.0}
        out = {}
        for m in ("util_h_month", "own_per_ac_month", "maint_per_bh", "cockpit_per_bh",
                  "block_per_dep"):
            bd = b["bands"].get(m)
            if bd:
                f = k.get(m, 1.0 / rate)
                out[m] = {"p25": bd.p25 * f, "p50": bd.p50 * f, "p75": bd.p75 * f, "n": bd.n}
        return {"icao": icao, "available": True, "source": "BTS Form 41",
                "year": b["year"], "carriers": len(b["carriers"]), "bands": out,
                "usd_per_eur": rate}

    def airports(self) -> list[dict]:
        if self._apts is None:
            with self.lock:
                rows = self.store.db.execute(
                    "SELECT key, value_text FROM facts WHERE domain='airport' "
                    "AND valid_to IS NULL").fetchall()
            # Названия на разных языках: поиск должен находить и по
            # «Франкфурт», и по «法兰克福», а не только по коду.
            with self.lock:
                names: dict[str, dict[str, str]] = {}
                for key, nm in self.store.db.execute(
                        """SELECT key, value_text FROM facts
                           WHERE domain = 'airport_name' AND valid_to IS NULL"""):
                    icao, _, loc = (key or "").partition("/")
                    if icao and nm:
                        names.setdefault(icao, {})[loc] = nm
            out = []
            for key, txt in rows:
                if not txt:
                    continue
                p = txt.split("|", 3)
                if len(p) < 4 or not p[1]:
                    continue
                tr = names.get(p[1], {})
                try:
                    lat, lon = (float(x) for x in p[0].split(",", 1))
                except (ValueError, IndexError):
                    lat = lon = None
                out.append({"key": key, "icao": p[1], "iso": p[2],
                            "lat": lat, "lon": lon,
                            "name": tr.get("en") or p[3],
                            # Строка поиска собирается ОДИН раз здесь, а не
                            # на каждое нажатие в браузере: две тысячи
                            # аэропортов на пять локалей — это работа,
                            # которую незачем делать заново по букве.
                            "find": " ".join([key, p[1], p[3]] + list(tr.values())).lower(),
                            "tr": tr})
            # Сорок восемь тысяч в браузер не отдать. Правило отбора
            # ЯВНОЕ: аэропорты, по которым есть разобранный тариф, плюс
            # те, что наблюдались. Не «первые N по алфавиту» — такой
            # список выглядит осмысленным и не является им.
            # ВЕС АЭРОПОРТА для уровней показа на карте. Пассажиропотока
            # у нас пока нет — он приходит на M10, и до тех пор «больше
            # миллиона в год» не величина, а пожелание. Зато есть
            # ИЗМЕРЕННОЕ: число наблюдённых рейсов. Оно не то же самое,
            # но оно наше, у него есть происхождение, и заменить его
            # потоком, когда тот появится, — одна строка.
            # Источник — агрегаты `observed/frequency/<пара>/<дата>` (факты),
            # а не сырая таблица `observations`: `fca publish` её вычищает
            # (в справочнике только агрегаты), и на сервере аэропорты с
            # наблюдениями пропадали из списка и с карты. Сырое читается
            # ДОПОЛНИТЕЛЬНО — у владельца оно свежее последней свёртки.
            with self.lock:
                flights: dict[str, float] = {}
                seen: set[str] = set()
                daily: dict[str, float] = {}
                for key, value in self.store.db.execute(
                        "SELECT key, value FROM facts WHERE domain='observed' "
                        "AND key LIKE 'frequency/%' AND valid_to IS NULL"):
                    daily[key[len("frequency/"):]] = float(value or 0)
                for key, value in self.store.db.execute(
                        "SELECT key, COUNT(*) FROM observations WHERE kind='frequency' "
                        "GROUP BY key"):
                    daily[key] = max(daily.get(key, 0.0), float(value or 0))
                for key, n in daily.items():
                    pair = (key or "").split("/")[0]
                    if "-" not in pair:
                        continue
                    for side in pair.split("-"):
                        flights[side] = flights.get(side, 0) + (n or 1)
                        seen.add(side)
                tariffed = {r[0].split("/")[0] for r in self.store.db.execute(
                    "SELECT DISTINCT key FROM facts WHERE domain='airport_charge'")}
            # Перечень, который ведёт владелец, — третий источник списка.
            # Без него в выборе оставались только те, по кому уже есть
            # тариф или наблюдения, то есть пять аэропортов: человек не мог
            # выбрать то, ради чего список и заводил.
            with self.lock:
                watch = {r[0] for r in self.store.db.execute(
                    "SELECT DISTINCT key FROM facts WHERE domain='airport_watch' "
                    "AND valid_to IS NULL")}
            keep = tariffed | seen | watch
            for a in out:
                a["tier"] = 1 if a["icao"] in tariffed else 3
                a["seen"] = a["icao"] in seen
                # Откуда аэропорт попал в список — видно в интерфейсе:
                # «ведём» и «есть тариф» это разные состояния, и путать их
                # значит обещать данные, которых нет.
                a["watch"] = a["icao"] in watch
                a["flights"] = round(flights.get(a["icao"], 0))
            self._apts = sorted((a for a in out if a["icao"] in keep),
                                key=lambda a: (a["tier"], a["icao"]))
        return self._apts

    def resolve(self, code: str) -> str:
        """Код аэропорта -> ключ хранилища.

        Домен `airport` ключуется кодом ИАТА, а весь остальной продукт
        говорит на ИКАО: тариф, PCN и зона аэронавигации публикуются по
        нему. Пока нет домена-указателя (решения 103 и 104), перевод
        делается здесь — и делается ФОРГИВИНГ: принимаем и то, и другое,
        потому что пользователь наберёт то, что знает, а не то, чем мы
        ключуем.
        """
        c = (code or "").strip().upper()
        for a in self.airports():
            if c in (a["key"], a["icao"]):
                return a["key"]
        return c

    def _kwargs(self, q: dict) -> dict:
        """Параметры запроса -> аргументы `route_economics`.

        ОДИН разбор на маршрут и порог. Пока `solve` собирал аргументы
        отдельно, месяц и переопределения терялись по дороге — та же
        ловушка, что у `--month` в CLI: ключ принят, в `base_kwargs` не
        попал, расчёт молча пошёл без него.
        """
        from .overrides import parse_set
        kw = dict(
            aircraft=q.get("ac", "A320"),
            load_factor=float(q.get("lf", 0.80)),
            fare_eur=float(q["fare"]) if q.get("fare") else None,
            as_of=q.get("as_of") or None,
            month=int(q["month"]) if q.get("month") else None,
            alternate_nm=float(q["alt"]) if q.get("alt") else None,
            freq_week=float(q["freq"]) if q.get("freq") else None,
            util_mode=q.get("util", "fleet_average"),
            operator=q.get("operator", "*"),
            # Кресла рейсом: положения «по сертификату» и «своя». Пусто —
            # компоновка перевозчика (`operator`), как и раньше.
            seats=int(float(q["seats"])) if q.get("seats") else None,
        )
        sets = [x for x in q.get("set", "").split("~") if x]
        own = self._settings_overrides()
        if sets or own:
            # Своё из места — под явным `set`: заданное в запросе главнее
            # сохранённого, как флаг главнее файла настроек.
            kw["overrides"] = {**parse_set(own), **parse_set(sets)} if own else parse_set(sets)
        return kw

    def route(self, q: dict) -> dict:
        from .econ import route_economics
        kw = self._kwargs(q)
        # Разрешение кодов ДО замка. Прежде `resolve` стоял аргументом
        # внутри `with self.lock`, звал `airports`, который берёт тот же
        # замок, — а `Lock` не реентрантный, и сервер вставал намертво,
        # приняв соединение и не ответив. Взять `RLock` было бы проще и
        # хуже: он прячет вложенный захват вместо того, чтобы его не
        # допускать.
        o = self.resolve(q.get("origin", "FRA"))
        d = self.resolve(q.get("destination", "BCN"))
        with self.lock:
            res = route_economics(self.store, o, d, **kw)
            out = result_json(res)
            # Поток пары (M10): рядом с ответом, в расчёт не входит —
            # нужен для обращения «какая доля рынка нужна» и подбора типа.
            try:
                from .traffic import nearby, pair_flow
                oi, di = res.inputs.get("origin_icao"), res.inputs.get("dest_icao")
                out["traffic"] = pair_flow(self.store, oi, di, kw.get("as_of"), kw.get("month"))
                # Другой аэропорт того же города с потоком — рядом с ответом:
                # Дели–Нави-Мумбаи легко принять за «весь Мумбаи».
                out["traffic"]["nearby"] = nearby(self.store, oi, di, kw.get("as_of"),
                                                  kw.get("month"))
            except Exception as exc:                       # noqa: BLE001
                out["traffic"] = {"pax_month": None, "src": f"не прочитан: {exc}"}
        return out

    def solve(self, q: dict) -> dict:
        """Порог по каждому параметру, который человек может менять.

        Та же функция, что печатает запас прочности в `fca explain`, —
        `solve.margins`, не второй солвер под витрину. Ответ содержит
        статус каждой строки: `ok`, `unreachable`, `failed` — три разных
        утверждения, и витрина обязана показать их тремя способами.
        """
        from .solve import LEASE_TERMS, margins
        kw = self._kwargs(q)
        o = self.resolve(q.get("origin", "FRA"))
        d = self.resolve(q.get("destination", "BCN"))
        if not kw.get("fare_eur"):
            # Без тарифа нет вопроса «сколько до нуля» (см. `margins`).
            # Пустой список без причины прочтётся как «порогов нет».
            return {"rows": [], "why": "не задан чек: без тарифа порог "
                    "не от чего считать", "lease_terms": LEASE_TERMS}
        with self.lock:
            rows = margins(self.store, o, d, kw, kw["aircraft"])
        return {"rows": rows, "lease_terms": LEASE_TERMS,
                # Что именно передано в ядро — чтобы расхождение с вкладкой
                # «Маршрут» (месяц, --set) было видно, а не угадывалось.
                "inputs": {k: _jsonable(v) for k, v in kw.items()}}

    # ── сеть (решения 154–159) ───────────────────────────────────────────
    # Сложить сеть — вызовы ядра на каждое плечо, секунды; переиграть её с
    # другими ценами, частотами и парком — миллисекунды. Поэтому сложенные
    # пары кэшируются по тому, что их определяет (аэропорты, база, тип,
    # месяц, переопределения), а ввод человека накладывается заново.
    # Сложенных сетей в памяти. Было 6 на весь сервер: сравнение пяти
    # типов у двух человек одновременно вытесняло своё же из кэша, и опрос
    # страницы запускал расчёт заново. Сеть — десятки плеч, сотни КБ.
    NET_CACHE = 64
    # Одновременных сборок сети. Расчёт — чистый Python под одной
    # блокировкой интерпретатора: десять параллельных потоков не быстрее
    # двух, зато каждый ждёт в десять раз дольше. Остальные — в очереди,
    # и страница показывает место в ней.
    NET_WORKERS = 2
    _net_sem = threading.Semaphore(NET_WORKERS)
    _net_queue: list = []
    _net_queue_lock = threading.Lock()

    @staticmethod
    def _pairs_q(raw: str, cast=float) -> dict:
        """«ALA-FRA:300,ALA-DME:160» → {"ALA-FRA": 300.0, …}."""
        out = {}
        for part in (raw or "").replace("~", ",").split(","):
            k, _, v = part.strip().partition(":")
            if k and v:
                try:
                    out[k.strip().upper()] = cast(v)
                except ValueError:
                    continue
        return out

    def network(self, q: dict, ip: str = "") -> dict:
        """Сеть: сложить (дорого, в фоне, с ходом) и просимулировать (дёшево).

        Первый запрос с новым составом запускает поток и отвечает
        `pending` с ходом «пар посчитано»; страница опрашивает тот же
        адрес, пока не придёт ответ. Поток работает на СВОЁМ соединении с
        базой, а не под общим замком: иначе минуту расчёта сети не
        отвечала бы вся витрина, включая /healthz. Плечи и обходы
        кэшируются по концам и типу, поэтому седьмой аэропорт к шести
        прежним — это только его плечи.
        """
        from copy import deepcopy
        from .network import ALPHA, apply_inputs, load_closures, simulate
        NET_ONLY = ("fares", "freqs", "market", "util_h", "lf", "fleet", "lease", "maint_fh", "maint_fc",
                    "fare_mult", "fare_conv", "alpha", "airports", "base")
        kw = self._kwargs({k: v for k, v in q.items() if k not in NET_ONLY})
        airports = [self.resolve(c) for c in (q.get("airports") or "").split(",") if c.strip()]
        base = self.resolve(q.get("base") or (airports[0] if airports else "FRA"))
        if len(set(airports) | {base}) < 2:
            return {"error": "нужны хотя бы два аэропорта"}
        ov = kw.get("overrides") or {}
        as_of = str(kw.get("as_of") or date.today())
        form_key = (self.ws, tuple(sorted(set(airports) | {base})), base, kw["aircraft"],
                    kw.get("month"), kw.get("operator"),
                    tuple(sorted((k, str(v)) for k, v in ov.items())), as_of)
        cached = self._net_cache.get(form_key)
        if cached is None:
            job = self._net_jobs.get(form_key)
            if job is None:
                if ip and not self.allow(ip):
                    return {"error": f"слишком часто: расчёт состава сети — не чаще "
                                     f"{self.HEAVY_PER_MIN} в минуту с адреса"}
                job = self._start_net_job(form_key, airports, base, kw, ov, as_of)
            if job.get("error"):
                self._net_jobs.pop(form_key, None)
                return {"error": job["error"], "pairs": [], "network": None}
            if not job.get("done"):
                return {"pending": True, "progress": dict(job["progress"])}
            cached = self._net_cache.get(form_key)
            self._net_jobs.pop(form_key, None)
            if cached is None:
                return {"error": "расчёт состава не оставил результата", "pairs": [], "network": None}
        pairs, fleet, formed_ms = deepcopy(cached[0]), deepcopy(cached[1]), cached[2]

        apply_inputs(pairs, self._pairs_q(q.get("fares", "")), self._pairs_q(q.get("market", "")))
        carrier = next((p.ca for p in pairs if p.a == base), "") or next((p.cb for p in pairs if p.b == base), "")
        closures = load_closures()
        closed = sorted({z for c in closures if c.active(as_of) and c.applies_to(carrier)
                         for z in c.zones})
        out = {"base": base, "carrier": carrier, "aircraft": kw["aircraft"], "as_of": as_of,
               "closed_zones": closed, "formed_ms": formed_ms, "cached": True,
               "pairs": [_jsonable(p) for p in pairs], "network": None, "error": None}
        if fleet is None:
            out["error"] = "ни одной пары с правом летать — сети нет"
            return out
        freq = self._pairs_q(q.get("freqs", ""), int) or None
        try:
            net = simulate(pairs, fleet=fleet, fleet_n=int(float(q.get("fleet") or 1)),
                           freq=freq,
                           util_h_month=float(q["util_h"]) if q.get("util_h") else None,
                           lease_eur_month=float(q["lease"]) if q.get("lease") else None,
                           maint_fh=float(q["maint_fh"]) if q.get("maint_fh") else None,
                           maint_fc=float(q["maint_fc"]) if q.get("maint_fc") else None,
                           fare_mult=float(q.get("fare_mult") or 1.0),
                           fare_conv=float(q["fare_conv"]) if q.get("fare_conv") not in (None, "") else None,
                           lf_ref=float(q.get("lf") or 0.8),
                           alpha=float(q["alpha"]) if q.get("alpha") else ALPHA)
        except ValueError as exc:
            out["error"] = str(exc)
            out["pairs"] = [_jsonable(p) for p in pairs]     # с причинами «нет цены»
            out["fleet"] = _jsonable(fleet)
            return out
        out["network"] = _jsonable(net)
        out["pairs"] = [_jsonable(p) for p in pairs]
        out["fleet"] = _jsonable(fleet)
        return out

    NET_CMP_MAX = 5

    def net_compare(self, q: dict, ip: str = "") -> dict:
        """Одна сеть на нескольких типах (Ф1 для сети, решение 189).

        Сначала человек выбирает, какие типы сравнить, потом сеть
        считается на каждом — тем же `network`, с тем же парком в бортах,
        ценой, загрузкой и частотами. Лизинг и налёт из полей сети
        относятся к типу, выбранному в шапке; у остальных — их собственные
        ставки, иначе A320 и E195 считались бы с одной арендой. Условия
        начисления, которые задаёт тип (шумовая категория, класс, группа
        стоянки), у чужих типов сняты — как в сравнении на маршруте.

        Одно сравнение — одно «тяжёлое» обращение для ограничителя: типы
        складываются в фоне каждый своим потоком, страница опрашивает
        тот же адрес, пока не придут все.
        """
        chosen = (q.get("ac") or "").upper()
        types = list(dict.fromkeys(t for t in (q.get("types") or "").upper().split(",") if t))
        if not types:
            return {"error": "не выбрано ни одного типа"}
        if len(types) > self.NET_CMP_MAX:
            return {"error": f"типов {len(types)}, предел {self.NET_CMP_MAX} за одно сравнение"}
        key = (self.ws, ip, tuple(types), q.get("airports"), q.get("base"), q.get("month"))
        seen = self.__dict__.setdefault("_netcmp_seen", {})
        if key not in seen:
            if ip and not self.allow(ip):
                return {"error": f"слишком часто: сравнение сети — не чаще "
                                 f"{self.HEAVY_PER_MIN} в минуту с адреса"}
            if len(seen) > 200:
                seen.clear()
            seen[key] = True
        results, pend, dropped = self._net_by_type(q, chosen, types)
        rows = [{"icao": t, "status": "pending"} if results[t] is None
                else self._net_summary(t, results[t], own=t == chosen) for t in types]
        out = {"rows": rows, "chosen": chosen, "fleet": int(float(q.get("fleet") or 1)),
               "lf_ref": float(q.get("lf") or 0.8), "dropped_ctx": dropped}
        if pend["types_left"]:
            out.update(pending=True, progress=pend)
        return out

    def _net_by_type(self, q: dict, chosen: str, types: list) -> tuple[dict, dict, list]:
        """Сеть на каждом типе: {тип: ответ `network` | None, пока считается}."""
        own_sets = [x for x in (q.get("set") or "").split("~") if x]
        foreign_sets = [x for x in own_sets
                        if not (x.startswith("charge_context.")
                                and x.split("=")[0].split(".")[-1] in self.TYPE_CTX)]
        results, pend = {}, {"done": 0, "total": 0, "types_left": 0}
        for t in types:
            q2 = dict(q, ac=t)
            q2.pop("types", None)
            if t != chosen:
                for k in ("util_h", "lease", "maint_fh", "maint_fc"):
                    q2.pop(k, None)
                q2["set"] = "~".join(foreign_sets)
            r = self.network(q2, ip="")
            if r.get("pending"):
                pr = r.get("progress") or {}
                pend["done"] += pr.get("done", 0)
                pend["total"] += pr.get("total", 0)
                pend["types_left"] += 1
                if pr.get("queue"):
                    pend["queue"] = min(pend.get("queue") or 10 ** 6, pr["queue"])
                results[t] = None
                continue
            results[t] = r
        dropped = sorted({x.split("=")[0].split(".")[-1] for x in own_sets}
                         - {x.split("=")[0].split(".")[-1] for x in foreign_sets})
        return results, pend, dropped

    def fleet_report(self, q: dict, ip: str = "") -> tuple[dict, dict | None]:
        """Отчёт по парку (Ф5) по тем же вводам, что сравнение сети.

        Возвращает (отчёт, ответы сети по типам) — второе нужно выгрузке в
        Excel. Пока какой-то тип считается — `pending`, как у сравнения;
        лимит тяжёлых обращений тот же: отчёт по уже посчитанному
        сравнению берётся из кэша и лимит не тратит.
        """
        from .fleetreport import build
        chosen = (q.get("ac") or "").upper()
        types = list(dict.fromkeys(t for t in (q.get("types") or "").upper().split(",") if t))
        if not types:
            return {"error": "не выбрано ни одного типа"}, None
        if len(types) > self.NET_CMP_MAX:
            return {"error": f"типов {len(types)}, предел {self.NET_CMP_MAX} за один отчёт"}, None
        key = (self.ws, ip, tuple(types), q.get("airports"), q.get("base"), q.get("month"))
        seen = self.__dict__.setdefault("_netcmp_seen", {})
        if key not in seen:
            if ip and not self.allow(ip):
                return {"error": f"слишком часто: отчёт по парку — не чаще "
                                 f"{self.HEAVY_PER_MIN} в минуту с адреса"}, None
            if len(seen) > 200:
                seen.clear()
            seen[key] = True
        results, pend, dropped = self._net_by_type(q, chosen, types)
        if pend["types_left"]:
            return {"pending": True, "progress": pend}, None
        acs = self.aircraft()
        names = {a["icao"]: a["name"] for a in acs}
        geom = {a["icao"]: a.get("geom") for a in acs}
        any_r = next((r for r in results.values() if r), {}) or {}
        # Допущения плана — из запроса; цена к рынку по умолчанию та же,
        # что у сети на витрине.
        assume = {k: q.get(k) for k in ("share", "price", "elasticity", "lf_target", "min_freq",
                                         "reserve", "share_cap", "fare_conv")}
        if not assume["price"] and q.get("fare_mult"):
            assume["price"] = q["fare_mult"]
        rep = build(results, assume=assume, chosen=chosen, names=names, geom=geom, context={
            "base": any_r.get("base"), "carrier": any_r.get("carrier"),
            "airports": sorted({p.get("a") for p in any_r.get("pairs") or []}
                               | {p.get("b") for p in any_r.get("pairs") or []} - {None}),
            "month": int(q["month"]) if q.get("month") else None,
            "as_of": any_r.get("as_of"), "dropped_ctx": dropped,
            "market_given": bool(q.get("market")), "fares_given": bool(q.get("fares")),
            "freqs_given": bool(q.get("freqs"))})
        return rep, results

    def fleet_report_html(self, q: dict, ip: str = "", *, theme="dark") -> tuple[int, str]:
        """Документ отчёта: тёмный — страница сайта, светлый — для PDF."""
        from .fleetreport import assumptions
        from .fleetreport_doc import Doc, render, share_line, toolbar
        from .ui import css
        lang = q.get("lang") if q.get("lang") in ("ru", "en", "de") else "ru"
        cur, rate = (q.get("cur") or "EUR").upper(), 1.0
        if cur != "EUR":
            try:
                rate = float(((self.fx({}) or {}).get("rates") or {}).get(cur, {}).get("rate") or 0)
            except Exception:                              # noqa: BLE001
                rate = 0.0
            if not rate:
                cur, rate = "EUR", 1.0
        rep, _ = self.fleet_report(q, ip)
        D = Doc(lang, cur, rate)
        if rep.get("error"):
            return (400, f'<!doctype html><html><head><meta charset="utf-8">'
                         f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                         f'<style>{css(inline_fonts=False)}</style></head><body class="doc" '
                         f'style="padding:40px 24px"><p>{D.T("Не собрать.")} {html_escape(rep["error"])}</p>'
                         f'</body></html>')
        if rep.get("pending"):
            # Та же зона ожидания, что на витрине: страница перезагружается
            # раз в две секунды, фраза эфира — новая на каждой загрузке.
            import random
            pr = rep.get("progress") or {}
            ph = D.T(random.choice(LOADER_PHRASES))
            if pr.get("total"):
                sub = f'{pr.get("done", 0)} / {pr["total"]} {D.T("пар посчитано")}'
            elif pr.get("queue"):
                sub = f'{D.T("в очереди на взлёт:")} {pr["queue"]}'
            else:
                sub = D.T("ядро считает каждое плечо сети")
            return (202, f'<!doctype html><html><head><meta charset="utf-8">'
                         f'<meta http-equiv="refresh" content="2">'
                         f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                         f'<style>{css(inline_fonts=False)}{LOADER_CSS}</style></head>'
                         f'<body style="margin:0;min-height:100vh;background:var(--bg)">'
                         f'{LOADER_SVG.format(ph=html_escape(ph), sub=html_escape(sub))}</body></html>')
        types = [t["icao"] for t in rep.get("types") or [] if t.get("status") == "ok"]
        tb = toolbar(D, q, assumptions(q), types, share_line(D, rep)) if theme == "dark" else ""
        return 200, render(rep, theme=theme, lang=lang, cur=cur, rate=rate, toolbar=tb,
                           css_text=css(inline_fonts=(theme == "light")), hl=q.get("hl"))

    @staticmethod
    def _net_summary(t: str, r: dict, own: bool) -> dict:
        """Строка сравнения: те же пять чисел, что над глобусом, и состав."""
        n, fl = r.get("network"), r.get("fleet") or {}
        pairs = r.get("pairs") or []
        cut: dict[str, int] = {}
        for p in pairs:
            if p.get("status") != "ok":
                cut[p.get("status") or "?"] = cut.get(p.get("status") or "?", 0) + 1
        row = {"icao": t, "status": "ok" if n else "failed", "why": r.get("error") or "",
               "own_rates": own, "pairs_total": len(pairs), "cut": cut,
               "lease_eur_month": (n or fl).get("lease_eur_month"),
               "lease_prov": (n or fl).get("lease_prov"),
               "util_h_month": (n or fl).get("util_h_month"),
               "util_prov": (n or fl).get("util_prov"),
               "maint_fh": (n or fl).get("maint_fh"), "maint_fc": (n or fl).get("maint_fc"),
               "maint_prov": (n or fl).get("maint_prov")}
        if not n:
            return row
        np_ = n.get("pairs") or []
        row.update(
            pairs_in=len(np_),
            excluded=len(n.get("excluded") or []),
            freq_week=sum(x.get("freq_week", 0) for x in np_),
            seats_month=sum(x.get("seats_month", 0) for x in np_),
            pax_month=sum(x.get("pax_month", 0) for x in np_),
            revenue_month=sum(x.get("revenue_month", 0) for x in np_),
            # Сколько нынешнего потока нужно — единственное, что в сети
            # держит большой борт от «везёт больше, потому что больше»:
            # загрузка у всех одна, и без потока сравнение льстит размеру.
            need_max=max((x["need_share"] for x in np_ if x.get("need_share") is not None),
                         default=None),
            need_known=sum(1 for x in np_ if x.get("need_share") is not None),
            need_over=sum(1 for x in np_ if (x.get("need_share") or 0) > 1),
            hours_used=n.get("hours_used"), fleet=n.get("fleet"),
            breakeven_lf=n.get("breakeven_lf"), profit_at_ref=n.get("profit_at_ref"),
            fare_mult_breakeven=n.get("fare_mult_breakeven"),
            lease_breakeven=n.get("lease_breakeven"),
            fuel_price_breakeven=n.get("fuel_price_breakeven"),
            fuel_price_now=n.get("fuel_price_now"),
            seats_per_ac=next((l.get("seats") for p in pairs for l in (p.get("legs") or [])
                               if l.get("seats")), None),
            warnings=len(n.get("warnings") or []) + len(n.get("core_warnings") or []))
        return row

    def _start_net_job(self, form_key, airports, base, kw, ov, as_of) -> dict:
        """Поток формирования сети на отдельном соединении с базой."""
        from .econ import route_economics
        from .network import fleet_from_core, form_network
        from .store import Store
        job = {"done": False, "error": None, "progress": {"done": 0, "total": 0, "last": "",
                                                          "queue": 0}}
        self._net_jobs[form_key] = job
        cls = type(self)
        with cls._net_queue_lock:
            cls._net_queue.append(job)

        def progress(done, total, key):
            job["progress"].update(done=done, total=total, last=key)

        def queue_pos():
            with cls._net_queue_lock:
                waiting = [j for j in cls._net_queue if not j.get("started")]
                for i, j in enumerate(waiting):
                    j["progress"]["queue"] = i + 1

        # Плечи — общие для всех, у кого нет своих данных: витрина без
        # своих ставок и типов считает одно и то же, и после видео десять
        # человек, открывших одну сеть, должны ждать один расчёт, а не
        # десять. Переопределения в ключе плеча, поэтому чужие не смешаются.
        scope = self.ws
        if self.ws and self.gdb is not None:
            try:
                if not self.gdb.facts(self.ws):
                    scope = "shared"
            except Exception:                                  # noqa: BLE001
                pass
        elif not self.ws:
            scope = "shared"

        def run():
            queue_pos()
            cls._net_sem.acquire()
            job["started"] = True
            job["progress"]["queue"] = 0
            queue_pos()
            t0 = time.monotonic()
            try:
                base_store = Store(self.store.path if not isinstance(self.store, GuestStore)
                                   else self.store.base.path, shared=True)
                store = (GuestStore(base_store, self.gdb, self.ws)
                         if isinstance(self.store, GuestStore) else base_store)
                try:
                    pairs = form_network(store, airports, base=base, aircraft=kw["aircraft"],
                                         as_of=kw.get("as_of"), month=kw.get("month"),
                                         overrides=ov or None, operator=kw.get("operator", "*"),
                                         leg_cache=self._leg_cache.setdefault(scope, {}),
                                         detour_cache=self._detour_cache,
                                         progress=progress)
                    ok = [p for p in pairs if p.status == "ok"]
                    fleet = None
                    if ok:
                        fleet = fleet_from_core(route_economics, store, ok[0].a, ok[0].b,
                                                aircraft=kw["aircraft"], as_of=kw.get("as_of"),
                                                month=kw.get("month"), overrides=ov or None,
                                                operator=kw.get("operator", "*"))
                finally:
                    base_store.db.close()
                if len(self._net_cache) >= self.NET_CACHE:
                    self._net_cache.pop(next(iter(self._net_cache)))
                if sum(len(v) for v in self._leg_cache.values()) > 4000:
                    self._leg_cache.clear()
                self._net_cache[form_key] = (pairs, fleet, round((time.monotonic() - t0) * 1000))
            except Exception as exc:                           # noqa: BLE001
                job["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                job["done"] = True
                cls._net_sem.release()
                with cls._net_queue_lock:
                    if job in cls._net_queue:
                        cls._net_queue.remove(job)
                queue_pos()

        threading.Thread(target=run, daemon=True, name="net-form").start()
        return job

    # Условия начисления, которые определяет ТИП (решение 78). В сравнении
    # они сняты у всех: заданные пользователем для A320, они переехали бы
    # на E195 и дали бы ему шумовой сбор A320. Что снято — в ответе.
    TYPE_CTX = ("noise_cat", "ac_class", "stand_group")

    def compare(self, q: dict) -> dict:
        """Типы при ЗАДАННЫХ пассажирах, а не при одинаковой загрузке.

        Решение 91: одинаковая загрузка у всех типов молча предполагает,
        что большой борт находит больше пассажиров, то есть протаскивает
        модель спроса. Спрос здесь — вход: пассажиров на рейс. У каждого
        типа своя загрузка при них, а кому кресел не хватает — «нельзя».
        """
        kw = self._kwargs(q)
        kw.pop("seats", None)                    # кресла — из компоновки каждого типа
        # Снять условия типа из --set до разбора: они приходят строками
        # charge_context.<ап>.<ключ>=…
        sets = [x for x in q.get("set", "").split("~") if x]
        dropped = sorted({x.split("=")[0].split(".")[-1] for x in sets
                          if x.startswith("charge_context.")
                          and x.split("=")[0].split(".")[-1] in self.TYPE_CTX})
        keep = [x for x in sets if not (x.startswith("charge_context.")
                                        and x.split("=")[0].split(".")[-1] in self.TYPE_CTX)]
        if keep:
            from .overrides import parse_set
            kw["overrides"] = parse_set(keep)
        else:
            kw.pop("overrides", None)
        pax = float(q.get("pax") or 0)
        try:
            legs = self._legs(q, pax)
        except ValueError as exc:
            return {"error": str(exc)}
        want = [t for t in (q.get("types") or "").upper().split(",") if t]
        if not want:
            want = [t["icao"] for t in self.aircraft() if t["usable"]]
        rows = [self._compare_type(t, legs, kw) for t in want]
        # Порядок: выполнимые по себестоимости на пассажира, потом
        # невыполнимые, потом маленькие, потом сбои.
        rank = {"ok": 0, "infeasible": 1, "too_small": 2, "failed": 3}
        rows.sort(key=lambda r: (rank[r["status"]], r.get("cost_per_pax") or 0))
        return {"pax": pax if len(legs) == 1 else max(lg["pax"] for lg in legs),
                "rows": rows, "dropped_ctx": dropped,
                "legs": [{"origin": lg["o"], "destination": lg["d"], "pax": lg["pax"]} for lg in legs],
                "route": {"origin": legs[0]["o"], "destination": legs[0]["d"]},
                "note": ("условия типа сняты у всех типов: " + ", ".join(dropped)
                         if dropped else "")}

    MAX_LEGS = 8

    def _legs(self, q: dict, pax: float) -> list[dict]:
        """Участки для подбора типа (Ф1, решение 188).

        Без `legs` — один участок, текущий маршрут. С `legs` — строка
        `FRA-BCN:150~FRA-LIS:120`: тип подходит, только если выполним на
        каждом, — так выбирают борт под несколько линий сразу. Пассажиры
        участка не указаны — берутся общие `pax`.
        """
        raw = [x.strip() for x in (q.get("legs") or "").split("~") if x.strip()]
        if not raw:
            return [{"o": self.resolve(q.get("origin", "FRA")),
                     "d": self.resolve(q.get("destination", "BCN")), "pax": pax}]
        if len(raw) > self.MAX_LEGS:
            raise ValueError(f"участков {len(raw)}, предел {self.MAX_LEGS}: подбор типа под "
                             f"всю сеть — отчёт по парку (Ф5)")
        out = []
        for x in raw:
            route, _, n = x.partition(":")
            parts = [p for p in re.split(r"[\s\-–—>→]+", route) if p]
            if len(parts) != 2:
                raise ValueError(f"участок {x!r}: нужно «откуда-куда» или «откуда-куда:пассажиров»")
            try:
                lp = float(n) if n.strip() else pax
            except ValueError:
                raise ValueError(f"участок {x!r}: пассажиры не число") from None
            o, d = self.resolve(parts[0]), self.resolve(parts[1])
            # Аэропорт без записи — ошибка ввода, а не свойство типа: один
            # ответ сразу, а не тридцать семь одинаковых «сбоев».
            known = {a["key"] for a in self.airports()}
            for c in (o, d):
                if c not in known:
                    raise ValueError(f"аэропорта {c} нет в справочнике ({x})")
            out.append({"o": o, "d": d, "pax": lp})
        return out

    def _compare_type(self, t: str, legs: list[dict], kw: dict) -> dict:
        """Один тип на всех участках; сумма — по рейсам, по одному на участок."""
        from .econ import load_aircraft, route_economics
        row = {"icao": t, "status": "failed", "why": ""}
        try:
            with self.lock:
                ac = load_aircraft(self.store, t, kw.get("as_of"), kw.get("operator", "*"))
            row.update(name=ac.name, seats=ac.seats, seats_source=ac.seats_source)
            if any(lg["pax"] <= 0 for lg in legs):
                row.update(why="не задано число пассажиров")
                return row
            big = max(legs, key=lambda lg: lg["pax"])
            if big["pax"] > ac.seats:
                # Не «нельзя» модели, а нехватка кресел: отдельный статус,
                # чтобы не смешивать с перегрузом и баками.
                row.update(status="too_small",
                           why=f"{int(big['pax'])} пассажиров при {ac.seats} креслах"
                               + (f" ({big['o']}–{big['d']})" if len(legs) > 1 else ""))
                return row
            per, cost = [], 0.0
            for lg in legs:
                k = dict(kw, aircraft=t, load_factor=lg["pax"] / ac.seats)
                with self.lock:
                    res = route_economics(self.store, lg["o"], lg["d"], **k)
                tier = next((st for st in res.trace if st.label == "Ярус расхода"), None)
                c = sum(res.cost.values())
                cost += c
                per.append({"o": lg["o"], "d": lg["d"], "pax": lg["pax"], "res": res,
                            "cost": c, "tier": tier,
                            "km": (res.distance_nm or 0) * 1.852,
                            # Запас: сколько ещё пассажиров влезет — по креслам
                            # и по массе на этой дальности, что меньше.
                            "head": min(ac.seats, res.max_pax or 0) - lg["pax"]
                                    if res.max_pax is not None else None})
            bad = next((p for p in per if not p["res"].feasible), None)
            # Статьи по всем участкам (замечание 9): выбор типа делается не по
            # итогу, а по тому, из чего он сложен — топливо против владения.
            items: dict[str, float] = {}
            iprov: dict[str, str] = {}
            for p in per:
                for k, v in p["res"].cost.items():
                    items[k] = items.get(k, 0.0) + v
                    iprov[k] = p["res"].cost_prov.get(k, "?")
            row["items"] = [{"item": k, "label": _COST_RU.get(k, k), "eur": v, "prov": iprov[k]}
                            for k, v in sorted(items.items(), key=lambda kv: -kv[1])]
            pax_sum = sum(p["pax"] for p in per)
            seat_km = sum(ac.seats * p["km"] for p in per)
            fuel = sum(p["res"].fuel_kg for p in per)
            heads = [p for p in per if p["head"] is not None]
            tight = min(heads, key=lambda p: p["head"]) if heads else None
            first = per[0]
            why = ""
            if bad:
                why = "; ".join(l.get("text", "") for l in (bad["res"].feasibility or {}).get("limits", []))
                if len(legs) > 1:
                    why = f"{bad['o']}–{bad['d']}: {why}"
            row.update(
                status="infeasible" if bad else "ok", why=why,
                limits=[l.get("key") for l in ((bad or first)["res"].feasibility or {}).get("limits", [])]
                       if bad else [],
                lf=pax_sum / (ac.seats * len(per)), cost_total=cost, cost_per_pax=cost / pax_sum,
                # Распространение уже внутри себестоимости, поэтому средний
                # тариф в ноль по участкам — та же сумма на тех же пассажиров.
                breakeven_fare_eur=first["res"].breakeven_fare_eur if len(per) == 1
                                   else cost / pax_sum,
                cask=cost / seat_km * 100 if seat_km else None,
                fuel_kg=fuel, fuel_per_pax=fuel / pax_sum,
                block_h=sum(p["res"].block_h for p in per),
                max_pax=first["res"].max_pax if len(per) == 1 else (
                    tight["res"].max_pax if tight else None),
                headroom=tight["head"] if tight else None,
                headroom_leg=f"{tight['o']}–{tight['d']}" if tight and len(per) > 1 else "",
                tier=first["tier"].value if first["tier"] else None,
                tier_note=first["tier"].subst if first["tier"] else "",
                default_share=sum(p["res"].default_share() * p["cost"] for p in per) / cost if cost else 0,
                unused=sorted({w for p in per for w in p["res"].warnings if "не используется" in w}),
                legs=[{"leg": f"{p['o']}–{p['d']}", "cost": p["cost"], "pax": p["pax"],
                       "ok": p["res"].feasible, "head": p["head"]} for p in per] if len(per) > 1 else [])
        except KeyError as exc:
            row.update(status="failed", why=str(exc).strip("'"))
        except Exception as exc:                          # noqa: BLE001
            row.update(status="failed", why=f"{type(exc).__name__}: {exc}")
        return row

    USER_SRC = "aircraft_user"

    def _user_dir(self) -> Path:
        reg = (self.registry.get("sources", {}) if isinstance(self.registry, dict)
               else getattr(self.registry, "sources", {}))
        return Path((reg.get(self.USER_SRC) or {}).get("path") or "data/aircraft/user")

    def aircraft_save(self, doc: dict) -> dict:
        """Форма -> тот же разбор, что у файла -> файл каталога -> факты.

        Здесь нет отдельной приёмки: автор формы и есть тот человек,
        который принимал бы предложение (решение 4 говорит «человек
        принимает», и он принимает — нажатием). Проверки те же, что у
        файла: словарь полей, обязательные поля, издатель, якорь с
        источником, цена ошибки у неточности.
        """
        from .parsers.aircraft_user import _one
        if self.public and not self.ws:
            return {"error": "публичная витрина: чтобы сохранить свой тип, создайте "
                             "рабочее место — оно ваше по секретной ссылке",
                    "need_workspace": True}
        today = date.today().isoformat()
        doc = dict(doc)
        doc.setdefault("valid_from", today)
        doc["checked_at"] = today
        for k in ("fields", "burn", "fleet"):
            if isinstance(doc.get(k), dict):
                doc[k] = {a: b for a, b in doc[k].items() if b not in ("", None)}
        if not doc.get("burn", {}).get("analog"):
            doc.pop("burn", None)
        if not doc.get("fleet"):
            doc.pop("fleet", None)
            doc.pop("fleet_source", None)
        ctx = {"source_id": self.USER_SRC, "sha": None,
               "extracted_by": "form:aircraft_user@1", "node": "src_aircraft_user"}
        facts = _one(doc, ctx)                      # отказ — ValueError словами
        key = facts[0].key.split("/")[0]
        if self.ws:
            # Гость: тот же разбор, но в свой слой; файла нет, каталог —
            # экспорт места. Чужой код (A320) переопределить нельзя — только
            # USER:… — иначе своё значение молча подменило бы справочник.
            if not key.startswith("USER:"):
                return {"error": f"{key} — код справочника; свой тип заводится под "
                                 f"ключом USER:…"}
            by_domain: dict[str, list] = {}
            for f in facts:
                by_domain.setdefault(f.domain, []).append(f)
            st = {}
            for dom, fs in by_domain.items():
                st[dom] = self.gdb.replace_facts(self.ws, dom, key, fs, today)
            doc["icao"] = key
            self.gdb.put_doc(self.ws, "aircraft", key, doc)
            return {"ok": True, "icao": key, "workspace": True, "stats": st}
        with self.lock:
            other = self.store.db.execute(
                """SELECT DISTINCT source_id FROM facts WHERE domain='aircraft'
                   AND valid_to IS NULL AND key LIKE ? AND source_id != ?""",
                (key + "/%", self.USER_SRC)).fetchall()
        if other:
            return {"error": f"{key} заведён источником {other[0][0]} и здесь не "
                             f"редактируется — создайте свой тип на его основе под "
                             f"ключом USER:…"}
        # Файл — прежде фактов: если запись в базу упадёт, каталог уже
        # верен, и `fca refresh --only aircraft_user` восстановит базу.
        d = self._user_dir(); d.mkdir(parents=True, exist_ok=True)
        path = d / (key.replace(":", "_") + ".json")
        doc["icao"] = key
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        with self.lock:
            st = self.store.commit_facts(facts)
            gone = self.store.retire_missing("aircraft", self.USER_SRC, prefixes=[key],
                                             keep=[f.key for f in facts], as_of=today)
            self.store.mark_source(self.USER_SRC, status="ok",
                                   message=f"{key} сохранён с формы: {st}")
        return {"ok": True, "icao": key, "file": str(path), "stats": st, "retired": gone}

    def aircraft_delete(self, body: dict) -> dict:
        """Снятие своего типа с учёта: факты закрываются сегодняшним днём,
        файл каталога убирается. История остаётся (append-only)."""
        key = (body.get("icao") or "").upper()
        if self.ws:
            if not key.startswith("USER:"):
                return {"error": "удалить можно только свой тип USER:…"}
            n = sum(self.gdb.retire_facts(self.ws, d, key) for d in ("aircraft", "aircraft_layout"))
            self.gdb.delete_doc(self.ws, "aircraft", key)
            if not n:
                return {"error": f"у {key} нет действующих фактов в вашем месте"}
            return {"ok": True, "icao": key, "retired": n, "workspace": True}
        if self.public:
            return {"error": "публичная витрина: удаление закрыто без рабочего места"}
        if not key.startswith("USER:"):
            # Обозначатель ИКАО могут делить два источника; удалять
            # разрешено только то, что заведено с формы или из каталога.
            with self.lock:
                other = self.store.db.execute(
                    """SELECT 1 FROM facts WHERE domain='aircraft' AND valid_to IS NULL
                       AND key LIKE ? AND source_id != ?""",
                    (key + "/%", self.USER_SRC)).fetchone()
            if other:
                return {"error": f"{key} заведён не из каталога своих типов"}
        today = date.today().isoformat()
        with self.lock:
            gone = self.store.retire_missing("aircraft", self.USER_SRC, prefixes=[key],
                                             keep=[], as_of=today)
        path = self._user_dir() / (key.replace(":", "_") + ".json")
        if path.exists():
            path.unlink()
        if not gone:
            return {"error": f"у {key} нет действующих фактов из каталога — снимать нечего"}
        return {"ok": True, "icao": key, "retired": gone}

    def aircraft_type(self, q: dict) -> dict:
        """Все факты одного типа с происхождением — страница типа.

        Что показывается: поле, значение, единица, источник, достоверность,
        примечание, дата. Тип не редактируется здесь — редактируется его
        копия в каталоге (см. `aircraft_draft`).
        """
        icao = (q.get("icao") or "").upper()
        with self.lock:
            rows = self.store.db.execute(
                """SELECT key, value, value_text, unit, source_id, confidence,
                          certainty, valid_from, note, source_note, confirm_by
                   FROM facts WHERE domain = 'aircraft' AND valid_to IS NULL
                   AND key LIKE ? ORDER BY key""", (icao + "/%",)).fetchall()
            layouts = self.store.db.execute(
                """SELECT key, value, source_id, confidence FROM facts
                   WHERE domain = 'aircraft_layout' AND valid_to IS NULL
                   AND key LIKE ?""", ("%/" + icao,)).fetchall()
            fleet = self.store.db.execute(
                """SELECT key, value, unit, source_id, confidence FROM facts
                   WHERE domain = 'fleet_economics' AND valid_to IS NULL
                   AND key LIKE ?""", ("%/" + icao + "/%",)).fetchall()
        own = False
        if self.ws and icao.startswith("USER:"):
            g = [r for r in self.gdb.facts(self.ws, "aircraft") if r["key"].startswith(icao + "/")]
            if g:
                own = True
                rows = [(r["key"], r["value"], r["value_text"], r["unit"], r["source_id"],
                         r["confidence"], r["certainty"], r["valid_from"], r["note"],
                         r["source_note"], r["confirm_by"]) for r in g]
                layouts = [(r["key"], r["value"], r["source_id"], r["confidence"])
                           for r in self.gdb.facts(self.ws, "aircraft_layout")
                           if r["key"].endswith("/" + icao)]
        if not rows:
            return {"icao": icao, "error": f"типа {icao} в домене aircraft нет"}
        fields = [{"field": k.split("/", 1)[1], "value": v, "text": t, "unit": u,
                   "source": src, "prov": conf, "certainty": cert, "from": vf,
                   "note": note, "source_note": sn, "confirm_by": cb}
                  for k, v, t, u, src, conf, cert, vf, note, sn, cb in rows]
        try:
            from openap import prop
            physics = icao.lower() in {a.lower() for a in prop.available_aircraft()}
        except Exception:                                  # noqa: BLE001
            physics = None
        try:
            from openap import prop
            analogs = sorted(a.upper() for a in prop.available_aircraft())
        except Exception:                                  # noqa: BLE001
            analogs = []
        # Что работает, если поле ставки пусто: заготовка от массы и кресел
        # (решение 190) — числом в поле, а не словами «из справочника».
        fleet_default = {}
        try:
            from .fleet import parametric
            num = {f["field"]: f["value"] for f in fields if isinstance(f["value"], (int, float))}
            if num.get("mtow_t"):
                pe = parametric(icao, num["mtow_t"], num.get("seats_typical") or num.get("seats_max") or 150)
                fleet_default = {k: getattr(pe, k) for k in (
                    "lease_eur_month", "monthly_hours", "maint_eur_per_fh", "maint_eur_per_fc",
                    "crew_eur_per_fh", "crew_eur_per_fc")}
        except Exception:                                  # noqa: BLE001
            fleet_default = {}
        return {"icao": icao, "fleet_default": fleet_default,
                "name": next((f["note"] for f in fields if f["field"] == "mtow_t"), ""),
                "fields": fields, "physics": physics, "analogs": analogs,
                "editable": (own or not self.public) and all(f["source"] == self.USER_SRC for f in fields),
                "public": self.public, "workspace": own, "has_workspace": bool(self.ws),
                "user": any(f["source"] == "aircraft_user" for f in fields),
                "layouts": [{"operator": k.split("/")[0], "seats": v, "source": s_, "prov": c}
                            for k, v, s_, c in layouts],
                "fleet": [{"operator": k.split("/")[0], "field": k.split("/")[-1],
                           "value": v, "unit": u, "source": s_, "prov": c}
                          for k, v, u, s_, c in fleet]}

    def aircraft_draft(self, q: dict) -> dict:
        """Копия типа как заготовка файла `data/aircraft/user/<код>.json`.

        Паспортные поля переносятся из хранилища; расход — как вариант с
        тем же двигателем (`same_engine`), если у исходного типа есть
        физика, иначе аналог исходного типа с его же якорем. Поля
        источника заполняются подсказками, а не выдумкой: «источник»
        у копии — тот, кто её меняет, и это надо написать.
        """
        from .parsers.aircraft_user import FIELDS
        src = (q.get("icao") or "").upper()
        as_key = (q.get("as") or f"USER:{src}-MY").upper()
        t = self.aircraft_type({"icao": src})
        if t.get("error"):
            return t
        by = {f["field"]: f for f in t["fields"]}
        fields = {k: by[k]["value"] for k in FIELDS if k in by and by[k]["value"] is not None}
        analog = by["burn_analog"]["text"] if "burn_analog" in by else src
        burn = {"analog": analog}
        if t["physics"] or by.get("burn_same_engine"):
            burn["same_engine"] = True
            burn["note"] = (f"вариант {src} с тем же двигателем: вычислитель {analog}, "
                            f"множитель 1. Если двигатель другой — снять same_engine и "
                            f"назвать якорь с источником")
        else:
            for k_src, k_dst in (("burn_anchor_kg_per_h", "anchor_kg_per_h"),
                                 ("burn_anchor_mass_t", "anchor_mass_t")):
                if k_src in by and by[k_src]["value"] is not None:
                    burn[k_dst] = by[k_src]["value"]
            burn["anchor_source"] = by["burn_anchor_note"]["text"] if "burn_anchor_note" in by else ""
            burn["note"] = f"скопировано из {src}; якорь и аналог унаследованы — проверить"
        return {
            "icao": as_key,
            "name": f"{t['name'] or src} (свой вариант)",
            "valid_from": date.today().isoformat(),
            "source": f"копия {src} из хранилища ({', '.join(sorted({f['source'] for f in t['fields']}))}) "
                      f"с изменениями — ОПИСАТЬ, что и почему изменено",
            "source_url": "адрес публикации изменённых величин, или «собственное допущение»",
            "publisher": "кто отвечает за изменённые числа",
            "checked_at": date.today().isoformat(),
            # exact, а не reading_unconfirmed: достоверность описывает
            # прочтение документа, а у своих чисел документа нет — есть
            # утверждение автора, и оно точно такое, какое он записал.
            # Неточность требует цены ошибки числом и адресата (75, 76).
            "certainty": "exact",
            "fields": fields,
            "engine": by["engine"]["text"] if "engine" in by else "",
            **({"engine_mount": by["engine_mount"]["text"]} if "engine_mount" in by else {}),
            **({"fleet": fl, "fleet_source": next((by[k]["note"] for k in by if k.startswith("fleet_")), "")
                .removeprefix("ставка автора типа: ")} if (fl := {k[6:]: by[k]["value"] for k in by
                                                                if k.startswith("fleet_")}) else {}),
            "burn": burn,
        }

    def seo_types(self) -> list[dict]:
        """Типы для страниц поисковика: справочник без слоя гостя, кэш на 10 минут.

        Страницы типов и sitemap спрашивают список на каждый запрос, а
        поисковый робот ходит пачками; список меняется только выкладкой.
        """
        now = time.time()
        c = getattr(self, "_seo_cache", None)
        if c and now - c[0] < 600:
            return c[1]
        types = self.aircraft()         # общий контекст: слоя гостя нет
        self._seo_cache = (now, types)
        return types

    def aircraft(self) -> list[dict]:
        """Типы ВС из хранилища, с тем, что о каждом известно.

        Четыре типа были зашиты в `<option>` при тридцати семи в домене —
        тот же класс дефекта, что 170 кресел в коде (решение 44). Список
        читается из домена `aircraft`; для каждого типа названо, есть ли
        компоновки и есть ли физика `openap`. Тип без физики считается
        ярусом 3/4 (решение 94), и сейчас он падает в параметрику молча
        (M8) — пометка в списке это единственное, что об этом говорит.
        """
        with self.lock:
            rows = self.store.db.execute(
                """SELECT key, value, value_text, source_id, note FROM facts
                   WHERE domain = 'aircraft' AND valid_to IS NULL""").fetchall()
            lay = self.store.db.execute(
                """SELECT key, value, source_id, confidence FROM facts
                   WHERE domain = 'aircraft_layout' AND valid_to IS NULL""").fetchall()
        if self.ws:
            # Свои типы гостя — поверх справочника, как при чтении.
            rows = list(rows) + [(r["key"], r["value"], r["value_text"], r["source_id"],
                                  r["note"] if "note" in r.keys() else None)
                                 for r in self.gdb.facts(self.ws, "aircraft")]
            lay = list(lay) + [(r["key"], r["value"], r["source_id"], r["confidence"])
                               for r in self.gdb.facts(self.ws, "aircraft_layout")]
        types: dict[str, dict] = {}
        for key, value, txt, src, note in rows:
            icao, _, field = (key or "").partition("/")
            if not icao or not field:
                continue
            t = types.setdefault(icao, {"icao": icao, "fields": {}, "sources": set()})
            t["fields"][field] = value if value is not None else txt
            # Имя своего типа и типа каталога парсер кладёт в note массы
            # (как openap): без него в списке стоял один код.
            if field == "mtow_t" and note and "name" not in t["fields"]:
                t["fields"]["name"] = str(note)
            t["sources"].add(src)
        layouts: dict[str, list[dict]] = {}
        for key, seats, src, conf in lay:
            op, _, icao = (key or "").partition("/")
            if icao and seats:
                layouts.setdefault(icao, []).append(
                    {"operator": op, "seats": int(seats), "source": src, "prov": conf})
        # Физика: библиотека спрашивается сама, а не выводится из
        # источника факта. Тип, заведённый руками, может стоять в домене с
        # тем же полем `mtow_t`, и по факту его не отличить.
        try:
            from openap import prop
            phys = {a.upper() for a in prop.available_aircraft()}
            phys_checked = True
        except Exception:                          # noqa: BLE001
            prop, phys, phys_checked = None, set(), False

        def lib_name(icao: str) -> str:
            # Полное имя — «Airbus A320», «Boeing 737-800» — из той же
            # библиотеки, что физика: это её справочная строка, у неё есть
            # издатель и редакция (решение 108). Домен `aircraft` имени
            # не держит, а искать человек будет по нему.
            if prop is None or icao not in phys:
                return ""
            try:
                return str(prop.aircraft(icao.lower()).get("aircraft") or "")
            except Exception:                      # noqa: BLE001
                return ""

        def geom(f: dict) -> dict | None:
            num = lambda k: f.get(k) if isinstance(f.get(k), (int, float)) else None
            if not num("span_m") or not num("length_m"):
                return None
            return {"span": num("span_m"), "length": num("length_m"),
                    "width": num("fuselage_width_m"), "sweep": num("sweep_deg"),
                    "engines": int(num("engine_count") or 2),
                    "mount": f.get("engine_mount") if isinstance(f.get("engine_mount"), str) else None,
                    "mach": num("cruise_mach"), "mtow": num("mtow_t")}

        out = []
        for icao, t in sorted(types.items()):
            f = t["fields"]
            name = (f.get("name") if isinstance(f.get("name"), str) else "") \
                or lib_name(icao)
            ls = sorted(layouts.get(icao, []), key=lambda x: (x["operator"] != "*", x["operator"]))
            out.append({
                "icao": icao,
                "name": name,
                "mtow_t": f.get("mtow_t"),
                "seats_typical": f.get("seats_typical"),
                "seats_max": f.get("seats_max"),
                # Без взлётной массы `load_aircraft` отказывает; такой тип
                # в списке остаётся, но выбрать его нельзя — с причиной.
                # Карточка каталога без полей расчёта (решение 223) видна
                # в списке, но не выбирается — с перечнем того, чего нет.
                "usable": f.get("mtow_t") is not None and not f.get("calc_gaps"),
                "why_not": ("в домене aircraft нет mtow_t" if f.get("mtow_t") is None
                            else f"только карточка: не опубликованы {f['calc_gaps']}"
                            if f.get("calc_gaps") else ""),
                "status": f.get("program_status") if isinstance(f.get("program_status"), str) else None,
                "data_kind": f.get("data_kind") if isinstance(f.get("data_kind"), str) else None,
                "layouts": ls,
                "layout_default": next((x for x in ls if x["operator"] == "*"), None),
                # None — «не проверялось» (библиотеки нет), а не «нет
                # физики»: два разных состояния (решение 67).
                "physics": (icao in phys) if phys_checked else None,
                "tier": 1 if (phys_checked and icao in phys) else (None if not phys_checked else 3),
                "sources": sorted(t["sources"]),
                # Строка поиска: код, имя и имя без разделителей, чтобы
                # «737800» находило «737-800». Совпадение по словам — в
                # браузере: «airbus 320» это два слова, оба должны найтись.
                "find": " ".join([icao, name, re.sub(r"[\s\-]", "", name)]).lower(),
                # Силуэт рисует браузер из этих чисел (решение 188):
                # картинок на сервере нет, лицензий на них не нужно, и
                # свой тип получает рисунок сразу, как только у него
                # есть размах и длина.
                "geom": geom(f),
            })
        return out

    def fact(self, q: dict) -> dict:
        """Один факт со всей его историей — то, во что упирается «прокликать».

        Шаг расчёта называет источник строкой; чтобы дойти до справочника,
        нужен адрес. Здесь он и раскрывается: значение, происхождение,
        достоверность, цена ошибки, адресат подтверждения и все прежние
        редакции с интервалами.
        """
        dom, key = q.get("domain", ""), q.get("key", "")
        # Адрес статьи сбора указывает на КОД, а не на факт: у Франкфурта
        # пассажирский сбор — четыре строки по направлениям, и одна из
        # них не есть статья. Поэтому ключ, под которым записи нет,
        # раскрывается в перечень правил с этим префиксом.
        with self.lock:
            exact = self.store.db.execute(
                "SELECT 1 FROM facts WHERE domain = ? AND key = ? LIMIT 1",
                (dom, key)).fetchone()
        if not exact:
            return self._by_prefix(dom, key)
        with self.lock:
            rows = self.store.db.execute(
                """SELECT value, value_text, unit, currency, valid_from,
                          valid_to, source_id, extracted_by, confidence,
                          certainty, error_cost, confirm_by, source_note, note
                   FROM facts WHERE domain = ? AND key = ?
                   ORDER BY valid_from DESC, id DESC""", (dom, key)).fetchall()
        if not rows:
            return {"domain": dom, "key": key, "found": False,
                    "why": "в хранилище такого ключа нет"}
        cols = ["value", "value_text", "unit", "currency", "valid_from",
                "valid_to", "source_id", "extracted_by", "confidence",
                "certainty", "error_cost", "confirm_by", "source_note", "note"]
        hist = [dict(zip(cols, r)) for r in rows]
        src = self.registry.get("sources", {}).get(hist[0]["source_id"], {})
        # Решение 219: запись закрытого источника на публичной витрине —
        # только действующее значение, которое и так стоит в расчёте;
        # истории и выписок из первоисточника нет.
        from .browse import is_public
        restricted = self.public and not is_public(self.registry, hist[0]["source_id"])
        if restricted:
            hist = [{k: v for k, v in hist[0].items() if k not in ("source_note", "note")}]
        return {"domain": dom, "key": key, "found": True, "restricted": restricted,
                "current": hist[0], "history": hist[1:],
                "source": {"id": hist[0]["source_id"],
                           "title": src.get("title"), "url": src.get("url"),
                           "license": src.get("license"),
                           "cadence_days": src.get("cadence_days"),
                           "sla_days": src.get("sla_days")}}

    def _by_prefix(self, dom: str, prefix: str) -> dict:
        """Правила под общим префиксом — раскрытие адреса статьи."""
        with self.lock:
            rows = self.store.db.execute(
                """SELECT key, value, value_text, unit, currency, valid_from,
                          valid_to, source_id, confidence, certainty,
                          error_cost, confirm_by, source_note, note
                   FROM facts WHERE domain = ? AND key LIKE ?
                     AND valid_to IS NULL ORDER BY key""",
                (dom, prefix + "/%")).fetchall()
        if not rows:
            return {"domain": dom, "key": prefix, "found": False,
                    "why": "ни точного ключа, ни правил с таким префиксом"}
        cols = ["key", "value", "value_text", "unit", "currency", "valid_from",
                "valid_to", "source_id", "confidence", "certainty",
                "error_cost", "confirm_by", "source_note", "note"]
        items = [dict(zip(cols, r)) for r in rows]
        # Документ, из которого взята статья: парсер тарифов кладёт в note
        # «пункт | документ | адрес». Реестр знает только источник-папку
        # («~40 аэропортов вручную»), а пользователю нужен сам тариф.
        doc = {}
        for it in items:
            parts = [x.strip() for x in (it.get("note") or "").split(" | ")]
            it["clause"] = parts[0] if parts else ""
            if len(parts) >= 2 and parts[-1].startswith("http"):
                doc = {"url": parts[-1],
                       "title": parts[-2] if len(parts) >= 3 else ""}
        src = self.registry.get("sources", {}).get(items[0]["source_id"], {})
        return {"domain": dom, "key": prefix, "found": True, "kind": "prefix",
                "rules": items, "count": len(items), "document": doc,
                "source": {"id": items[0]["source_id"], "title": src.get("title"),
                           "url": src.get("url"), "license": src.get("license"),
                           "cadence_days": src.get("cadence_days"),
                           "sla_days": src.get("sla_days")}}

    def geo(self) -> dict:
        """Геометрия для глобуса: зоны, контуры суши, точки аэропортов.

        Питон отдаёт ШИРОТУ И ДОЛГОТУ, проецирует браузер (решение 97).
        Вторая реализация проекции на сервере разошлась бы с первой так
        же молча, как разошлись два отпечатка состава.

        Полигоны лежат рецептом под `data/geo/` и в репозиторий не идут
        (решение 1). Если их нет — это состояние, а не поломка: глобус
        покажет точки без подложки и скажет, чего не хватает.
        """
        out: dict = {"zones": {}, "land": [], "airports": {}, "missing": []}
        for name, key in (("zones.json", "zones"), ("land.json", "land")):
            f = GEO / name
            if f.exists():
                try:
                    out[key] = json.loads(f.read_text(encoding="utf-8"))
                except ValueError as exc:
                    out["missing"].append(f"{name}: не разбирается ({exc})")
            else:
                out["missing"].append(
                    f"{name} нет в data/geo — источник геометрии не заведён")
        for a in self.airports():
            out["airports"][a["icao"]] = {
                "lat": a.get("lat"), "lon": a.get("lon"),
                "name": (a.get("tr") or {}).get("ru") or a["name"],
                "iata": a["key"], "tier": a["tier"], "seen": a["seen"],
                "flights": a.get("flights", 0), "watch": a.get("watch", False)}
        return out

    def bench(self, q: dict) -> dict:
        """Полосы, с которыми сравнивается ответ.

        Три величины и три разных вопроса (решение 123):
          CASK и стоимость блок-часа — правдоподобна ли наша модель;
          доход с пассажира — сходится ли экономика линии;
          видимая цена — можно ли войти на линию ценой.

        Пусто — законный ответ, и он показывается наравне с полосой:
        отсутствие бенчмарка есть состояние, а не пробел (решение 85).
        """
        # Маршрут приводится к ИКАО: домен `market_fare` ключуется им
        # (решение 103), а витрина присылает ключ хранилища, то есть ИАТА.
        # Совпадать они перестали ровно тогда, когда перевод появился, и
        # это лучше, чем совпадать случайно.
        with self.lock:
            to_icao = self.store.icao_of_iata()
        def _icao(code: str) -> str:
            c = (code or "").strip().upper()
            return to_icao.get(c, c)
        # Без указателя перевод молча не делается, и поиск по ключу в
        # ИКАО не находит ничего — выглядит как «наблюдений нет». Разница
        # между «нет данных» и «не смогли посмотреть» обязана быть видна
        # (решение 67).
        route = f"{_icao(q.get('origin',''))}-{_icao(q.get('destination',''))}"
        out = {"route": route, "cask": None, "yield": None, "fare": None}
        if not to_icao:
            # Сообщение писалось в `out` до того, как `out` создавался:
            # именно в том случае, для которого оно написано, ответ падал
            # с UnboundLocalError. Проверка, чей единственный путь никогда
            # не выполнялся (решение 16).
            out["no_index"] = ("указателя кодов нет: цена ключуется в ИКАО, "
                               "а перевести код маршрута нечем — "
                               "fca refresh --only airport_codes --all")
        with self.lock:
            rows = self.store.db.execute(
                """SELECT key, value, unit, value_text, source_id, currency
                   FROM facts
                   WHERE domain = 'carrier_benchmark' AND valid_to IS NULL""").fetchall()
            fares = self.store.db.execute(
                """SELECT key, value, unit, value_text FROM facts
                   WHERE domain = 'market_fare' AND valid_to IS NULL
                     AND key LIKE ?""", (route + "/%",)).fetchall()
            # Цена направленная: туда и обратно различаются (сборы страны
            # вылета, точка продажи, спрос). Но список сбора часто односторонний,
            # и пустота на FRA–BCN при собранном BCN–FRA — хуже, чем обратная
            # цена с пометкой. Пометка обязательна: без неё число выглядит
            # ценой этого направления.
            if not fares:
                back = "-".join(reversed(route.split("-")))
                fares = self.store.db.execute(
                    """SELECT key, value, unit, value_text FROM facts
                       WHERE domain = 'market_fare' AND valid_to IS NULL
                         AND key LIKE ?""", (back + "/%",)).fetchall()
                if fares:
                    out["fare_reverse"] = back
        # Величины перевозчика собираются по контурам, и ВЫВОДИМЫЕ
        # считаются здесь — там же, где видно слагаемые. Хранить CASK
        # фактом значило бы хранить чей-то выбор границы учёта: считать от
        # операционных расходов или от расходов без топлива, от выручки
        # сегмента или от трафиковой. У Lufthansa разница между последними
        # двумя — 6,4%.
        by_carrier: dict[str, dict] = {}
        for key, value, unit, txt, src, currency in rows:
            car, _, rest = key.partition("/")
            year, _, metric = rest.partition("/")
            try:
                meta = json.loads(txt or "{}")
            except ValueError:
                meta = {}
            slot = by_carrier.setdefault(f"{car}/{year}", {"vals": {}, "meta": {}})
            slot["vals"][metric] = value
            # Валюта — КОЛОНКА факта, а не поле в тексте. Искал её в
            # `value_text` и не находил: пересчёт молча не делался, и
            # рублёвый CASK 4,47 встал в полосу рядом с евровым 9,40,
            # дав «9,4 – 446,9». Ошибка была видна только потому, что
            # рубль отличается от евро на два порядка; при валюте
            # поближе — скажем, франке — прошла бы незамеченной.
            slot["meta"][metric] = dict(meta, currency=currency or "")

        from . import bench as _bench
        with self.lock:
            rep_by = {(r["carrier"], r["year"]): r for r in _bench.reports(self.store)}
        derived = []
        for who, d in sorted(by_carrier.items()):
            v = d["vals"]
            meta0 = (list(d["meta"].values()) or [{}])[0]
            car, _, year = who.partition("/")
            item = {"carrier": who, "code": car, "year": year,
                    # Название — из выписки (там оно из отчёта, решение 108);
                    # у старых фактов его нет, и тогда показывается код,
                    # а не выдуманная расшифровка.
                    "name": meta0.get("name") or car,
                    "scope": meta0.get("scope", "")}
            ask, opex = v.get("ask_km"), v.get("opex_eur")
            # Валюта хранится как опубликована (решение 22), пересчёт
            # здесь. Без него рублёвый CASK 4,47 встал бы в один ряд с
            # евровыми 9,40 и выглядел бы вдвое лучше, будучи втрое хуже.
            # Валюта денег контура: расходов, а если их нет — выручки. Брал
            # только расходы, и у Norwegian (выручка в кронах, расходов в
            # выписке нет) доход с пассажира вышел 1 379 «евро».
            cur = next((m.get("currency") for k in ("opex_eur", "revenue_eur",
                                                     "traffic_revenue_eur")
                        if (m := d["meta"].get(k) or {}).get("currency")), "")
            rate = 1.0
            if cur and cur != "EUR":
                # Курс ИЗ ОТЧЁТА имеет приоритет (решение 22): отчёт
                # пересчитывает свои же показатели им, и другой курс дал
                # бы величину, которой в документе нет. Только если его
                # не заведено — общий слой разрешения.
                own = v.get("fx_per_eur")
                if own:
                    rate = own
                    item["fx"] = {"currency": cur, "rate": rate,
                                  "provenance": "курс из того же отчёта, "
                                  + (d["meta"].get("fx_per_eur") or {}).get("basis", "")}
                else:
                    from . import fx as _fx
                    rate, prov = _fx.resolve(self.store, cur, None)
                    item["fx"] = {"currency": cur, "rate": rate,
                                  "provenance": prov}
            if ask and opex and rate:
                item["cask_cents"] = round(opex / rate / ask * 100, 2)
                item["cask_currency"] = cur or "EUR"
            if opex and v.get("block_hours") and rate:
                # Стоимость блок-часа — единственная полоса, которой можно
                # поверить нашу параметрику напрямую: на блок-времени
                # висят владение, ТОиР и экипаж, то есть 39% ответа.
                item["cost_per_block_h"] = round(opex / rate / v["block_hours"])
            if v.get("block_hours") and v.get("flights"):
                item["block_h_per_flight"] = round(
                    v["block_hours"] / v["flights"], 2)
            if ask and v.get("revenue_eur") and rate:
                item["rask_cents"] = round(v["revenue_eur"] / rate / ask * 100, 2)
            # Доход с пассажира — от ТРАФИКОВОЙ выручки, если она названа:
            # прочие доходы к перевозке пассажира отношения не имеют.
            rev = v.get("traffic_revenue_eur") or v.get("revenue_eur")
            if rev and v.get("pax") and rate:
                item["yield_eur_pax"] = round(rev / rate / v["pax"], 1)
                item["yield_basis"] = ("трафиковая выручка"
                                       if v.get("traffic_revenue_eur")
                                       else "вся выручка контура")
            # Среднее плечо. Без него полоса несравнима: на коротком
            # секторе постоянные статьи делятся на меньшее число
            # кресло-километров, и CASK выше при той же эффективности.
            if v.get("rpk_km") and v.get("pax"):
                item["sector_nm"] = round(v["rpk_km"] / v["pax"] / 1.852)
            if ask and v.get("flights") and v.get("pax") and v.get("load_factor"):
                seats = v["pax"] / v["flights"] / v["load_factor"]
                item["seats_per_flight"] = round(seats)
                # Вторая дорога к тому же числу — сверка, а не украшение.
                item["sector_nm_check"] = round(ask / v["flights"] / seats / 1.852)
            # ЗАТРАТЫ НА РЕЙС НЕ СЧИТАЕМ. Арифметика верна — 17 643 млн
            # на 476 842 рейса даёт 37 000 EUR и сходится с CASK до двух
            # евро, — но величина почти бессмысленна: в контур Lufthansa
            # Airlines входят и региональные партнёры, и Discover, то есть
            # часовой рейс CRJ на 90 кресел усредняется с десятичасовым
            # A350 на 300. «Средний рейс 2 382 км на 165 креслах» — рейс,
            # которого не существует.
            #
            # CASK и стоимость блок-часа усреднением не портятся: они
            # нормированы на кресло-километр и на час. Затраты на рейс —
            # нет, и ставить их в ту же колонку значит подсунуть под одной
            # подписью две разные величины.
            if opex and v.get("pax") and rate:
                # Зато затраты НА ПАССАЖИРА сравнимы: это та же сторона,
                # что доход с пассажира, и с ней осмысленно сопоставлять.
                item["cost_per_pax"] = round(opex / rate / v["pax"], 1)
            # Ставки на блок-час из отчётности (решение 183): у большинства
            # новых выписок нет ни выручки, ни операционных расходов, зато
            # есть блок-часы и строки персонала и ТОиР. Считает их
            # `bench.reports` — тот же расчёт, что в `fca bench`.
            rep = rep_by.get((car, int(year) if year.isdigit() else year))
            if rep:
                for f in ("crew_per_bh", "crew_basis", "staff_per_bh", "maint_per_bh",
                          "maint_own_per_bh", "bh_estimated", "unconfirmed"):
                    if rep.get(f) not in (None, [], ""):
                        item[f] = rep[f]
            # Заполненность — сколько сравнимых величин у контура. По ней
            # сортируется список: пустые карточки вверху выглядели так,
            # будто отчётность есть, а сравнить не с чем.
            item["filled"] = sum(1 for f in ("cask_cents", "yield_eur_pax", "sector_nm",
                                             "cost_per_block_h", "cost_per_pax", "crew_per_bh",
                                             "staff_per_bh", "maint_own_per_bh")
                                 if item.get(f) is not None)
            if item["filled"]:
                derived.append(item)
        derived.sort(key=lambda x: (-x["filled"], x["name"]))
        out["carriers"] = derived
        for name, field in (("cask", "cask_cents"), ("yield", "yield_eur_pax")):
            vals = sorted(x[field] for x in derived if field in x)
            if vals:
                out[name] = {"lo": vals[0], "hi": vals[-1], "n": len(vals)}
        out["have"] = sorted({m for d in by_carrier.values() for m in d["vals"]})

        if fares:
            out["fare"] = [{"key": k, "value": v, "unit": u,
                            "meta": json.loads(t or "{}")} for k, v, u, t in fares]
            # Одна цена на линию — по тому же правилу, что в сети (решение 209):
            # прямые, полосы глубины в порядке FARE_BANDS (сначала «за 15–30
            # дней»). Остальные полосы — разложение по глубине и пересадкам,
            # не разброс одной цены; витрина показывает их по нажатию.
            from .network import FARE_BANDS
            rank = {b: i for i, b in enumerate(FARE_BANDS)}

            def _order(i):
                parts = out["fare"][i]["key"].split("/")
                band = parts[1] if len(parts) > 1 else ""
                direct = (parts[2] if len(parts) > 2 else "direct") == "direct"
                return (0 if direct else 1, rank.get(band, len(rank)))
            idx = sorted(range(len(out["fare"])), key=_order)
            out["fare_order"] = idx
            out["fare_main"] = idx[0]
            # Число без валюты рядом с евровыми — приглашение сравнить
            # несравнимое. Пересчёт даётся, ТОЛЬКО если курс есть: без
            # него подпись валюты и всё.
            curs = {(x["unit"] or "").upper() for x in out["fare"]}
            if len(curs) == 1 and (cur := next(iter(curs))) not in ("", "EUR"):
                from . import fx as _fx
                with self.lock:
                    rate, prov = _fx.resolve(self.store, cur, None)
                if rate:
                    # Показываем В ЕВРО, валюта источника уходит в подпись.
                    # Числа в разных деньгах в одной колонке — приглашение
                    # сравнить несравнимое, а подпись рядом с числом это
                    # приглашение лишь смягчает.
                    out["fare_eur"] = [x["value"] / rate for x in out["fare"]]
                    out["fare_fx"] = f"{rate:.4g} {cur}/EUR, {prov}"
                    out["fare_src_cur"] = cur
        else:
            # «Нет данных» без счёта читается как «источник не работает».
            # Сказать, по скольким маршрутам они ЕСТЬ, — значит отличить
            # «не собрано вовсе» от «собрано, но не про этот маршрут».
            with self.lock:
                other = self.store.db.execute(
                    """SELECT COUNT(DISTINCT substr(key, 1, instr(key, '/') - 1))
                       FROM facts WHERE domain = 'market_fare'
                       AND valid_to IS NULL""").fetchone()[0]
            out["fare_elsewhere"] = other
        # Что есть в домене вообще — чтобы витрина могла сказать не просто
        # «нет», а «есть вот это, но не то, что нужно».
        return out

    def node(self, q: dict) -> dict:
        """Узел карты и то, откуда он берёт входы.

        Нужен для шагов БЕЗ адреса факта: они вычислены, и продолжать
        трассировку надо не «ключа нет», а перечнем того, из чего
        величина получена. Карта данных это знает — там у каждого узла
        перечислены входы с указанием, что именно берётся и в чём.
        """
        from .graph import N
        nid = q.get("id", "")
        by_id = {x["id"]: x for x in N}
        me = by_id.get(nid)
        if me is None:
            return {"id": nid, "found": False,
                    "why": "узла с таким идентификатором нет на карте данных"}
        # Вход из справочника ведёт к источнику: у узла-справочника подпись
        # — имя домена, а реестр знает, какой источник домен наполняет.
        # Без этого аэронавигация показывала «enroute_rate · store» и
        # ничего, что можно открыть; сборы аэропорта ссылку имели, потому
        # что там адрес лежит в самом факте.
        reg = self.registry.get("sources", {})
        def sources_for(domain: str) -> list[dict]:
            out = []
            for sid, sv in reg.items():
                doms = sv.get("domain")
                doms = doms if isinstance(doms, list) else [doms]
                if domain in doms:
                    out.append({"id": sid, "title": sv.get("title"),
                                "url": sv.get("url") or sv.get("url_template"),
                                "templated": not sv.get("url") and bool(sv.get("url_template")),
                                "license": sv.get("license")})
            return out
        def reachable(start: str, empty: list | None = None) -> dict:
            """Справочники, до которых можно дойти вверх по входам узла.

            `empty` собирает справочники БЕЗ источника в реестре — у
            fleet_economics его нет, и вместо справочника работает
            заготовка. Пустой список источников у ставки ТОиР выглядел как
            «источник не указан», а это ответ: данных нет, есть оценка.
            """
            seen, todo, found = set(), [start], {}
            while todo:
                cur = todo.pop()
                if cur in seen or len(seen) > 60:
                    continue
                seen.add(cur)
                node = by_id.get(cur, {})
                if node.get("role") == "store":
                    got = sources_for(node.get("label", ""))
                    if not got and empty is not None and node.get("label") not in empty:
                        empty.append(node.get("label"))
                    for s_ in got:
                        found.setdefault(s_["id"], dict(s_, domain=node.get("label")))
                todo.extend(i["id"] for i in node.get("inputs") or [])
            return found

        # Источники — ПО ВХОДУ, а не общей кучей. Общий список у ТОиР
        # называл OurAirports: справочник честно достижим через блок-время
        # (координаты → дистанция → время), но под заголовком «Источники»
        # у ставки ТОиР он читался как источник ставки.
        ins = []
        for inp in me.get("inputs") or []:
            src = by_id.get(inp["id"], {})
            empty: list = []
            found = reachable(inp["id"], empty)
            ins.append({"id": inp["id"], "take": inp["take"],
                        "unit": inp["unit"], "label": src.get("label", inp["id"]),
                        "role": src.get("role", ""), "note": src.get("note", ""),
                        "sources": list(found.values()), "unsourced": empty})
        srcs = reachable(nid)
        # Сверка — источники, которые стоят РЯДОМ с величиной: полоса
        # бенчмарка. Собираются по узлу и его входам на один шаг.
        refs = {}
        for x in [me] + [by_id.get(i["id"], {}) for i in me.get("inputs") or []]:
            for sid in x.get("refs") or []:
                sv = reg.get(sid)
                if sv:
                    refs.setdefault(sid, {"id": sid, "title": sv.get("title"),
                                          "url": sv.get("url"), "license": sv.get("license")})
        return {"id": nid, "found": True, "label": me.get("label"),
                "unit": me.get("unit"), "role": me.get("role"),
                "formula": me.get("formula"), "emits": me.get("emits"),
                "note": me.get("note"), "inputs": ins,
                "sources": list(srcs.values()), "refs": list(refs.values()),
                "fields": me.get("fields") or []}

    def data(self) -> dict:
        from . import inventory
        from .browse import is_public
        with self.lock:
            self.store.registry = self.registry
            out = inventory.collect(self.store)
        # Решение 219: на публичной витрине образцы строк — только из
        # открытых источников; закрытые остаются числом в `sources`.
        if self.public:
            for d in out["domains"]:
                d["shown"] = [r for r in d.get("shown") or []
                              if is_public(self.registry, r.get("source"))]
        return out

    def browse(self, q: dict) -> dict:
        """Просмотр хранилища (/data): каталог разделов или страница строк."""
        from . import browse
        with self.lock:
            if not q.get("domain"):
                return browse.catalog(self.store, self.registry, open_all=not self.public)
            try:
                page = int(q.get("page") or 0)
            except ValueError:
                page = 0
            return browse.rows(self.store, self.registry, q["domain"], q.get("q", ""),
                               page, open_all=not self.public)

    def map_page(self) -> bytes:
        """Карта данных на сайте: та же, что `fca map`, плюс форма маршрута."""
        from .graph import to_html
        return _i18n(to_html(self.registry, web=True)).encode("utf-8")


LEGAL_FIELDS = ("name", "street", "city", "email", "hoster", "server_location")


def _legal_values() -> dict:
    """Реквизиты для Impressum и политики — из `web/legal.json`.

    Один файл, а не текст страниц: правите реквизиты, не трогая
    юридических формулировок, и наоборот. Файл в репозитории — Impressum
    публичен по определению, секретов в нём нет.
    """
    p = WEB / "legal.json"
    if not p.exists():
        return {}
    return {k: str(v).strip() for k, v in
            json.loads(p.read_text(encoding="utf-8")).items()
            if v is not None and not k.startswith("_")}


def _legal_page(kind: str, values: dict | None = None) -> bytes:
    """Impressum или Datenschutz с подставленными реквизитами.

    Незаполненное поле видно на странице красной пометкой, а не пустым
    местом: пустой Impressum выглядит готовым и потому опаснее
    отсутствующего.
    """
    import html as _html
    vals = _legal_values() if values is None else values
    page = (WEB / f"{kind}.html").read_text(encoding="utf-8")

    def sub(m):
        v = (vals.get(m.group(1)) or "").strip()
        return (_html.escape(v) if v else
                f'<mark class="todo">[{m.group(1)}: не заполнено]</mark>')
    return re.sub(r"\{\{(\w+)\}\}", sub, page).encode("utf-8")


# Зона ожидания для страницы отчёта, пока сеть считается (те же фразы и
# рисунок, что у витрины в serve.html).
LOADER_PHRASES = ("Запрашиваю запуск", "Руление к исполнительному старту", "Взлёт разрешён",
                  "Набираю эшелон", "Обхожу закрытое небо", "Сверяю сборы аэропортов",
                  "Считаю топливо до запасного", "Выбираю запасной аэродром",
                  "Связываюсь с подходом", "Вхожу в зону ожидания", "Ухожу на второй круг",
                  "Запрашиваю разрешение на посадку", "Выпускаю шасси")
LOADER_CSS = (
    "#loader{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);display:flex;"
    "flex-direction:column;align-items:center;gap:10px;padding:22px 28px 18px;border-radius:14px;"
    "background:var(--panel);border:1px solid var(--line);min-width:260px;max-width:86vw}"
    "#loader svg{width:132px;height:132px;overflow:visible}"
    "#loader .orbit{fill:none;stroke:var(--line);stroke-width:1.2;stroke-dasharray:3 5}"
    "#loader .rwy{fill:var(--raise);stroke:var(--line)}"
    "#loader .rwy-c{stroke:var(--dim);stroke-width:.8;stroke-dasharray:3 3}"
    "#loader .hold{animation:o 5.2s linear infinite;transform-origin:0 0}"
    "#loader .plane{fill:var(--doc)}"
    "#loader .trail{fill:none;stroke:var(--doc);stroke-width:1.6;stroke-linecap:round;opacity:.35}"
    "#loader .ph{font:600 14px/1.35 var(--sans);color:var(--ink2);text-align:center}"
    "#loader .sub{font:12px var(--sans);color:var(--dim);text-align:center}"
    "@keyframes o{to{transform:rotate(360deg)}}"
    "@media (prefers-reduced-motion:reduce){#loader .hold{animation:none}}")
LOADER_SVG = (
    '<div id="loader" role="status"><svg viewBox="-66 -66 132 132" aria-hidden="true">'
    '<circle class="orbit" r="46"/><rect class="rwy" x="-5" y="-22" width="10" height="44" rx="2"/>'
    '<line class="rwy-c" x1="0" y1="-18" x2="0" y2="18"/><g class="hold">'
    '<path class="trail" d="M0,-46 A46,46 0 0 0 -32.5,-32.5"/><g transform="translate(0,-46) rotate(90)">'
    '<path class="plane" d="M0,-9 C1.1,-9 1.5,-7.5 1.5,-6 L1.5,-2.2 L9,2 L9,3.6 L1.5,1.4 L1.3,5.6 '
    'L4,7.6 L4,8.8 L0,7.8 L-4,8.8 L-4,7.6 L-1.3,5.6 L-1.5,1.4 L-9,3.6 L-9,2 L-1.5,-2.2 L-1.5,-6 '
    'C-1.5,-7.5 -1.1,-9 0,-9Z"/></g></g></svg>'
    '<div class="ph">{ph}</div><div class="sub">{sub}</div></div>')


def _page(name: str = "serve.html") -> bytes:
    """Страница витрины с вшитым каталогом переводов.

    Каталог вшивается, а не грузится отдельным запросом: страница остаётся
    одним самодостаточным файлом, и подписи готовы до первой отрисовки —
    без мелькания русского текста перед английским.
    """
    return _i18n((WEB / name).read_text(encoding="utf-8")).encode("utf-8")


def _i18n(html: str) -> str:
    """Вшить каталог переводов на место `/*I18N*/{}/*/I18N*/`."""
    cat_path = WEB / "i18n.json"
    if cat_path.exists():
        cat = json.dumps(json.loads(cat_path.read_text(encoding="utf-8")),
                         ensure_ascii=False, separators=(",", ":"))
        # «</» внутри <script> закрыл бы его раньше времени
        cat = cat.replace("</", "<\\/")
        html = html.replace("/*I18N*/{}/*/I18N*/", "/*I18N*/" + cat + "/*/I18N*/", 1)
    return html


def serve(store, registry, *, host: str = "127.0.0.1", port: int = 8000,
          warm: bool = True, log=print, public: bool = False,
          guests: bool | None = None) -> None:
    # Соединение приходит из CLI уже снятым с привязки к потоку
    # (`Store(..., shared=True)`). Безопасность держит замок в `Context`,
    # а не отключённая проверка — она только перестаёт мешать.
    # Слой гостя: на публичной витрине всегда, локально — по флагу.
    # Файл лежит рядом со справочником и в снимок `fca publish` не входит.
    gdb = None
    if guests if guests is not None else public:
        gdb = GuestDB(Path(store.path).parent / "user.db")
        n = gdb.prune()                   # сразу, не дожидаясь метлы по часам
        log(f"рабочие места гостей: {gdb.path}" + (f", удалено {n} забытых" if n else ""))
    ctx = Context(store, registry, public=public, gdb=gdb)
    from .visits import Visits, stats_path
    ctx.visits = Visits(stats_path(store.path))
    log(f"статистика посещений: {ctx.visits.path}")
    if warm:
        # Прогрев в явном виде: пять секунд холодных импортов иначе
        # заплатит первый же запрос, и человек решит, что тормозит всё.
        log("прогрев ядра…")
        try:
            ctx.route({"origin": "FRA", "destination": "BCN"})
        except Exception as exc:                          # noqa: BLE001
            log(f"  прогрев не удался: {type(exc).__name__}: {exc}")
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.ctx = ctx
    log(f"витрина: http://{host}:{port}/   (Ctrl-C чтобы остановить)")
    log("  хранилище остаётся файлом, наружу сервер не слушает")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("\nостановлено")
