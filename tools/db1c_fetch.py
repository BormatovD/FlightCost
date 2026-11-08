#!/usr/bin/env python3
"""BTS DB1C Market: скачать помесячные файлы и свернуть их по парам — у себя.

Запуск на КОМПЬЮТЕРЕ владельца (не на сервере):

    python tools/db1c_fetch.py              # скачать недостающие месяцы и свернуть
    python tools/db1c_fetch.py --keep-zip   # не удалять архивы после свёртки
    python tools/db1c_fetch.py --file путь/DB1C.MARKET.202607.15OCT2026.zip   # свернуть свой файл

Потом обычным путём:

    fca refresh --only db1c_market          # свёртки -> домен fare_paid
    fca master send --only db1c_market      # агрегаты -> на сервер, в очередь приёмки

Почему так. Лицензия DB1C прямо не заявлена (исследование 13, verify/p2):
до проверки сырые строки не уходят ни на сервер, ни в репозиторий —
решение владельца 06.11.2026. Месячный архив — сотни мегабайт, строка —
пассажир; в базу едут только агрегаты по паре и месяцу.

Где лежит: data/raw/db1c/ (архивы, временно) и data/raw/db1c/agg/ (свёртки).
data/raw в .gitignore; tools/check_hygiene.py проверяет это перед push.

Адреса архивов не угадываются (в имени дата публикации), поэтому берутся
со страницы BTS со списком месяцев. Страница bts.gov закрыта защитой от
ботов (403 для программ, 07.11.2026) — обходить её не будем. Тогда адреса
берутся из списка KNOWN ниже (сами архивы лежат в открытом хранилище и
скачиваются), а новые месяцы — из сохранённой в браузере страницы:

    python tools/db1c_fetch.py --page ~/Downloads/db1c.html
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import itertools
import json
import re
import sys
import urllib.request
import zipfile
from array import array
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "db1c"
AGG = RAW / "agg"
INDEX = "https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data-market"
LINK = re.compile(r'https://[^"\'\s>]+/DB1C\.MARKET\.(\d{6})\.[A-Z0-9]+\.zip', re.I)
UA = "flightcostapp/0.1 (+https://flightcost.app)"
SAMPLE_RATE = 0.40
# Пара попадает в свёртку, если за месяц в выборке не меньше стольких
# пассажиров на прямых рейсах: ~10 в день по выборке 40 % — рынок, у которого
# есть смысл считать квантили. Меньше — среднее и квантили шумят.
MIN_PAX = 300
# Бонусные билеты. Тариф рынка в DB1C — сумма по билету с налогами, и билет
# за мили стоит ровно государственные сборы: сбор безопасности 5,60 USD за
# посадку (08.11.2026: 13 тыс. пар-месяцев из 40 тыс. с p10 в 5–10 USD,
# на JFK–LAX p10 = 5,61–5,87). Платный билет не бывает дешевле суммы сборов —
# 7,5 % акциза, 5,30 сегментного сбора, 5,60 безопасности и до 4,50
# аэропортового — то есть ~16 USD при нулевой базе. Между ними в данных
# провал: 10–15 USD у 148 пар-месяцев против 13 294 у 5–10. Граница — по
# этому механизму, а не по «выбросам». DOT в Consumer Airfare Report бонусные
# билеты тоже не берёт. Бонусные считаются отдельно: их доля — тоже знание.
AWARD_MAX = 15.0
LOW_BINS = (0, 5, 10, 15, 20, 25, 30)
GROUPS = ("21AP", "2290", "91UP")
NEED = ("ORIGIN", "DEST", "MKTCOUPONS", "PASSENGERS", "MKTAMOUNT", "PURCHASEWINDOWGROUP")
# Признак действительной доходности. В описании DB1C Market — VYield, в
# выгрузках 2025–2026 она называется V_YIELD (08.11.2026). Ищем по
# похожим именам; не нашли — работаем без него и пишем это в свёртку.
PEEK_ROWS = 200_000
FLAG_VALID = {"1", "1.0", "1.00", "Y", "y", "T", "t", "TRUE", "true", "True"}
FLAG_VALUES = FLAG_VALID | {"0", "0.0", "0.00", "N", "n", "F", "f", "FALSE", "false", "False", ""}
VYIELD_NAMES = ("V_YIELD", "VYIELD", "VALIDYIELD", "YIELDVALID", "VALID_YIELD", "YIELD_VALID", "VALIDYIELDIND")


# Опубликованные на 06.11.2026 (страница BTS, исследование 13). Новые месяцы —
# через --page или прямо со страницы, если она откроется программе.
_BLOB = "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/"
KNOWN = {m: _BLOB + f for m, f in {
    "2025-07": "DB1C.MARKET.202507.18SEP2026.zip", "2025-08": "DB1C.MARKET.202508.21SEP2026.zip",
    "2025-09": "DB1C.MARKET.202509.21SEP2026.zip", "2025-10": "DB1C.MARKET.202510.21SEP2026.zip",
    "2025-11": "DB1C.MARKET.202511.22SEP2026.zip", "2025-12": "DB1C.MARKET.202512.22SEP2026.zip",
    "2026-01": "DB1C.MARKET.202601.01JUN2026.zip", "2026-02": "DB1C.MARKET.202602.02JUN2026.zip",
    "2026-03": "DB1C.MARKET.202603.02JUL2026.zip", "2026-04": "DB1C.MARKET.202604.15JUL2026.zip",
    "2026-05": "DB1C.MARKET.202605.20AUG2026.zip", "2026-06": "DB1C.MARKET.202606.16SEP2026.zip",
    "2026-07": "DB1C.MARKET.202607.15OCT2026.zip"}.items()}


def links(page: str | None = None) -> dict[str, str]:
    """Месяц -> адрес архива. Сохранённая страница (--page) главнее; иначе
    страница BTS; закрыта (403 защиты от ботов) — известный список KNOWN."""
    out = dict(KNOWN)
    if page:
        html = Path(page).expanduser().read_text("utf-8", errors="replace")
    else:
        try:
            req = urllib.request.Request(INDEX, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                html = r.read().decode("utf-8", errors="replace")
        except OSError as e:
            print(f"страница BTS не открылась ({e}) — беру известный список месяцев; новые месяцы: "
                  "сохраните страницу в браузере и передайте --page файл.html")
            return out
    found = 0
    for m in LINK.finditer(html):
        ym = m.group(1)
        out[f"{ym[:4]}-{ym[4:]}"] = m.group(0)
        found += 1
    if page and not found:
        raise SystemExit(f"в {page} нет ссылок на DB1C.MARKET.*.zip — сохранена не та страница?")
    return out


def _quantile(xs: list, q: float) -> float:
    i = q * (len(xs) - 1)
    lo = int(i)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def aggregate(fh, month: str, min_pax: int = MIN_PAX) -> dict:
    """Поток CSV рынков DB1C -> свёртка по паре (без направления, коды по
    алфавиту). Заголовок узнаётся по именам колонок; без заголовка —
    порядок полей из описания DB1C Market."""
    text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
    line = text.readline()
    # Разделитель — по первой строке: в описании запятая, но выгрузки BTS
    # бывали и через «|» и табуляцию.
    delim = max((",", "|", "\t", ";"), key=line.count)
    rd = csv.reader(itertools.chain([line], text), delimiter=delim)
    first = next(rd)
    up = [c.strip().upper() for c in first]
    if "MKTAMOUNT" in up:
        head, pending = up, None
    else:
        head = ["ITINID", "MKTID", "GATEID", "MKTCOUPONS", "RPYEAR", "RPQUARTER", "RPMONTH", "SCHFLYR",
                "SCHFLQUARTER", "SCHFLMO", "ORIGINAIRPORTID", "ORIGINAIRPORTSEQID", "ORIGINCITYMARKETID",
                "ORIGIN", "ORIGINCOUNTRY", "ORIGINSTATEFIPS", "ORIGINSTATE", "ORIGINSTATENAME", "ORIGINWAC",
                "DESTAIRPORTID", "DESTAIRPORTSEQID", "DESTCITYMARKETID", "DEST", "DESTCOUNTRY", "DESTSTATE",
                "DESTSTATENAME", "DESTWAC", "AIRPORTGROUP", "WACGROUP", "DWELLTIMEGROUP", "SEGMENTVIAGROUP",
                "RPCARRIERAIRLINEID", "RPCARRIER", "ISSUINGCARRIERAIRLINEID", "ISSUINGCARRIER",
                "MARKETINGCARRIERAIRLINEID", "MKTCARRIER", "MKTCARRIERGROUP", "MKTCARRIERCHANGE",
                "OPERATINGCARRIERAIRLINEID", "OPCARRIER", "OPCARRIERGROUP", "OPCARRIERCHANGE", "PASSENGERS",
                "MKTAMOUNT", "MKTTAX", "VYIELD", "PURCHASEWINDOWGROUP", "TOTALDISTANCE", "MILESTRAVELED",
                "NONSTOPMILES", "MKTGEOTYPE", "ITINGEOTYPE", "BREAK_LEGACYLOGIC"]
        pending = first
    miss = [c for c in NEED if c not in head]
    if miss:
        raise ValueError(f"в файле DB1C нет колонок: {', '.join(miss)}. Первая строка файла: "
                         f"{line.strip()[:300]!r} — это точно файл MARKET, а не SEGMENT?")
    ix = {c: head.index(c) for c in NEED}
    vy = next((head.index(n) for n in VYIELD_NAMES if n in head), None)
    if vy is None:
        print("  колонки признака доходности (VYield) в файле нет — беру все строки с тарифом больше нуля.\n"
              f"  Колонки файла: {', '.join(head)}", flush=True)
    # Что лежит в колонке признака, смотрим по первым строкам, а не верим
    # описанию: 08.11.2026 при сравнении с «1» отбросились все 23 млн строк.
    # Флаг (только 0/1, Y/N…) — фильтруем по нему; иначе это не флаг, и
    # фильтра нет, а увиденные значения записываются в свёртку.
    buf = []
    vy_vals: Counter = Counter()
    if pending is not None:
        buf.append(pending)
        pending = None
    for r in itertools.islice(rd, PEEK_ROWS):
        buf.append(r)
    if vy is not None:
        vy_vals.update(r[vy].strip() for r in buf if len(r) > vy)
        seen = set(vy_vals)
        valid = sum(n for v, n in vy_vals.items() if v in FLAG_VALID)
        total = sum(vy_vals.values()) or 1
        if not seen or not seen <= FLAG_VALUES:
            vy_mode = "not_a_flag"
            vy = None
        elif valid / total < 0.5:
            # Флаг, но «действительных» почти нет: в публичных выгрузках
            # 2025–2026 V_YIELD = 0 у 99 % строк и пусто у остальных
            # (08.11.2026). Фильтр по нему выбросил бы всё — значит, смысл
            # колонки в выгрузке не тот, что в описании. Без фильтра.
            vy_mode = "flag_uninformative"
            vy = None
        else:
            vy_mode = "flag"
        top = ", ".join(f"{v!r}: {n}" for v, n in vy_vals.most_common(8))
        label = {"flag": "флаг, фильтрую", "not_a_flag": "не флаг — без фильтра",
                 "flag_uninformative": "флаг, но «действительных» меньше половины — без фильтра"}[vy_mode]
        print(f"  признак доходности: {label}; "
              f"значения в первых {len(buf):,} строках: {top}".replace(",", " ", 1), flush=True)
    else:
        vy_mode = "absent"
    direct: dict = defaultdict(lambda: array("f"))
    grp: dict = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    allm: dict = defaultdict(lambda: [0, 0.0])
    award: dict = defaultdict(lambda: [0, 0])          # пара -> [прямые, все] бонусных пассажиров
    low_hist: Counter = Counter()
    rows = skipped = 0

    def take(r):
        nonlocal rows, skipped
        rows += 1
        try:
            if vy is not None and r[vy].strip() not in FLAG_VALID:
                skipped += 1
                return
            fare = float(r[ix["MKTAMOUNT"]])
            pax = int(float(r[ix["PASSENGERS"]] or 1))
        except (ValueError, IndexError):
            skipped += 1
            return
        if fare <= 0 or pax <= 0:
            skipped += 1
            return
        a, b = sorted((r[ix["ORIGIN"]].strip().upper(), r[ix["DEST"]].strip().upper()))
        pair = f"{a}-{b}"
        if fare < LOW_BINS[-1]:
            low_hist[int(fare // 5) * 5] += pax
        if fare < AWARD_MAX:
            w = award[pair]
            w[1] += pax
            if r[ix["MKTCOUPONS"]].strip() == "1":
                w[0] += pax
            return
        s = allm[pair]
        s[0] += pax
        s[1] += fare * pax
        if r[ix["MKTCOUPONS"]].strip() != "1":
            return
        direct[pair].extend([fare] * pax)
        g = r[ix["PURCHASEWINDOWGROUP"]].strip().upper()
        if g in GROUPS:
            c = grp[pair][g]
            c[0] += pax
            c[1] += fare * pax

    for r in buf:
        take(r)
    for r in rd:
        take(r)
    out = {}
    for pair, fares in direct.items():
        n = len(fares)
        if n < min_pax:
            continue
        xs = sorted(fares)
        st = {"pax": n, "mean": round(sum(xs) / n, 2)}
        for q, name in ((0.1, "p10"), (0.25, "p25"), (0.5, "p50"), (0.75, "p75"), (0.9, "p90")):
            st[name] = round(_quantile(xs, q), 2)
        known = sum(grp[pair][g][0] for g in GROUPS)
        for g in GROUPS:
            c = grp[pair][g]
            if known:
                st[f"share_{g}"] = round(c[0] / known, 4)
            if c[0] >= 30:                         # средняя по группе — от тридцати пассажиров
                st[f"mean_{g}"] = round(c[1] / c[0], 2)
        w = award[pair]
        if w[0]:
            st["award_pax"] = w[0]
        st["share_award"] = round(w[0] / (w[0] + n), 4)
        a = allm[pair]
        out[pair] = {"direct": st, "all": {"pax": a[0], "mean": round(a[1] / a[0], 2),
                                           "share_award": round(w[1] / (w[1] + a[0]), 4)}}
    return {"month": month, "sample_rate": SAMPLE_RATE, "min_pax": min_pax, "rows": rows,
            "skipped": skipped, "vyield_filter": vy is not None, "vyield_mode": vy_mode,
            "award_max_usd": AWARD_MAX, "low_fare_hist": {f"{k}-{k + 5}": v for k, v in sorted(low_hist.items())},
            "vyield_values": dict(vy_vals.most_common(8)), "pairs": out}


def _open_table(z: zipfile.ZipFile, label: str):
    """Файл таблицы внутри архива: самый большой, не каталог. Вложенный zip
    раскрывается, .gz распаковывается на лету. Имена внутри архивов BTS
    меняются от выгрузки к выгрузке (07.11.2026: ни .csv, ни .txt), поэтому
    по расширению не выбираем, а при сбое печатаем, что внутри."""
    # Служебное macOS (__MACOSX, «._») — мимо. Если в архиве несколько
    # форматов одной таблицы (BTS кладёт .csv.zip, .asc.zip и .parquet,
    # 08.11.2026), берём CSV: его читает этот скрипт; parquet — двоичный, без
    # pyarrow его не прочитать, и он давал «строк 34 млн, отброшено 34 млн».
    files = [i for i in z.infolist() if not i.is_dir() and "__MACOSX" not in i.filename
             and not i.filename.rsplit("/", 1)[-1].startswith("._")]
    if not files:
        raise ValueError(f"{label}: архив пустой")

    def rank(i):
        n = i.filename.lower()
        r = (0 if ".csv" in n else 1 if ".asc" in n or n.endswith((".txt", ".dat")) else
             3 if n.endswith(".parquet") else 2)
        return (r, -i.file_size)
    big = min(files, key=rank)
    if big.filename.lower().endswith(".parquet"):
        raise ValueError(f"{label}: в архиве только parquet ({big.filename}) — нужен CSV-вариант того же месяца")
    print(f"  {label}: внутри {', '.join(f'{i.filename} ({i.file_size / 1e6:.0f} МБ)' for i in files[:6])}"
          f" — беру {big.filename}", flush=True)
    fh = z.open(big)
    low = big.filename.lower()
    if low.endswith(".zip"):
        inner = zipfile.ZipFile(io.BytesIO(fh.read()))
        return _open_table(inner, f"{label}/{big.filename}")
    if low.endswith(".gz"):
        return gzip.GzipFile(fileobj=fh)
    return fh


def fold_zip(path: Path, month: str) -> Path:
    with zipfile.ZipFile(path) as z:
        with _open_table(z, path.name) as fh:
            doc = aggregate(fh, month)
    doc["file"] = path.name
    if not doc["pairs"]:
        # Пустая свёртка не пишется: иначе refresh упадёт позже и непонятно где,
        # а повторный запуск решит, что месяц уже свёрнут.
        raise ValueError(f"{month}: строк {doc['rows']}, отброшено {doc['skipped']}, пар нет — "
                         "формат файла не тот; свёртка не записана")
    AGG.mkdir(parents=True, exist_ok=True)
    out = AGG / f"DB1C-{month}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    aw = sum(v["direct"].get("award_pax", 0) for v in doc["pairs"].values())
    paid = sum(v["direct"]["pax"] for v in doc["pairs"].values())
    print(f"{month}: строк {doc['rows']:,}, отброшено {doc['skipped']:,}, пар {len(doc['pairs'])}, "
          f"бонусных на прямых {aw / max(aw + paid, 1):.1%} → {out.name}".replace(",", " "))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-zip", action="store_true", help="не удалять архивы после свёртки")
    ap.add_argument("--file", help="свернуть свой архив вместо скачивания")
    ap.add_argument("--month", help="месяц для --file, ГГГГ-ММ (иначе из имени файла)")
    ap.add_argument("--page", help="сохранённая в браузере страница BTS со списком месяцев")
    a = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    if a.file:
        p = Path(a.file)
        m = a.month or (lambda g: f"{g[:4]}-{g[4:]}")(re.search(r"\.(\d{6})\.", p.name).group(1))
        fold_zip(p, m)
        return 0
    have = {f.stem.replace("DB1C-", "") for f in AGG.glob("DB1C-*.json")}
    todo = {m: u for m, u in sorted(links(a.page).items()) if m not in have}
    if not todo:
        print("все опубликованные месяцы уже свёрнуты")
        return 0
    for m, url in todo.items():
        dst = RAW / url.rsplit("/", 1)[-1]
        if not dst.exists():
            print(f"{m}: скачиваю {dst.name}…", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            tmp = dst.with_suffix(".part")
            with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.replace(dst)
        fold_zip(dst, m)
        if not a.keep_zip:
            dst.unlink()
    print("дальше: fca refresh --only db1c_market && fca master send --only db1c_market")
    return 0


if __name__ == "__main__":
    sys.exit(main())
