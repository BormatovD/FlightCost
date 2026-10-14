"""DGCA (Индия): пассажиропоток по парам городов — домен `traffic` (M10).

Источник — статистика DGCA, собранная в CSV проектом
github.com/Vonter/india-aviation-traffic (ODbL 1.0, с указанием DGCA):

* `aggregated/domestic/city.csv` — регулярные внутренние рейсы, по месяцам:
  `Year, Month, City1, City2, PaxToCity2, PaxFromCity2, …`;
* `aggregated/international/city.csv` — международные, по КВАРТАЛАМ
  (таблица 4 квартального отчёта DGCA): `Year` двумя цифрами, `Quarter`.

Что делается со строкой:

1. Оба направления складываются: `PaxToCity2 + PaxFromCity2` — пара туда
   и обратно, как у Eurostat и T-100. Одна пара за месяц иногда стоит
   двумя строками (A–B и B–A) — они тоже складываются: это разные
   строки отчёта, а не одно число дважды.
2. Город переводится в аэропорт по `config/dgca_cities.yaml` (ИАТА или
   ИКАО, с периодами действия названия). Города с несколькими аэропортами
   (Лондон, Москва, Дубай) отнесены к главному — и это написано в подписи
   факта. Непереведённые названия не теряются молча: их список и поток
   за ними — в сводке разбора.
3. Квартал хранится кварталом (`"Q1"` в ряду), а не размазывается по
   месяцам: делить его на три — значит выдумать сезонность. Читатель
   берёт треть квартала как средний месяц и пишет это.

Отчётчик один — `DGCA`. Внутренние и международные пары не пересекаются
(у международной один конец за рубежом), поэтому одного имени хватает.
"""

from __future__ import annotations

import csv
import io
import pathlib

import yaml

from ..store import Fact  # noqa: F401  (факты строит traffic.pack)

WHO = "parser:dgca@1"
REPORTER = "DGCA"
KEEP_MONTHS = 36
CITIES = pathlib.Path(__file__).resolve().parents[2] / "config" / "dgca_cities.yaml"


def load_cities(path=CITIES) -> dict:
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}


def resolve(name: str, period: str, cities: dict, to_icao: dict,
            scope: str = "domestic") -> tuple[str | None, str]:
    """(ИКАО | None, пометка). Пометка — «город» или причина отказа."""
    spec = cities.get(name)
    if spec is None:
        spec = cities.get(name.upper())
    if spec is None:
        return None, "нет в перечне"
    specs = spec if isinstance(spec, list) else [spec]
    for s in specs:
        if isinstance(s, str):
            s = {"iata": s}
        until = s.get("until")
        if until and period > str(until):
            continue
        if s.get("scope") and s["scope"] != scope:
            continue
        if "skip" in s:
            return None, s["skip"]
        icao = s.get("icao") or to_icao.get(str(s.get("iata") or "").upper())
        if not icao:
            return None, f"нет ИКАО для {s.get('iata')}"
        return icao, "город" if s.get("city") else ""
    return None, "период названия не покрыт перечнем"


def parse(blob: bytes, ctx: dict) -> list:
    from ..traffic import pack
    text = blob.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text))
    cols = set(rd.fieldnames or [])
    need = {"Year", "City1", "City2", "PaxToCity2", "PaxFromCity2"}
    if not need <= cols or not ({"Month", "Quarter"} & cols):
        raise ValueError(f"не похоже на выгрузку DGCA по парам городов: колонки {sorted(cols)}")
    quarterly = "Quarter" in cols
    rows = list(rd)
    store = ctx.get("store")
    to_icao = store.icao_of_iata(ctx.get("today")) if store is not None else {}
    cities = ctx.get("cities") or load_cities()

    def period(r):
        y = int(r["Year"])
        y = y + 2000 if y < 100 else y
        return (f"{y:04d}-Q{int(r['Quarter'])}" if quarterly else f"{y:04d}-{int(r['Month']):02d}")

    pers = [period(r) for r in rows]
    if not pers:
        raise ValueError("файл пуст")
    last = max(pers)
    ly = int(last[:4])
    lm = (int(last[6]) * 3) if quarterly else int(last[5:])
    since_n = ly * 12 + lm - KEEP_MONTHS
    since = f"{since_n // 12:04d}-{since_n % 12 + 1:02d}"

    agg: dict[tuple, list] = {}
    city_of: dict[tuple, set] = {}
    miss: dict[str, float] = {}
    why: dict[str, str] = {}
    for r, per in zip(rows, pers):
        mon_cmp = per if not quarterly else f"{per[:4]}-{int(per[6]) * 3:02d}"
        if mon_cmp < since:
            continue
        try:
            pax = float(r["PaxToCity2"] or 0) + float(r["PaxFromCity2"] or 0)
        except ValueError:
            continue
        if not pax:
            continue
        c1, c2 = r["City1"].strip(), r["City2"].strip()
        ref = per[:7] if not quarterly else f"{per[:4]}-{int(per[6]) * 3:02d}"
        sc = "international" if quarterly else "domestic"
        i1, n1 = resolve(c1, ref, cities, to_icao, sc)
        i2, n2 = resolve(c2, ref, cities, to_icao, sc)
        if not i1 or not i2:
            for c, i, n in ((c1, i1, n1), (c2, i2, n2)):
                if not i:
                    miss[c] = miss.get(c, 0.0) + pax
                    why[c] = n
            continue
        if i1 == i2:
            continue
        a, b = sorted((i1, i2))
        key = (REPORTER, a, b, per)
        agg.setdefault(key, [0.0, None, None])[0] += pax
        cities_here = {c for c, n in ((c1, n1), (c2, n2)) if n == "город"}
        if cities_here:
            city_of.setdefault((a, b), set()).update(cities_here)

    if not agg:
        raise ValueError("ни одной пары с переводимыми городами; без перевода: "
                         + ", ".join(sorted(miss)[:10]))
    kind = "международные, по кварталам" if quarterly else "внутренние регулярные, по месяцам"

    def note(rep, a, b):
        base = f"DGCA ({kind}): пассажиры, оба направления"
        c = city_of.get((a, b))
        return base + (f"; город, а не аэропорт: {', '.join(sorted(c))} отнесён к главному "
                       f"аэропорту" if c else "")

    facts = pack(agg, ctx=ctx, who=WHO, note=note)
    ctx.setdefault("parsed_prefixes", []).append(REPORTER)
    lost = sum(miss.values())
    total = lost + sum(v[0] for v in agg.values())
    head = sorted(miss, key=miss.get, reverse=True)[:8]
    ctx["summary"] = list(ctx.get("summary", []))
    ctx["summary"].insert(0,
        f"{kind}: пар {len({(a, b) for _, a, b, _ in agg})}, периодов с {since} по {last}"
        + (f"; без перевода {len(miss)} названий, {lost / total * 100:.1f}% пассажиров: "
           + ", ".join(f"{c} ({why[c]})" for c in head) if miss else ""))
    return facts
