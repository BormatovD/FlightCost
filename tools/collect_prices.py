# -*- coding: utf-8 -*-
"""
Сбор цен по маршрутной сети через Aviasales Data API (Travelpayouts).
Обновление 2026: месячные запросы (departure_at=YYYY-MM), новые поминутные
лимиты (X-Rate-Limit-Remaining / X-Rate-Limit-Reset), возобновление, агрегация.

Использование:
    export TP_TOKEN="ваш_токен"
    python collect_prices.py collect   --routes "Маршрутная_сеть.xlsx" --months 12
    python collect_prices.py aggregate --routes "Маршрутная_сеть.xlsx"

Выход:
    flight_data/raw_*.csv            — сырые предложения (чанки, возобновляемо)
    flight_data/prices_by_route.csv  — min/median/mean/max и др. по маршрутам
    flight_data/prices_by_day.csv    — статистика по дням вылета
"""
import argparse
import os
import sys
import time
import glob
from datetime import datetime

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

RUN = datetime.now().strftime("%Y%m%dT%H%M")
API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def _token() -> str:
    """Ключ из окружения, очищенный от того, что к нему липнет при копировании.

    В переменной оказывался «token=…» — хвост адреса из документации,
    скопированный целиком, — и ключ на шесть символов длиннее настоящего.
    В заголовке такой ключ давал 401 на каждом запросе, а по ссылке в
    браузере тот же человек видел ответ: там он вводил ключ без префикса.
    Очищаются пробелы, кавычки и префиксы «token=», «X-Access-Token:».
    """
    t = os.environ.get("TP_TOKEN", "").strip().strip("\"'").strip()
    for pref in ("token=", "x-access-token:", "x-access-token"):
        if t.lower().startswith(pref):
            t = t[len(pref):].strip(" =:")
    return t


TOKEN = _token()
OUT = "flight_data"
LOG = os.path.join(OUT, "processed.log")   # route,month,status,rows
PAGE_LIMIT = 1000                          # максимум записей на страницу v3
# Валюта запроса — одна на весь сбор и одна на весь файл. Объявлена здесь,
# потому что её читают ТРИ места: параметр запроса, колонка `currency` в
# выгрузке и подпись колонок сводки. Пока она жила только в параметре,
# выгрузка выходила без валюты, разбор подставлял рубли, и 36 567 евровых
# минимумов легли в хранилище как «99 RUB».
CURRENCY = "eur"
SESSION = requests.Session()
# Ключ едет параметром `token` в адресе, как в примере документации к
# prices_for_dates, — ровно так, как работает ссылка в браузере. Заголовок
# X-Access-Token документация тоже допускает, но при отказе по нему
# причина не видна; один путь проверяется одной командой curl.
SESSION.headers.update({
    "Accept-Encoding": "gzip, deflate",    # рекомендация API — экономит время ответа
})


# ------------------------------------------------------------------ инфраструктура
def ensure_env():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(LOG):
        with open(LOG, "w", encoding="utf-8") as f:
            f.write("timestamp,origin,destination,month,status,rows\n")
    if not TOKEN:
        sys.exit("Не задан токен: export TP_TOKEN=...")
    # Проба ключа до сбора: один дешёвый запрос. Отказ здесь — одна
    # строка с причиной, а не шестьдесят строк http_401 в журнале.
    probe = SESSION.get(API_URL, params={"origin": "MOW", "destination": "LED",
                                         "currency": CURRENCY, "limit": 1,
                                         "token": TOKEN}, timeout=30)
    if probe.status_code in (401, 403):
        sys.exit(f"агрегатор не принял ключ (http {probe.status_code}): в TP_TOKEN "
                 f"{len(TOKEN)} символов. Проверьте той же ссылкой в браузере: "
                 f"{API_URL}?origin=MOW&destination=LED&limit=1&token=<ключ>")
    if probe.status_code != 200:
        sys.exit(f"агрегатор ответил http {probe.status_code} на пробный запрос — "
                 f"сбор не начат")
    print(f"ключ принят ({len(TOKEN)} символов), валюта {CURRENCY.upper()}")


def read_routes(path):
    """Читает сеть формата 'Направление | Кол-во рейсов | Дистанция, км'."""
    df = pd.read_excel(path)
    col = df.columns[0]
    routes = []
    for _, row in df.iterrows():
        raw = str(row[col])
        if "-" not in raw:
            continue
        o, d = [x.strip().upper() for x in raw.split("-", 1)]
        if len(o) == 3 and len(d) == 3:
            routes.append({
                "origin": o, "destination": d,
                "flights_per_year": row.get("Кол-во рейсов"),
                "distance_km": row.get("Дистанция, км"),
            })
    print(f"Маршрутов в сети: {len(routes)}")
    return routes


def months_ahead(n):
    today = datetime.now()
    return [(today + relativedelta(months=i + 1)).strftime("%Y-%m") for i in range(n)]


