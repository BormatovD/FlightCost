"""Check route-rating examples and the lookup used by /api/network-hints."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from flightcostapp.serve import network_pair_hints  # noqa: E402

read = lambda rel: json.loads((ROOT / rel).read_text(encoding="utf-8"))
fixture = read("research/routes-2026-11/verify/network_hint_examples.json")
rating = read("research/routes-2026-11/out/rating.json")
airports = read("research/routes-2026-11/out/airports.json")
iata = {row[5].upper(): icao for icao, row in airports.items() if len(row) > 5 and row[5]}
airport_rows = [
    {"icao": icao, "key": row[5], "iso": row[2], "lat": row[0], "lon": row[1]}
    for icao, row in airports.items() if len(row) > 5 and row[5]
]
india_rows = rating["india"]["pairs"]
city_to_icao = {}
for row in india_rows:
    for city, code in zip((row["a"], row["b"]), row["icao"]):
        if code:
            city_to_icao[city.casefold()] = code


def endpoint(token):
    t = token.strip()
    upper = t.upper()
    if upper in airports:
        return upper
    if upper in iata:
        return iata[upper]
    if t.casefold() in city_to_icao:
        return city_to_icao[t.casefold()]
    raise AssertionError(f"unknown airport/city alias: {token}")


def find(market, first, second):
    a, b = endpoint(first), endpoint(second)
    rows = rating[market]["pairs"] + rating[market].get("long_haul", [])
    if market == "europe":
        key = "-".join(sorted((a, b)))
        return next((r for r in rows if r["pair"] == key), None), key
    if market == "india":
        return next((r for r in rows if sorted(x for x in (r.get("icao") or []) if x) == sorted((a, b))), None), "-".join(sorted((a, b)))
    raise AssertionError(f"unknown market: {market}")


def app_hint(first, second, current_rating=rating):
    return network_pair_hints(current_rating, airport_rows, [first, second])[0]


for case in fixture["cases"]:
    market = case["market"]
    if case["result"] is None:
        assert case["hint_ru"]
    else:
        result = case["result"]
        actual_market = rating[market]
        assert actual_market["last_month"] == case["period"]["source_last_month"]
        assert result["rank_of"] == len(actual_market["pairs"])
        assert case["hint_ru"]
    for query in case["expected_searches"]:
        if market is None:
            hint = app_hint(query["from"], query["to"])
            assert not hint["found"] and hint["market"] is None and hint["period"] is None
            continue
        actual, canonical = find(market, query["from"], query["to"])
        assert canonical == case["normalized_pair"], (case["id"], canonical)
        assert (actual is not None) is query["found"], (case["id"], query, actual)
        hint = app_hint(query["from"], query["to"])
        if not query["found"]:
            assert not hint["found"] and hint["market"] is None and hint["period"] is None
            continue
        result = case["result"]
        assert actual["rank"] == result["rank"]
        assert actual["pax"] == result["market_pax"]
        assert actual["index"] == result["index"]
        assert actual["pct"] == result["percentiles"]
        if market == "europe":
            assert actual["growth"] == result["growth_2024_vs_2023"]
            assert actual["lf"] == result["load_factor"]
            bucket_name = "europe_long_haul" if actual in rating["europe"]["long_haul"] else "europe_short_haul"
            assert hint["market"] == bucket_name
            assert hint["period"] == "2024-12"
        else:
            assert actual["growth"] == result["growth_latest_12m_vs_previous_12m"]
            assert actual["growth25"] == result["growth_2025_vs_2024_matched_months"]
            assert "lf" not in actual and hint["load_factor"] is None
            assert hint["market"] == "india"
            assert hint["period"] == "2026-07"
        assert hint["rank"] == actual["rank"]
        assert hint["pax"] == actual["pax"]
        assert hint["slot3"] == actual.get("slot3", [])
        assert hint["load_factor"] == actual.get("lf")

# The long-haul denominator is its own published rating list, not the short-haul one.
long_row = rating["europe"]["long_haul"][0]
long_hint = app_hint(long_row["a"], long_row["b"])
assert long_hint["market"] == "europe_long_haul"
assert long_hint["rank_of"] == len(rating["europe"]["long_haul"])

# The denominator follows a changed rating snapshot; no copied rating table is cached.
modified = copy.deepcopy(rating)
modified["europe"]["pairs"].append({"pair": "XXXX-YYYY", "rank": len(modified["europe"]["pairs"]) + 1})
changed = app_hint("FRA", "BCN", modified)
assert changed["rank"] == 599 and changed["rank_of"] == len(rating["europe"]["pairs"]) + 1

# Adding/removing airports refreshes the exact unordered pair set.
assert len(network_pair_hints(rating, airport_rows, ["EDDF", "LEBL", "VIDP", "VABB"])) == 6
assert len(network_pair_hints(rating, airport_rows, ["EDDF", "LEBL", "VIDP"])) == 3
assert len(network_pair_hints(rating, airport_rows, ["EDDF", "LEBL"])) == 1
assert app_hint("FRA", "BCN")["slot3"] == ["EDDF", "LEBL"]
assert app_hint("DEL", "BOM")["slot3"] == ["VIDP", "VABB"]
print(f"OK: {sum(len(c['expected_searches']) for c in fixture['cases'])} lookups; aliases, reverse directions, exact buckets, periods, rank, LF, slots, missing pairs, changed rating, and add/remove checked")
