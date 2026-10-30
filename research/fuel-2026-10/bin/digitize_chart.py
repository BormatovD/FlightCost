"""Оцифровка графика «Jet Fuel Price Development (Global and Regional)» со страницы IATA Jet Fuel
Price Monitor (данные S&P Global Platts), $/баррель, по неделям.

Данные — собственность Platts: ни ряд, ни картинка в репозиторий и в статьи не кладутся. Наружу
выходит только соотношение спота регионов к Северной Америке за последние недели — в
data/fuel/_platts.local.json (в .gitignore), его читает калькулятор (решение 236).

    python3 research/fuel-2026-10/bin/digitize_chart.py <картинка.jpg> --end 2026-10-23 --global 196.70 \\
        [--raw <вне репозитория>/raw.json] [--local data/fuel/_platts.local.json]

--end     — дата последней недели на графике (неделя, к которой относится текст страницы);
--global  — «global average jet fuel price … to $X/bbl» из текста той же страницы: по нему
            калибруется масштаб (верх последнего столбика = X), так что смена шкалы графика
            не ломает оцифровку. Без него — шкала скриншота от 30.10.2026 (0 → y=1027, 50 $ = 178,2 px).
Проверка 30.10.2026: неделя 25.09 — 186,0 против 185,43 у FuelOS (IATA/Platts).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics

from PIL import Image

REGS = ("asia", "europe", "middle_east", "latam", "africa")
CL = {
    "asia": lambda r, g, b: r > 170 and b > 140 and g < 130,
    "europe": lambda r, g, b: g > r + 40 and g > b + 30,
    "north_america": lambda r, g, b: r > 200 and g > 160 and b < 150,
    "latam": lambda r, g, b: r > 170 and g < 120 and b < 120,
    "africa": lambda r, g, b: b > 170 and r < 90 and g < 110,
}


def digitize(path: str, global_last: float | None = None) -> list[dict]:
    im = Image.open(path).convert("RGB")
    W, H = im.size
    dark = lambda x, y: sum(im.getpixel((x, y))) < 260  # noqa: E731
    # низ столбиков — нулевая линия: самая нижняя строка, где тёмное продолжается вверх на 40 px
    # (столбики), а не текст подписей и легенды
    counts = {y: sum(1 for x in range(0, W, 2) if dark(x, y) and dark(x, y - 40)) for y in range(H // 2, H)}
    top_c = max(counts.values())
    y_base = max(y for y, c in counts.items() if c >= 0.8 * top_c) + 1
    y_scan = y_base - 15
    cols = [x for x in range(W) if sum(im.getpixel((x, y_scan))) < 200]
    bars, s, p = [], None, None
    for x in cols:
        if s is None:
            s = x
        elif x != p + 1:
            bars.append((s + p) // 2)
            s = x
        p = x
    bars.append((s + p) // 2)

    def top_of(cx):
        for yy in range(int(H * 0.09), y_base):
            if all(dark(cx, yy + k) for k in range(12)):
                return yy
        return None

    y0, k = (1027, 3.564)
    if global_last:
        t = top_of(bars[-1])
        y0, k = y_base, (y_base - t) / global_last
    v = lambda y: (y0 - y) / k  # noqa: E731

    def pick(x, test):
        ys = [yy for xx in (x - 1, x, x + 1) for yy in range(int(H * 0.09), y_base) if test(*im.getpixel((xx, yy)))]
        return v(statistics.median(ys)) if ys else None

    out = []
    for i, cx in enumerate(bars):
        top = top_of(cx)
        row = {"i": i, "global": round(v(top), 1) if top else None}
        for name, t in CL.items():
            val = pick(cx, t)
            row[name] = round(val, 1) if val else None
        me = []   # Ближний Восток — чёрная линия: между столбиками, где её не закрывает столбик;
        # искать только рядом с уровнем столбика (±150 px), иначе попадают заголовок и подписи
        lo_y, hi_y = (max(0, top - 150), min(y_base - 10, top + 150)) if top else (int(H * 0.1), y_base - 10)
        for mx in (cx - 15, cx + 15):
            if 0 < mx < W:
                ys = [yy for yy in range(lo_y, hi_y) if sum(im.getpixel((mx, yy))) < 200]
                if ys:
                    me.append(v(statistics.median(ys)))
        row["middle_east"] = round(statistics.mean(me), 1) if me else None
        out.append(row)
    return out


def ratios(rows, end_date: str, weeks: int = 3) -> dict:
    """Соотношение спота регионов к Северной Америке: среднее за последние `weeks` недель
    (оцифровка шумит на ±2–3 $/баррель) и по каждой неделе (для привязки множителей к дате)."""
    end = dt.date.fromisoformat(end_date)
    last = rows[-1]["i"]
    weekly = []
    for x in rows:
        d = end - dt.timedelta(days=7 * (last - x["i"]))
        na = x.get("north_america")
        weekly.append({"date": str(d), **{k: round(x[k] / na, 4) for k in REGS if x.get(k) and na}})
    now = {k: round(statistics.mean(w[k] for w in weekly[-weeks:] if k in w), 4) for k in REGS}
    return {"as_of": str(end), "ratio_to_north_america": now, "weekly": weekly}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--end", required=True)
    ap.add_argument("--global", dest="glob", type=float)
    ap.add_argument("--raw")
    ap.add_argument("--local", default=str(pathlib.Path(__file__).resolve().parents[3] / "data/fuel/_platts.local.json"))
    a = ap.parse_args()
    rows = digitize(a.image, a.glob)
    if a.raw:
        json.dump(rows, open(a.raw, "w"), indent=0)
    out = ratios(rows, a.end)
    out["source"] = (f"оцифровка графика IATA Jet Fuel Price Monitor (данные S&P Global Platts), неделя до {a.end}; "
                     "не публикуется")
    pathlib.Path(a.local).write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(len(rows), "недель; последняя мировая", rows[-1]["global"], "; к Северной Америке:", out["ratio_to_north_america"])


if __name__ == "__main__":
    main()