def done_set():
    """Что уже собрано СЕГОДНЯ — возобновление прерванного прогона.

    Раньше множество не знало о дате: пара-месяц, собранная однажды,
    пропускалась навсегда, и повторный запуск через неделю не приносил ни
    одного наблюдения. А цена — временной ряд по глубине бронирования:
    тот же вылет, увиденный неделей позже, это другое наблюдение, ради
    которого сбор и повторяют.
    """
    df = pd.read_csv(LOG)
    today = datetime.now().strftime("%Y-%m-%d")
    return {(r.origin, r.destination, str(r.month)) for r in df.itertuples()
            if r.status == "success" and str(r.timestamp)[:10] == today}


def log_row(o, d, month, status, rows):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{o},{d},{month},{status},{rows}\n")


# ------------------------------------------------------------------ лимиты API
def respect_limits(resp):
    """Поминутные лимиты (с 14.06.2024): ждём ровно X-Rate-Limit-Reset секунд."""
    try:
        remaining = int(resp.headers.get("X-Rate-Limit-Remaining", 1))
        reset = float(resp.headers.get("X-Rate-Limit-Reset", 0))
    except (TypeError, ValueError):
        remaining, reset = 1, 0
    if resp.status_code == 429 or remaining <= 0:
        wait = max(reset, 5)
        print(f"  лимит минуты исчерпан — пауза {wait:.0f} с")
        time.sleep(wait)
        return True                        # запрос стоит повторить
    if remaining <= 3 and reset:
        time.sleep(min(reset, 10))         # мягкое торможение у края лимита
    return False


# ------------------------------------------------------------------ сбор
def fetch_month(origin, destination, month):
    """Все кэшированные предложения по маршруту за месяц (с пагинацией)."""
    rows, page = [], 1
    while True:
        params = {
            "origin": origin, "destination": destination,
            "departure_at": month,          # YYYY-MM: весь месяц одним запросом
            "one_way": "true", "unique": "false", "direct": "false",
            "currency": CURRENCY, "sorting": "price",
            "limit": PAGE_LIMIT, "page": page,
            "token": TOKEN,
        }
        for attempt in range(4):
            try:
                resp = SESSION.get(API_URL, params=params, timeout=60)
            except requests.RequestException as e:
                print(f"  сеть: {e}; повтор через 10 с")
                time.sleep(10)
                continue
            if respect_limits(resp):
                continue                    # 429 → подождали → повторяем страницу
            break
        else:
            return rows, "network_fail"

        if resp.status_code != 200:
            return rows, f"http_{resp.status_code}"
        payload = resp.json()
        if not payload.get("success"):
            return rows, f"api_error:{payload.get('error')}"
        chunk = payload.get("data") or []
        # Валюта — из ответа, если API её называет, иначе из запроса. Ответ
        # главнее: если агрегатор однажды проигнорирует параметр, в файле
        # окажется то, в чём цены на самом деле, а не то, что мы просили.
        cur = str(payload.get("currency") or CURRENCY).upper()
        for x in chunk:
            x["currency"] = cur
        rows.extend(chunk)
        if len(chunk) < PAGE_LIMIT:
            return rows, "success"
        page += 1


