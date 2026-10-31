"""Рейтинг привлекательных маршрутов FlightCostApp — Европа (Eurostat, 2024) и Индия (DGCA, последние 12 месяцев).

Опоры — процентили внутри своего рынка (100 — лучший):
- Европа: размер рынка (пассажиры 2024), рост (2024 к 2023), недопредложение (загрузка кресел 2024: пассажиры ÷ кресла);
- Индия: размер рынка (пассажиры за последние 12 месяцев), рост за год (12 мес. к предыдущим 12), рост 2025 к 2024 по
  месяцам, которые есть в обоих годах (в ряду DGCA нет мая 2024). (2023 не берём: в нём у Гоа два названия одного аэропорта — ряд DGCA задвоен).
Индекс — среднее опор. Ограничения (координируемый аэропорт уровня 3 на одном из концов) — флажком, не в индексе:
список уровней неполный (out/r2.json), и штрафовать только тех, про кого известно, было бы нечестно.
В рейтинг — пары от 200 тыс. пассажиров в год (Европа) и от 150 тыс. (Индия): меньше — не рынок для узкофюзеляжного.

    python3 research/routes-2026-11/rating.py   → out/rating.json
"""
import csv, json, math, pathlib, statistics

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
J = lambda f: json.loads((HERE / f).read_text(encoding="utf-8"))  # noqa: E731
EU_MIN, IN_MIN = 200_000, 150_000
LONG_KM = 4500        # дальше — уже не узкофюзеляжный A320/737: отдельная таблица
# Индия: город → ИКАО главного аэропорта (для расстояния и флажка слотов)
IN_ICAO = {"Delhi": "VIDP", "Mumbai": "VABB", "Bengaluru": "VOBL", "Hyderabad": "VOHS", "Chennai": "VOMM",
           "Kolkata": "VECC", "Ahmedabad": "VAAH", "Pune": "VAPO", "Goa": "VOGO", "Kochi": "VOCI", "Jaipur": "VIJP",
           "Lucknow": "VILK", "Guwahati": "VEGT", "Patna": "VEPT", "Srinagar": "VISR", "Bhubaneswar": "VEBS",
           "Chandigarh": "VICG", "Varanasi": "VEBN", "Indore": "VAID", "Nagpur": "VANP", "Trivandrum": "VOTV",
           "Thiruvananthapuram": "VOTV", "Coimbatore": "VOCB", "Calicut": "VOCL", "Kozhikode": "VOCL",
           "Bagdogra": "VEBD", "Visakhapatnam": "VOVZ", "Vishakhapatnam": "VOVZ", "Amritsar": "VIAR",
           "Ranchi": "VERC", "Raipur": "VERP", "Mangalore": "VOML", "Madurai": "VOMD", "Port Blair": "VOPB",
           "Udaipur": "VAUD", "Dehradun": "VIDN", "Jammu": "VIJU", "Leh": "VILH", "Vadodara": "VABO", "Surat": "VASU",
           "Imphal": "VEIM", "Tiruchirappalli": "VOTR", "Bhopal": "VABP", "Agartala": "VEAT", "Rajkot": "VAHS",
           "Dibrugarh": "VEMN", "Tirupati": "VOTP", "Vijayawada": "VOBZ", "Dabolim": "VOGO", "Jodhpur": "VIJO",
           "Prayagraj": "VEAB", "Allahabad": "VEAB", "Hubli": "VOHB", "Aurangabad": "VAAU", "Gorakhpur": "VEGK",
           "Silchar": "VEKU", "Darbhanga": "VEDH", "Jabalpur": "VAJB", "Belgaum": "VOBM", "Gaya": "VEGY",
           "Shirdi": "VASD", "Kannur": "VOKN", "Port blair": "VOPB", "Dimapur": "VEMR", "Deoghar": "VEDO"}
SLOT3 = {s["icao"] for s in J("out/r2.json")["slots"] if str(s["level"]).startswith("3") and len(s["icao"]) == 4}
SLOT3 |= {"LFPG", "LFPO", "LFMN"}          # COHOR: по меню сайта, без цитаты — помечено в статье


