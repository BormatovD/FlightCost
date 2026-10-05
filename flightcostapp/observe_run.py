"""Забор наблюдений: единственное место, где у накопления есть сеть.

`observe.py` и `adsb_opensky.py` написаны без сети намеренно — они
проверяются на выдуманных рейсах и не знают ни про ключи, ни про паузы.
Всё это живёт здесь.

ДОСТУП. КЛЮЧИ НУЖНЫ. Анонимно отдаются только самые свежие состояния
бортов, а параметр времени игнорируется; эндпоинт рейсов за интервал —
именно временной, и без ключей он отвечает отказом. Я утверждал обратное,
и первый же прогон дал двадцать восемь отказов подряд.

С марта 2026 доступ идёт через OAuth2: пароль не принимается, нужны
идентификатор клиента и секрет. Заводятся на странице учётной записи
OpenSky, скачиваются файлом `credentials.json`.

    export OPENSKY_CLIENT_ID=...
    export OPENSKY_CLIENT_SECRET=...
    # либо положить credentials.json и указать путь:
    export OPENSKY_CREDENTIALS=~/opensky/credentials.json

Ключи берутся ТОЛЬКО из окружения или из файла, на который указывает
окружение. В реестре их нет и не будет: реестр лежит в репозитории, а
рецепт не должен содержать пропуск.

Учётная запись даёт 4000 запросных единиц в сутки, активный участник сети
— 8000. Двадцать восемь аэропортов на два прохода это 56 запросов, то есть
лимит не узкое место.

ПОЧЕМУ ЗАПУСКАТЬ СЕГОДНЯ. Живой поток отдаёт настоящее, а не прошлое.
Исторический массив выдаётся исследователям при университетах,
государственным организациям и авиавластям, частным лицам — по заявке.
Чего не накопили сами, того потом не будет: каждые пропущенные сутки
невосстановимы. Это единственный источник в проекте, где просрочка
означает потерю, а не устаревшее число.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

TOKEN_URL = ("https://auth.opensky-network.org/auth/realms/opensky-network/"
             "protocol/openid-connect/token")
PAUSE_S = 1.2          # между запросами: лимит считается в сутки, но частить незачем
RETRY_429 = 2          # попытки при «слишком часто», с растущей паузой
TIMEOUT_S = 45

# С чего начинать. Аэропорты СБОРОВ и аэропорты НАБЛЮДЕНИЙ — разные
# множества: тариф нужен там, где считаем, наблюдение — там, где летают.
# Накопление по аэропорту, тарифа которого пока нет, сегодня ничего не
# стоит и завтра невосстановимо, поэтому список шире тарифного.
DEFAULT_AIRPORTS = [
    # уже с разобранным тарифом
    "EDDF", "LEBL", "EGKK", "EIDW", "EPPO", "LATI", "LEPA", "LIBR",
    "LICJ", "LIME", "LOWW", "LPPR",
    # плотные европейские узлы: сюда придут тарифы, а наблюдения нужны раньше
    "EHAM", "LFPG", "EDDM", "LEMD", "LIRF", "LSZH", "EGLL", "EKCH",
    "ESSA", "ENGM", "LGAV", "LPPT", "EBBR", "LIMC", "EDDB", "LFMN",
]


def _note_budget(headers) -> None:
    """Остаток бюджета из заголовка ответа, если сервер его прислал."""
    if not headers:
        return
    for name in ("X-Rate-Limit-Remaining", "x-rate-limit-remaining"):
        v = headers.get(name)
        if v is None:
            continue
        try:
            BUDGET["left"] = int(v)
            BUDGET["seen"] = True
        except (TypeError, ValueError):
            pass
        return


def budget_left() -> int | None:
    return BUDGET["left"] if BUDGET["seen"] else None


def credentials() -> tuple[str | None, str | None]:
    """Ключи из окружения или из `credentials.json`, как их даёт OpenSky."""
    cid = os.environ.get("OPENSKY_CLIENT_ID")
    secret = os.environ.get("OPENSKY_CLIENT_SECRET")
    if cid and secret:
        return cid, secret
    path = os.environ.get("OPENSKY_CREDENTIALS")
    if path:
        import pathlib
        d = json.loads(pathlib.Path(path).expanduser().read_text("utf-8"))
        return d.get("clientId") or d.get("client_id"), \
               d.get("clientSecret") or d.get("client_secret")
    return None, None


def token() -> str | None:
    """Токен OAuth2, если заданы ключи. Иначе — анонимный доступ.

    Отказ на этом шаге НЕ глушится: без токена каждый последующий запрос
    вернёт отказ, и двадцать восемь одинаковых строк скажут меньше, чем
    одна внятная здесь.
    """
    cid, secret = credentials()
    if not (cid and secret):
        return None
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": cid, "client_secret": secret}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as exc:
        detail = (exc.read() or b"")[:200].decode("utf-8", "replace")
        raise RuntimeError(
            f"не удалось получить токен OpenSky: HTTP {exc.code}. {detail}\n"
            f"  проверьте OPENSKY_CLIENT_ID и OPENSKY_CLIENT_SECRET на "
            f"странице учётной записи") from None


# Остаток суточного бюджета, как его сообщает сервер. Ставится из
# заголовка ответа и живёт до конца прогона.
#
# ЗАЧЕМ. Я посчитал двадцать восемь аэропортов на два прохода как
# «пятьдесят шесть запросов» и заключил, что лимит не узкое место. Считать
# надо было не запросы, а КРЕДИТЫ: у эндпоинта рейсов цена обращения
# зависит от длины окна, а нам нужны ровно сутки — самая дорогая полоса.
# Отсюда исчерпание на двадцатом аэропорту и три отказа подряд на
# следующий день.
#
# Догадка заменяется измерением: сервер шлёт остаток заголовком, и его
# надо читать, а не выводить из поведения.
BUDGET = {"left": None, "seen": False}
BUDGET_FLOOR = 40      # ниже — останавливаемся сами, не дожидаясь отказа


def make_fetch(tok: str | None, pause: float = PAUSE_S):
    """Загрузчик, который отдают в `adsb_opensky.pull`.

    Пустой ответ и 404 — не ошибка: у аэропорта могло не быть рейсов в
    окне, а у OpenSky это тот же код. Отличать их нечем, и притворяться,
    что можно, не стоит: возвращаем пусто и пишем это в отчёт.
    """
    def fetch(url: str) -> list:
        # Отказ «слишком часто» — ВРЕМЕННЫЙ, и терять из-за него сутки по
        # аэропорту нельзя: они невосстановимы. Отступаем и пробуем
        # снова, увеличивая паузу. Если и это не помогло — пусть решает
        # вызывающий, у него есть размыкатель.
        delay = pause
        for attempt in range(RETRY_429 + 1):
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "flightcostapp/observe")
            if tok:
                req.add_header("Authorization", f"Bearer {tok}")
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                    _note_budget(r.headers)
                    data = json.loads(r.read() or b"[]")
                time.sleep(pause)
                return data if isinstance(data, list) else []
            except urllib.error.HTTPError as exc:
                _note_budget(getattr(exc, "headers", None))
                if exc.code == 404:
                    time.sleep(pause)
                    return []                    # окно без рейсов, не ошибка
                if exc.code == 429 and attempt < RETRY_429:
                    delay = max(delay * 3, 5.0)
                    time.sleep(delay)
                    continue
                time.sleep(pause)
                raise
    return fetch


def run(store, *, day=None, airports=None, source_id="adsb_flights",
        pause: float = PAUSE_S, verbose=print) -> dict:
    """Один цикл: сутки, список аэропортов, вылеты и прилёты.

    Вчерашние сутки по умолчанию: сегодняшние ещё не закончились, а окно
    берётся с перекрытием, и рейс через полночь иначе теряется.
    """
    from . import adsb_opensky, observe

    day = day or (date.today() - timedelta(days=1))
    airports = airports or DEFAULT_AIRPORTS
    fetch = make_fetch(token(), pause)
    marks: list[tuple[str, str]] = []

    # Что уже забрано за эти сутки — не спрашиваем у памяти, а смотрим в
    # таблицу. Метка ставится по каждой паре «аэропорт × вид», и по её
    # отсутствию видно, что осталось. Без этого закрытый на ночь ноутбук
    # или исчерпанный лимит теряют сутки навсегда: живой поток отдаёт
    # настоящее, а не прошлое.
    done = store.fetched_marks(str(day)) if hasattr(store, "fetched_marks") else set()
    rows, failed, halted = [], [], None
    for kind in ("departure", "arrival"):
        todo = [a for a in airports if (a, kind) not in done]
        if not todo:
            verbose(f"  {kind}: уже забрано")
            continue
        skipped = len(airports) - len(todo)
        got, bad, stop, ok = adsb_opensky.pull(
            fetch, todo, day, kind=kind, budget=budget_left, floor=BUDGET_FLOOR)
        rows += got
        failed += [f"{kind} {x}" for x in bad]
        # Метка ставится ТОЛЬКО за ответившие аэропорты. Отказавший
        # останется в пробелах и будет добран следующим прогоном.
        marks.extend((a, kind) for a in ok)
        verbose(f"  {kind}: рейсов {len(got)}, забрано {len(ok)} из {len(todo)}"
                + (f", пропущено как забранное {skipped}" if skipped else "")
                + (f", не ответили {len(bad)}" if bad else ""))
        if stop:
            halted = f"{kind}: {stop}"
            verbose(f"  ОСТАНОВЛЕНО — {stop}")
            break

    # Тип берётся из реестра бортов: борт вещает адрес транспондера, а не
    # тип, и без сопоставления главная строка — блок-время ПО ТИПУ — не
    # собирается вовсе. Кэш на прогон: адреса повторяются.
    cache: dict[str, str | None] = {}

    def type_of(icao24: str):
        a = (icao24 or "").strip().lower()
        if a not in cache:
            # Спрашиваем на СЕГОДНЯ, а не на дату рейса. Реестр бортов —
            # состояние мира на момент снимка, а не ставка, действующая
            # «с и по»: снимок, загруженный сегодня, начинает действовать
            # сегодня, и на вчерашние рейсы не отвечал бы вовсе. Ровно тот
            # же довод, что в решении 23 про курс валюты — берётся
            # последняя известная котировка, потому что пустой ответ хуже
            # ответа трёхдневной давности.
            #
            # Цена: борт, перерегистрированный на другой тип, будет
            # отнесён к нынешнему типу задним числом. Для этого нужны
            # исторические снимки реестра, которых у нас нет и которые
            # никто не публикует.
            row = store.get("aircraft_registry", a, None)
            cache[a] = (row["value_text"] or None) if row else None
        return cache[a]

    st = observe.collect(store, rows, source_id=source_id, type_of=type_of)
    if marks and hasattr(store, "mark_fetched"):
        store.mark_fetched(str(day), marks, source_id=source_id)
    st["failed"] = failed
    st["halted"] = halted
    st["marked"] = len(marks)
    st["budget_left"] = budget_left()
    st["day"] = str(day)
    st["airports"] = len(airports)
    # Пропуск одного аэропорта за сутки невосстановим так же, как пропуск
    # всех, поэтому список неответивших идёт в отчёт, а не в лог.
    if failed:
        verbose("  не ответили: " + ", ".join(failed[:8])
                + (f" …и ещё {len(failed) - 8}" if len(failed) > 8 else ""))
    return st


def probe(day=None, airport: str = "EDDF") -> str:
    """Один запрос, чтобы увидеть ответ целиком, а не двадцать восемь имён
    исключений. Ничего не пишет в хранилище."""
    from datetime import date as _d, timedelta as _td
    from . import adsb_opensky
    day = day or (_d.today() - _td(days=1))
    begin, end = adsb_opensky.windows(day)
    url = (f"{adsb_opensky.BASE}/flights/departure"
           f"?airport={airport}&begin={begin}&end={end}")
    cid, _ = credentials()
    out = [f"ключи: {'есть, ' + cid[:8] + '…' if cid else 'НЕТ — анонимно'}"]
    tok = None
    try:
        tok = token()
        out.append("токен: получен" if tok else "токен: не запрашивался")
    except Exception as exc:                           # noqa: BLE001
        out.append(f"токен: {exc}")
        return "\n".join(out)
    from datetime import datetime as _dt, timezone as _tz
    out.append(f"окно:   {_dt.fromtimestamp(begin, _tz.utc):%Y-%m-%d %H:%M} … "
               f"{_dt.fromtimestamp(end, _tz.utc):%Y-%m-%d %H:%M} UTC "
               f"({(end - begin) / 3600:.0f} ч)")
    out.append(f"запрос: {url}")
    try:
        rows = make_fetch(tok, pause=0)(url)
        out.append(f"ответ: рейсов {len(rows)}")
        left = budget_left()
        if left is not None:
            # Один запрос суточного окна стоит столько-то кредитов, и
            # отсюда видно, на сколько аэропортов хватит: цена обращения
            # зависит от длины окна, а не от числа запросов.
            out.append(f"бюджет: осталось {left} кредитов")
            out.append(f"  при {len(DEFAULT_AIRPORTS)} аэропортах на сутки "
                       f"нужно {len(DEFAULT_AIRPORTS) * 2} обращений")
        if rows:
            r = rows[0]
            out.append(f"  пример: {r.get('icao24')} {r.get('callsign','').strip()} "
                       f"{r.get('estDepartureAirport')}→{r.get('estArrivalAirport')}")
    except Exception as exc:                           # noqa: BLE001
        out.append(f"ответ: {adsb_opensky._why(exc)}")
        left = budget_left()
        if left is not None:
            out.append(f"бюджет: осталось {left} кредитов")
        elif getattr(exc, "code", None) == 429:
            out.append("бюджет: сервер остатка не прислал; три отказа подряд "
                       "при растущей паузе означают исчерпанный суточный "
                       "лимит, а не частоту — ждать до полуночи UTC")
    return "\n".join(out)


def gaps(store, *, limit: int = 25, since: str | None = None) -> str:
    """Борта, которые наблюдались, но типа у них нет.

    Вопрос не «сколько», а «каких»: четверть без типа может означать и
    равномерный пробел реестра, и один перевозчик, у которого не заведён
    весь парк. Первое — свойство источника, второе — наша дыра, и лечатся
    они по-разному.

    Позывной берётся из наблюдения: первые три знака — код перевозчика
    ИКАО, и по ним видно, сосредоточен пробел или размазан. У бортов без
    позывного (частные, государственные) кода нет, и это тоже ответ.
    """
    where = "WHERE kind = 'frequency'" + (
        " AND observed_at >= ?" if since else "")
    args = (since,) if since else ()
    rows = store.db.execute(
        f"""SELECT ref, note, COUNT(*) n FROM observations {where}
            GROUP BY ref ORDER BY n DESC""", args).fetchall()
    known = {r[0] for r in store.db.execute(
        "SELECT DISTINCT key FROM facts WHERE domain = 'aircraft_registry'")}

    miss, seen_n, miss_n = {}, 0, 0
    for ref, note, n in rows:
        seen_n += n
        if (ref or "").lower() in known:
            continue
        miss_n += n
        code = (note or "").strip()[:3].upper() or "—"
        slot = miss.setdefault(code, {"flights": 0, "tails": set(), "sample": []})
        slot["flights"] += n
        slot["tails"].add(ref)
        if len(slot["sample"]) < 3 and note:
            slot["sample"].append(note.strip())

    out = [f"наблюдалось рейсов {seen_n}, из них без типа {miss_n} "
           f"({miss_n / seen_n:.1%})" if seen_n else "наблюдений нет"]
    if not miss:
        return out[0]
    out.append(f"бортов без типа: {sum(len(v['tails']) for v in miss.values())}")
    out.append("")
    out.append(f"{'позывной':>9}  {'рейсов':>7} {'бортов':>7}  примеры")
    for code, v in sorted(miss.items(), key=lambda x: -x[1]["flights"])[:limit]:
        out.append(f"{code:>9}  {v['flights']:>7} {len(v['tails']):>7}  "
                   + ", ".join(v["sample"][:3]))
    tail = len(miss) - limit
    if tail > 0:
        out.append(f"{'':>9}  …и ещё {tail} кодов")
    out.append("")
    out.append("Код «—» — борта без позывного: частные и государственные. "
               "Их в реестре OpenSky обычно нет, и это свойство источника, "
               "а не наш пробел.")
    return "\n".join(out)