def cmd_collect(args):
    ensure_env()
    routes = read_routes(args.routes)
    months = months_ahead(args.months)
    done = done_set()
    buffer, chunk_no, req = [], 1, 0
    statuses: dict[str, int] = {}
    rows_total = 0

    for r in routes:
        o, d = r["origin"], r["destination"]
        for m in months:
            if (o, d, m) in done:
                continue
            req += 1
            print(f"[{req}] {o}-{d} {m}")
            offers, status = fetch_month(o, d, m)
            for x in offers:
                x["origin_req"], x["destination_req"], x["month"] = o, d, m
                x["collected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            buffer.extend(offers)
            log_row(o, d, m, status, len(offers))
            statuses[status] = statuses.get(status, 0) + 1
            rows_total += len(offers)
            if status in ("http_401", "http_403"):
                # Ключ не принят: дальше каждый запрос даст тот же отказ.
                # Шестьдесят строк «http_401» в журнале и «Сбор завершён»
                # на экране — тот самый тихий отказ (решение 37).
                sys.exit(f"агрегатор не принял ключ ({status}) на первом же "
                         f"запросе — сбор остановлен. Проверьте TP_TOKEN: "
                         f"длина {len(TOKEN)} символов (ключ Travelpayouts — 32), "
                         f"кавычки внутри: {'да' if any(c in TOKEN for c in chr(34) + chr(39)) else 'нет'}")
            time.sleep(0.3)                 # базовый темп; остальное решают заголовки
            if len(buffer) >= 20000:
                pd.DataFrame(buffer).to_csv(
                    os.path.join(OUT, f"raw_{RUN}_{chunk_no:03d}.csv"), index=False)
                print(f"  чанк {chunk_no}: {len(buffer)} строк")
                buffer, chunk_no = [], chunk_no + 1
    if buffer:
        # Хвост писался как raw_001.csv — без метки запуска, в отличие от
        # промежуточных чанков, — и каждый следующий сбор затирал
        # предыдущий. Накопление не происходило вовсе.
        pd.DataFrame(buffer).to_csv(
            os.path.join(OUT, f"raw_{RUN}_{chunk_no:03d}.csv"), index=False)
    print("Запросы: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())))
    if not rows_total:
        # Файл пишется только при непустом буфере. Без этой строки «Сбор
        # завершён» с указанием файлов звучал как успех, а файлов не было.
        sys.exit("ни одной строки — файл выгрузки не записан. Причины по "
                 "запросам — в flight_data/processed.log")
    print(f"Сбор завершён: {rows_total} строк в flight_data/raw_{RUN}_*.csv. "
          f"Дальше: скопировать их в data/raw/market_fare/ и fca fare, "
          f"затем fca fare --aggregate")


# ------------------------------------------------------------------ агрегация
def cmd_aggregate(args):
    files = sorted(glob.glob(os.path.join(OUT, "raw_*.csv")))
    if not files:
        sys.exit("Нет сырых данных — сначала collect.")
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    df = df.drop_duplicates(subset=["origin_req", "destination_req",
                                    "departure_at", "flight_number", "price"])
    df["dep_date"] = pd.to_datetime(df["departure_at"], errors="coerce",
                                    utc=True).dt.date
    df["route"] = df["origin_req"] + "-" + df["destination_req"]
    df["is_direct"] = df.get("transfers", 0).fillna(0).astype(int).eq(0)
    print(f"Всего предложений после дедупликации: {len(df)}")

    def day_minima(frame, suffix):
        """Свёртка в дневные минимумы и распределение по маршруту."""
        day = (frame.groupby(["route", "dep_date"])
                    .agg(min_price=("price", "min"),
                         offers=("price", "size"))
                    .reset_index())
        stats = (day.groupby("route")
                   .agg(**{f"days_{suffix}": ("dep_date", "nunique"),
                           f"min_{suffix}": ("min_price", "min"),
                           f"p25_{suffix}": ("min_price", lambda s: s.quantile(.25)),
                           f"median_{suffix}": ("min_price", "median"),
                           f"p75_{suffix}": ("min_price", lambda s: s.quantile(.75)),
                           f"max_{suffix}": ("min_price", "max")})
                   .round(0).reset_index())
        return day, stats

    # ДВЕ ветки на единой методике дневных минимумов:
    # all — все предложения (справочно); direct — только прямые (для экономики рейса)
    day_all, route_all = day_minima(df, "all")
    day_dir, route_dir = day_minima(df[df["is_direct"]], "direct")
    day_dir.to_csv(os.path.join(OUT, "prices_by_day.csv"), index=False)

    route = route_dir.merge(route_all, on="route", how="outer")
    route["no_direct_service"] = route["days_direct"].isna()

    # обогащение сетью: частоты и дистанция → цена за километр в валюте
    # сбора. Колонка называлась `rub_per_km_direct` при ценах в евро — имя
    # переживает комментарий рядом с ним (решение 115).
    net = read_routes(args.routes)
    net_df = pd.DataFrame(net)
    net_df["route"] = net_df["origin"] + "-" + net_df["destination"]
    route = route.merge(net_df[["route", "flights_per_year", "distance_km"]],
                        on="route", how="left")
    curs = sorted(df["currency"].dropna().str.upper().unique()) if "currency" in df else []
    if len(curs) > 1:
        sys.exit(f"в выгрузках смешаны валюты {curs}: медиана рублей и евро не значит "
                 f"ничего — собирать сводку по одной валюте")
    cur = (curs[0] if curs else CURRENCY.upper()).lower()
    if not curs:
        print(f"  ! в старых выгрузках нет колонки currency — принята валюта "
              f"запроса {CURRENCY.upper()}")
    route[f"{cur}_per_km_direct"] = (route["median_direct"] / route["distance_km"]).round(2)
    route.sort_values("median_direct", ascending=False) \
         .to_csv(os.path.join(OUT, "prices_by_route.csv"), index=False)
    print("Готово: prices_by_route.csv, prices_by_day.csv")
    print(route.head(15).to_string(index=False))


# ------------------------------------------------------------------ main
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Цены по маршрутной сети (Aviasales Data API)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect");  c.add_argument("--routes", required=True); \
        c.add_argument("--months", type=int, default=12); c.set_defaults(func=cmd_collect)
    a = sub.add_parser("aggregate"); a.add_argument("--routes", required=True); \
        a.set_defaults(func=cmd_aggregate)
    args = p.parse_args()
    args.func(args)