def airports():
    """Координаты и названия — OurAirports (общественное достояние), снимок из справочника калькулятора:
    out/airports.json (только аэропорты пар рейтинга)."""
    return {k: (v[0], v[1], v[3], v[2]) for k, v in J("out/airports.json").items()}


def km(a, b):
    (la1, lo1), (la2, lo2) = (math.radians(a[0]), math.radians(a[1])), (math.radians(b[0]), math.radians(b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def pct(vals, x):
    s = sorted(vals)
    return round((sum(1 for v in s if v < x) + (sum(1 for v in s if v == x) - 1) / 2) / (len(s) - 1) * 100, 1)


def rank(rows, metrics):
    for m in metrics:
        vals = [r[m] for r in rows if r.get(m) is not None]
        for r in rows:
            r.setdefault("pct", {})[m] = pct(vals, r[m]) if r.get(m) is not None else None
    for r in rows:
        have = [v for v in r["pct"].values() if v is not None]
        r["index"] = round(statistics.mean(have), 1)
    rows.sort(key=lambda r: -r["index"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def main():
    ap = airports()
    eu = J("out/pairs_eu.json")
    rows = []
    for k, v in eu["pairs"].items():
        y4, y3 = v.get("2024"), v.get("2023")
        if not y4 or y4["pax"] < EU_MIN:
            continue
        a, b = k.split("-")
        r = {"pair": k, "a": a, "b": b, "pax": y4["pax"],
             "growth": (y4["pax"] / y3["pax"] - 1) if y3 and y3["pax"] else None,
             "lf": (y4["pax"] / y4["seats"]) if y4.get("seats") else None,
             "pax_per_flight": (y4["pax"] / y4["flights"]) if y4.get("flights") else None,
             "reporters": y4["reporters"], "slot3": [x for x in (a, b) if x in SLOT3]}
        if a in ap and b in ap:
            r["km"] = round(km(ap[a][:2], ap[b][:2]))
            r["names"] = [ap[a][2], ap[b][2]]
            r["countries"] = [ap[a][3], ap[b][3]]
        if r.get("lf") and r["lf"] > 1.0:
            r["lf"] = None                                    # кресла не опубликованы целиком
        rows.append(r)
    for r in rows:
        r["size"] = math.log(r["pax"])
    short = [r for r in rows if r.get("km") is not None and r["km"] <= LONG_KM]
    long_ = [r for r in rows if r.get("km") is not None and r["km"] > LONG_KM]
    eu_r = rank(short, ["size", "growth", "lf"])
    eu_l = rank(long_, ["size", "growth", "lf"])
    ind = J("out/pairs_in.json")
    rows = []
    for k, v in ind["pairs"].items():
        if v["l12"] < IN_MIN:
            continue
        a, b = k.split("-")
        r = {"pair": k, "a": a, "b": b, "pax": v["l12"],
             "growth": (v["l12"] / v["p12"] - 1) if v["p12"] else None,
             "growth25": (v["g25"][1] / v["g25"][0] - 1) if v["g25"][0] else None,
             "icao": [IN_ICAO.get(a), IN_ICAO.get(b)]}
        r["slot3"] = [x for x in r["icao"] if x in SLOT3]
        if all(x and x in ap for x in r["icao"]):
            r["km"] = round(km(ap[r["icao"][0]][:2], ap[r["icao"][1]][:2]))
        r["size"] = math.log(r["pax"])
        rows.append(r)
    in_r = rank(rows, ["size", "growth", "growth25"])
    out = {"europe": {"source": eu["source"], "last_month": eu["last_month"], "min_pax": EU_MIN, "pairs": eu_r,
                      "long_haul": eu_l},
           "india": {"source": ind["source"], "last_month": ind["last_month"], "min_pax": IN_MIN, "pairs": in_r}}
    (HERE / "out" / "rating.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    for reg, rr in (("EU", eu_r), ("IN", in_r)):
        print(reg, len(rr))
        for r in rr[:15]:
            print(f"  {r['rank']:3} {r['pair']:22} {r['index']:5} pax {r['pax']:>9,} g {r.get('growth') or 0:+.2f} "
                  f"lf {r.get('lf') or 0:.2f} km {r.get('km')} slot {r['slot3']} {r.get('names') or ''}")


if __name__ == "__main__":
    main()
