#!/usr/bin/env python3
"""Самые массовые маршруты Индии, Европы и Африки — файлы для сбора цен.

Откуда ранжирование. Опубликованный пассажиропоток пар из домена `traffic`:
DGCA (Индия, внутренние и международные), Eurostat avia_par (ЕС/ЕАСТ с
партнёрами за пределами Европы — отсюда Европа–Африка и Европа–Индия),
BTS T-100. Поток пары — среднее за последние 12 опубликованных месяцев
(`traffic.published`), годовой = × 12. Чего в опубликованной статистике нет
вовсе — внутриафриканских линий, — берётся из списка `tools/routes_africa_core.yaml`
(крупные линии по расписаниям), с пометкой «без опубликованного потока» и в
конце своей группы.

Группы и квоты по умолчанию (пар, обе стороны — две строки файла):
  india   — пара с концом в Индии: внутренние 70, международные 30;
  europe  — оба конца в Европе (с Турцией): 130;
  africa  — конец в Африке, без Индии: 70, из них до 25 — из списка без потока.

    python3 tools/top_routes.py --db data/flightcost.db --out-dir .
    python3 tools/top_routes.py --india-dom 50 --india-intl 20 --europe 100 --africa 50

Выход: routes-india.xlsx, routes-europe.xlsx, routes-africa.xlsx и routes-300.xlsx
(всё вместе) в формате tools/collect_prices.py: «Направление | Кол-во рейсов |
Дистанция, км», плюс справочные столбцы «Пасс./год», «Источник потока», «Группа».
Сбор цен лучше вести по группам с рынком своей группы:
    python3 tools/collect_prices.py collect --routes routes-india.xlsx  --market in
    python3 tools/collect_prices.py collect --routes routes-europe.xlsx --market de
    python3 tools/collect_prices.py collect --routes routes-africa.xlsx --market de
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.econ import great_circle_nm  # noqa: E402
from flightcostapp.store import Store           # noqa: E402

EUROPE = set("AL AD AT BA BE BG CH CY CZ DE DK EE ES FI FO FR GB GG GI GR HR HU IE IM IS IT JE LI LT LU LV MC MD ME "
             "MK MT NL NO PL PT RO RS SE SI SK SM TR XK".split())
AFRICA = set("DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU "
             "MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW RE YT EH".split())


def _geo(st) -> dict[str, tuple[float, float, str]]:
    out = {}
    for txt, in st.db.execute("SELECT value_text FROM facts WHERE domain='airport' AND valid_to IS NULL"):
        p = (txt or "").split("|", 3)
        if len(p) < 4 or not p[1]:
            continue
        try:
            lat, lon = (float(x) for x in p[0].split(",", 1))
        except ValueError:
            continue
        out[p[1]] = (lat, lon, p[2])
    return out


def _pairs(st) -> set[tuple[str, str]]:
    out = set()
    for k, in st.db.execute("SELECT DISTINCT key FROM facts WHERE domain='traffic' AND valid_to IS NULL"):
        parts = (k or "").split("/")
        if len(parts) == 3 and "-" in parts[1]:
            a, b = parts[1].split("-", 1)
            if len(a) == 4 and len(b) == 4:
                out.add(tuple(sorted((a, b))))
    return out


def group_of(iso_a: str, iso_b: str) -> str | None:
    if "IN" in (iso_a, iso_b):
        return "india-dom" if iso_a == iso_b == "IN" else "india-intl"
    if iso_a in AFRICA or iso_b in AFRICA:
        return "africa"
    if iso_a in EUROPE and iso_b in EUROPE:
        return "europe"
    return None


def build(st, quotas: dict[str, int], africa_core: int, core_file: pathlib.Path) -> list[dict]:
    from flightcostapp import traffic
    geo, iata = _geo(st), st.iata_of(None)
    ranked: dict[str, list[dict]] = {}
    for a, b in _pairs(st):
        if a not in geo or b not in geo or a not in iata or b not in iata:
            continue
        g = group_of(geo[a][2], geo[b][2])
        if not g:
            continue
        pub = traffic.published(st, a, b)
        if not pub or not pub.get("pax_month"):
            continue
        ranked.setdefault(g, []).append({"a": a, "b": b, "pax_year": pub["pax_month"] * 12,
                                         "src": pub.get("src", "").split(":")[0], "group": g})
    out = []
    for g, n in quotas.items():
        rows = sorted(ranked.get(g, []), key=lambda r: -r["pax_year"])
        if g == "africa":
            rows = rows[:max(0, n - africa_core)]
            have = {(r["a"], r["b"]) for r in rows}
            core = []
            if core_file.exists():
                import yaml
                for p in yaml.safe_load(core_file.read_text(encoding="utf-8")).get("pairs", []):
                    a, b = sorted(str(p).upper().replace(" ", "").split("-"))
                    if (a, b) not in have and a in geo and b in geo and a in iata and b in iata:
                        core.append({"a": a, "b": b, "pax_year": None,
                                     "src": "без опубликованного потока — список по расписаниям", "group": g})
            rows = rows + core[:n - len(rows)]
        else:
            rows = rows[:n]
        out += rows
    for r in out:
        (la, lo, _), (lb, lob, _) = geo[r["a"]], geo[r["b"]]
        r["km"] = round(great_circle_nm(la, lo, lb, lob) * 1.852)
        r["A"], r["B"] = iata[r["a"]], iata[r["b"]]
    return out


def write(rows: list[dict], path: pathlib.Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Маршруты"
    ws.append(["Направление", "Кол-во рейсов", "Дистанция, км", "Пасс./год (оба направления)",
               "Источник потока", "Группа", "ИКАО"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        for o, d in ((r["A"], r["B"]), (r["B"], r["A"])):
            ws.append([f"{o}-{d}", None, r["km"], round(r["pax_year"]) if r["pax_year"] else None,
                       r["src"], r["group"], f"{r['a']}-{r['b']}"])
    for col, w in zip("ABCDEFG", (12, 14, 14, 26, 46, 12, 12)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    wb.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=str(ROOT / "data" / "flightcost.db"))
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--india-dom", type=int, default=70)
    ap.add_argument("--india-intl", type=int, default=30)
    ap.add_argument("--europe", type=int, default=130)
    ap.add_argument("--africa", type=int, default=70)
    ap.add_argument("--africa-core", type=int, default=25, help="сколько пар Африки взять из списка без потока")
    a = ap.parse_args(argv)
    st = Store(a.db)
    q = {"india-dom": a.india_dom, "india-intl": a.india_intl, "europe": a.europe, "africa": a.africa}
    rows = build(st, q, a.africa_core, ROOT / "tools" / "routes_africa_core.yaml")
    out = pathlib.Path(a.out_dir)
    for name, groups in (("india", ("india-dom", "india-intl")), ("europe", ("europe",)), ("africa", ("africa",))):
        part = [r for r in rows if r["group"] in groups]
        write(part, out / f"routes-{name}.xlsx")
        print(f"routes-{name}.xlsx: пар {len(part)} (строк {2 * len(part)})"
              + ("" if part else " — опубликованного потока нет: загружен ли источник?"))
    write(rows, out / "routes-300.xlsx")
    print(f"routes-300.xlsx: пар {len(rows)}")
    short = {g: q[g] - sum(1 for r in rows if r["group"] == g) for g in q}
    for g, n in short.items():
        if n > 0:
            print(f"  {g}: не добрано {n} — в домене traffic нет столько пар этой группы")


if __name__ == "__main__":
    main()
