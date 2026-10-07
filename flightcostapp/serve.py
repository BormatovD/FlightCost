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
import re
import threading
import traceback
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

try:
    from .econ import COST_RU as _COST_RU
except ImportError:            # подписей нет — показываем ключи как есть
    _COST_RU = {}


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
                  "pax": int(round((res.inputs.get("seats") or 0)
                                   * float(res.inputs.get("load_factor") or 0)))},
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

    def log_message(self, fmt, *args):        # тише: страница делает много запросов
        if "200" not in (fmt % args):
            super().log_message(fmt, *args)

    def do_POST(self):                                    # noqa: N802
        """Запись — только своих типов ВС, и только через тот же парсер и
        гейт, что у файла в каталоге. Сервер пишет файл сам: каталог
        остаётся источником (решение 1), база — производной от него.
        """
        u = urllib.parse.urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/aircraft/save":
                return self._json(self.server.ctx.aircraft_save(body))
            if u.path == "/api/aircraft/delete":
                return self._json(self.server.ctx.aircraft_delete(body))
            return self._send(404, b"not found", "text/plain")
        except Exception as exc:                          # noqa: BLE001
            return self._json({"error": f"{type(exc).__name__}: {exc}",
                               "trace": traceback.format_exc()}, 400)

    def do_GET(self):                                     # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/healthz":
                # Что сейчас на сервере: версия кода и дата снимка
                # справочника. По ней проверяет себя выкладка и ей
                # проверяете вы — «на домене то, что я думаю».
                return self._json(self.server.ctx.health())
            if u.path in ("/api/solve", "/api/compare") and not self.server.ctx.allow(
                    self._client_ip()):
                return self._json({"error": "слишком часто: тяжёлые расчёты — не чаще "
                                            f"{self.server.ctx.HEAVY_PER_MIN} в минуту с адреса"},
                                  429)
            if u.path in ("/", "/index.html"):
                return self._send(200, _page(), "text/html; charset=utf-8")
            if u.path == "/api/airports":
                return self._json(self.server.ctx.airports())
            if u.path == "/api/route":
                return self._json(self.server.ctx.route(q))
            if u.path == "/api/fact":
                return self._json(self.server.ctx.fact(q))
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
                return self._json(self.server.ctx.geo())
            if u.path == "/api/bench":
                return self._json(self.server.ctx.bench(q))
            if u.path == "/api/node":
                return self._json(self.server.ctx.node(q))
            if u.path == "/api/data":
                return self._json(self.server.ctx.data())
            if u.path == "/api/aircraft":
                return self._json(self.server.ctx.aircraft())
            if u.path == "/api/solve":
                return self._json(self.server.ctx.solve(q))
            if u.path == "/api/compare":
                return self._json(self.server.ctx.compare(q))
            if u.path == "/api/aircraft/type":
                return self._json(self.server.ctx.aircraft_type(q))
            if u.path == "/api/aircraft/draft":
                # Заготовка JSON для каталога своих типов: сервер НЕ пишет
                # в хранилище, файл кладёт человек, заводит refresh, принимает
                # review — тот же путь, что у тарифов (решение 4).
                body = json.dumps(self.server.ctx.aircraft_draft(q),
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
            if len(self._rl) > 5000:            # не копить адреса вечно
                for k in [k for k, v in self._rl.items() if not v][:1000]:
                    del self._rl[k]
            return True

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
        return out

    def __init__(self, store, registry, public: bool = False):
        self.store, self.registry = store, registry
        self.lock = threading.Lock()
        self._apts = None
        # Публичная витрина: запись в общее хранилище закрыта. Свои типы
        # гостей — слой сценария (решение 33), ему нужна своя область
        # видимости по автору; пока её нет, сохранение честно отказывает.
        self.public = public
        self._rl, self._rl_lock = {}, threading.Lock()
        self._facts_n = None

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
            with self.lock:
                flights: dict[str, float] = {}
                for key, value in self.store.db.execute(
                        "SELECT key, value FROM observations WHERE kind='frequency'"):
                    pair = (key or "").split("/")[0]
                    if "-" not in pair:
                        continue
                    for side in pair.split("-"):
                        flights[side] = flights.get(side, 0) + (value or 1)
            with self.lock:
                tariffed = {r[0].split("/")[0] for r in self.store.db.execute(
                    "SELECT DISTINCT key FROM facts WHERE domain='airport_charge'")}
                seen = set()
                for (k,) in self.store.db.execute(
                        "SELECT DISTINCT key FROM observations "
                        "WHERE kind='frequency'"):
                    seen.update((k or "").split("/")[0].split("-"))
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
        if sets:
            kw["overrides"] = parse_set(sets)
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
        return result_json(res)

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
        from .econ import load_aircraft, route_economics
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
        o = self.resolve(q.get("origin", "FRA"))
        d = self.resolve(q.get("destination", "BCN"))
        pax = float(q.get("pax") or 0)
        want = [t for t in (q.get("types") or "").upper().split(",") if t]
        if not want:
            want = [t["icao"] for t in self.aircraft() if t["usable"]]
        rows = []
        for t in want:
            row = {"icao": t, "status": "failed", "why": ""}
            rows.append(row)
            try:
                with self.lock:
                    ac = load_aircraft(self.store, t, kw.get("as_of"), kw.get("operator", "*"))
                row.update(name=ac.name, seats=ac.seats, seats_source=ac.seats_source)
                if pax <= 0:
                    row.update(status="failed", why="не задано число пассажиров")
                    continue
                if pax > ac.seats:
                    # Не «нельзя» модели, а нехватка кресел: отдельный статус,
                    # чтобы не смешивать с перегрузом и баками.
                    row.update(status="too_small",
                               why=f"{int(pax)} пассажиров при {ac.seats} креслах")
                    continue
                k = dict(kw, aircraft=t, load_factor=pax / ac.seats)
                with self.lock:
                    res = route_economics(self.store, o, d, **k)
                tier = next((st for st in res.trace if st.label == "Ярус расхода"), None)
                cost = sum(res.cost.values())
                row.update(
                    status="ok" if res.feasible else "infeasible",
                    why="" if res.feasible else "; ".join(
                        l.get("text", "") for l in (res.feasibility or {}).get("limits", [])),
                    limits=[l.get("key") for l in (res.feasibility or {}).get("limits", [])],
                    lf=pax / ac.seats, cost_total=cost, cost_per_pax=cost / pax,
                    breakeven_fare_eur=res.breakeven_fare_eur,
                    cask=cost / (ac.seats * res.distance_nm * 1.852) * 100
                         if res.distance_nm else None,
                    fuel_kg=res.fuel_kg, fuel_per_pax=res.fuel_kg / pax,
                    block_h=res.block_h, max_pax=res.max_pax,
                    tier=tier.value if tier else None,
                    tier_note=tier.subst if tier else "",
                    default_share=res.default_share(),
                    unused=[w for w in res.warnings if "не используется" in w])
            except KeyError as exc:
                row.update(status="failed", why=str(exc).strip("'"))
            except Exception as exc:                          # noqa: BLE001
                row.update(status="failed", why=f"{type(exc).__name__}: {exc}")
        # Порядок: выполнимые по себестоимости на пассажира, потом
        # невыполнимые, потом маленькие, потом сбои.
        rank = {"ok": 0, "infeasible": 1, "too_small": 2, "failed": 3}
        rows.sort(key=lambda r: (rank[r["status"]], r.get("cost_per_pax") or 0))
        return {"pax": pax, "rows": rows, "dropped_ctx": dropped,
                "route": {"origin": o, "destination": d},
                "note": ("условия типа сняты у всех типов: " + ", ".join(dropped)
                         if dropped else "")}

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
        if self.public:
            return {"error": "публичная витрина: свои типы в общее хранилище не "
                             "пишутся; для гостей нужен слой сценария с автором — "
                             "ещё не сделан"}
        today = date.today().isoformat()
        doc = dict(doc)
        doc.setdefault("valid_from", today)
        doc["checked_at"] = today
        for k in ("fields", "burn"):
            if isinstance(doc.get(k), dict):
                doc[k] = {a: b for a, b in doc[k].items() if b not in ("", None)}
        if not doc.get("burn", {}).get("analog"):
            doc.pop("burn", None)
        ctx = {"source_id": self.USER_SRC, "sha": None,
               "extracted_by": "form:aircraft_user@1", "node": "src_aircraft_user"}
        facts = _one(doc, ctx)                      # отказ — ValueError словами
        key = facts[0].key.split("/")[0]
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
        if self.public:
            return {"error": "публичная витрина: удаление закрыто"}
        key = (body.get("icao") or "").upper()
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
        return {"icao": icao,
                "name": next((f["note"] for f in fields if f["field"] == "mtow_t"), ""),
                "fields": fields, "physics": physics, "analogs": analogs,
                "editable": not self.public and all(f["source"] == self.USER_SRC for f in fields),
                "public": self.public,
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
            "burn": burn,
        }

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
                """SELECT key, value, value_text, source_id FROM facts
                   WHERE domain = 'aircraft' AND valid_to IS NULL""").fetchall()
            lay = self.store.db.execute(
                """SELECT key, value, source_id, confidence FROM facts
                   WHERE domain = 'aircraft_layout' AND valid_to IS NULL""").fetchall()
        types: dict[str, dict] = {}
        for key, value, txt, src in rows:
            icao, _, field = (key or "").partition("/")
            if not icao or not field:
                continue
            t = types.setdefault(icao, {"icao": icao, "fields": {}, "sources": set()})
            t["fields"][field] = value if value is not None else txt
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
                "usable": f.get("mtow_t") is not None,
                "why_not": "" if f.get("mtow_t") is not None
                           else "в домене aircraft нет mtow_t",
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
        return {"domain": dom, "key": key, "found": True,
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
            cur = (d["meta"].get("opex_eur") or {}).get("currency", "")
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
            if len(item) > 2:
                derived.append(item)
        out["carriers"] = derived
        for name, field in (("cask", "cask_cents"), ("yield", "yield_eur_pax")):
            vals = sorted(x[field] for x in derived if field in x)
            if vals:
                out[name] = {"lo": vals[0], "hi": vals[-1], "n": len(vals)}
        out["have"] = sorted({m for d in by_carrier.values() for m in d["vals"]})

        if fares:
            out["fare"] = [{"key": k, "value": v, "unit": u,
                            "meta": json.loads(t or "{}")} for k, v, u, t in fares]
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
        ins = []
        for inp in me.get("inputs") or []:
            src = by_id.get(inp["id"], {})
            role = src.get("role", "")
            ins.append({"id": inp["id"], "take": inp["take"],
                        "unit": inp["unit"], "label": src.get("label", inp["id"]),
                        "role": role, "note": src.get("note", ""),
                        "sources": sources_for(src.get("label", "")) if role == "store" else []})
        # Источники узла — все справочники, до которых можно дойти вверх
        # по входам. У аэронавигации прямые входы сами вычислены (единицы
        # обслуживания, ставки зон), а справочник CRCO стоит за ними.
        seen, todo, srcs = set(), [nid], {}
        while todo:
            cur = todo.pop()
            if cur in seen or len(seen) > 60:
                continue
            seen.add(cur)
            node = by_id.get(cur, {})
            if node.get("role") == "store":
                for s_ in sources_for(node.get("label", "")):
                    srcs.setdefault(s_["id"], dict(s_, domain=node.get("label")))
            todo.extend(i["id"] for i in node.get("inputs") or [])
        return {"id": nid, "found": True, "label": me.get("label"),
                "unit": me.get("unit"), "role": me.get("role"),
                "formula": me.get("formula"), "emits": me.get("emits"),
                "note": me.get("note"), "inputs": ins,
                "sources": list(srcs.values()),
                "fields": me.get("fields") or []}

    def data(self) -> dict:
        from . import inventory
        with self.lock:
            self.store.registry = self.registry
            return inventory.collect(self.store)


def _page() -> bytes:
    """Страница витрины с вшитым каталогом переводов.

    Каталог вшивается, а не грузится отдельным запросом: страница остаётся
    одним самодостаточным файлом, и подписи готовы до первой отрисовки —
    без мелькания русского текста перед английским.
    """
    html = (WEB / "serve.html").read_text(encoding="utf-8")
    cat_path = WEB / "i18n.json"
    if cat_path.exists():
        cat = json.dumps(json.loads(cat_path.read_text(encoding="utf-8")),
                         ensure_ascii=False, separators=(",", ":"))
        # «</» внутри <script> закрыл бы его раньше времени
        cat = cat.replace("</", "<\\/")
        html = html.replace("/*I18N*/{}/*/I18N*/", "/*I18N*/" + cat + "/*/I18N*/", 1)
    return html.encode("utf-8")


def serve(store, registry, *, host: str = "127.0.0.1", port: int = 8000,
          warm: bool = True, log=print, public: bool = False) -> None:
    # Соединение приходит из CLI уже снятым с привязки к потоку
    # (`Store(..., shared=True)`). Безопасность держит замок в `Context`,
    # а не отключённая проверка — она только перестаёт мешать.
    ctx = Context(store, registry, public=public)
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
