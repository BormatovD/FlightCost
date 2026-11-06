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
со страницы BTS со списком месяцев.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
import zipfile
from array import array
from collections import defaultdict
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
GROUPS = ("21AP", "2290", "91UP")
NEED = ("ORIGIN", "DEST", "MKTCOUPONS", "PASSENGERS", "MKTAMOUNT", "VYIELD", "PURCHASEWINDOWGROUP")


def links() -> dict[str, str]:
    req = urllib.request.Request(INDEX, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8", errors="replace")
    out = {}
    for m in LINK.finditer(html):
        ym = m.group(1)
        out[f"{ym[:4]}-{ym[4:]}"] = m.group(0)
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
    rd = csv.reader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline=""))
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
        raise ValueError(f"в файле DB1C нет колонок: {', '.join(miss)}")
    ix = {c: head.index(c) for c in NEED}
    direct: dict = defaultdict(lambda: array("f"))
    grp: dict = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    allm: dict = defaultdict(lambda: [0, 0.0])
    rows = skipped = 0

    def take(r):
        nonlocal rows, skipped
        rows += 1
        try:
            if r[ix["VYIELD"]].strip() != "1":
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

    if pending is not None:
        take(pending)
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
        a = allm[pair]
        out[pair] = {"direct": st, "all": {"pax": a[0], "mean": round(a[1] / a[0], 2)}}
    return {"month": month, "sample_rate": SAMPLE_RATE, "min_pax": min_pax, "rows": rows,
            "skipped": skipped, "pairs": out}


def fold_zip(path: Path, month: str) -> Path:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith((".csv", ".txt", ".dat")) or "." not in n)
        with z.open(name) as fh:
            doc = aggregate(fh, month)
    doc["file"] = path.name
    AGG.mkdir(parents=True, exist_ok=True)
    out = AGG / f"DB1C-{month}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"{month}: строк {doc['rows']:,}, отброшено {doc['skipped']:,}, пар {len(doc['pairs'])} → {out.name}"
          .replace(",", " "))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-zip", action="store_true", help="не удалять архивы после свёртки")
    ap.add_argument("--file", help="свернуть свой архив вместо скачивания")
    ap.add_argument("--month", help="месяц для --file, ГГГГ-ММ (иначе из имени файла)")
    a = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    if a.file:
        p = Path(a.file)
        m = a.month or (lambda g: f"{g[:4]}-{g[4:]}")(re.search(r"\.(\d{6})\.", p.name).group(1))
        fold_zip(p, m)
        return 0
    have = {f.stem.replace("DB1C-", "") for f in AGG.glob("DB1C-*.json")}
    todo = {m: u for m, u in sorted(links().items()) if m not in have}
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
