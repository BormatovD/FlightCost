"""Симулятор сети без базы: права, небо, дальность, линейность, пороги.

Ядро подменено линейной моделью с известными коэффициентами — так
проверяется сама сеть: восстанавливает ли она постоянную часть и добавку
на пассажира, сходятся ли пороги, режут ли пары права и закрытия. Права
читаются из настоящего `data/rights/closures.yaml`: тест заодно ловит
поломанный файл данных.
"""

from __future__ import annotations

import math
import re
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from flightcostapp import network as N
from flightcostapp.rights import load_closures, pair_rights

ROOT = Path(__file__).resolve().parents[1]

AP = {  # код: (lat, lon, ИКАО, страна)
    "FRA": (50.0333, 8.5706, "EDDF", "DE"),
    "BCN": (41.2971, 2.0785, "LEBL", "ES"),
    "DME": (55.4088, 37.9063, "UUDD", "RU"),
    "OVB": (55.0126, 82.6507, "UNNT", "RU"),
    "ALA": (43.3521, 77.0405, "UAAA", "KZ"),
    "DEL": (28.5562, 77.1000, "VIDP", "IN"),
}
ICAO = {v[2]: k for k, v in AP.items()}


def airport_fn(store, code, as_of):
    lat, lon, icao, iso = AP[code]
    return {"lat": lat, "lon": lon, "icao": icao, "country": iso, "name": code}


def gc_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    return 3440.065 * math.acos(min(1, math.sin(p1) * math.sin(p2)
                                    + math.cos(p1) * math.cos(p2) * math.cos(dl)))


@dataclass
class Cross:
    zones: dict


def crossing_fn(la1, lo1, la2, lo2, nm):
    """Зоны по концам; Алматы–Барселона идёт через Украину (как в жизни)."""
    a = next(v for v in AP.values() if (v[0], v[1]) == (la1, lo1))
    b = next(v for v in AP.values() if (v[0], v[1]) == (la2, lo2))
    z = {a[2][:2]: nm / 2, b[2][:2]: nm / 2}
    if {a[2], b[2]} == {"UAAA", "LEBL"}:
        z["UK"] = 300.0
    return Cross(z)


@dataclass
class Step:
    node: str
    value: float
    prov: str


@dataclass
class Res:
    aircraft: str
    block_h: float
    fuel_kg: float
    cost: dict
    inputs: dict
    max_pax: int
    feasible: bool
    warnings: list = field(default_factory=list)
    trace: list = field(default_factory=list)

    @property
    def cost_total(self):
        return sum(self.cost.values())


SEATS = 220
FIX_PER_KM, FIX0, PER_PAX = 2.5, 3000.0, 12.0
FUEL_PRICE = 0.8


def fake_core(store, o, d, *, load_factor, util_mode, aircraft, via=None, **kw):
    pts = [AP[o][:2]] + [tuple(w) for w in (via or [])] + [AP[d][:2]]
    km = sum(gc_nm(*p, *q) for p, q in zip(pts, pts[1:])) * 1.852
    pax = load_factor * SEATS
    fuel = 3.0 * km + 2.0 * pax
    cost = {"fuel": fuel * FUEL_PRICE,
            "other": FIX0 + FIX_PER_KM * km + PER_PAX * pax,
            "distribution": 999.0}            # сеть обязана её выбросить
    cap = SEATS if km < 6000 else max(0, int(SEATS * (1 - (km - 6000) / 1500)))
    return Res(aircraft, km / 800 + 0.5, fuel, cost,
               {"seats": SEATS, "pax": pax}, cap, pax <= cap,
               warnings=[f"нет тарифа для {AP[d][2]}"],
               trace=[Step("d_fleet", 400_000.0, "default"),
                      Step("v_util", 330.0, "default")])


class FakeStore:
    def __init__(self, fares=None, freq=None):
        self.fares, self.freq = fares or {}, freq or {}

    def get(self, domain, key, as_of=None):
        if domain == "market_fare" and key in self.fares:
            v, cur = self.fares[key]
            return {"value": v, "currency": cur, "value_text": '{"n_days": 40}'}
        return None

    def current(self, domain, as_of=None):
        return {f"frequency/{k}": {"value": v} for k, v in self.freq.items()} \
            if domain == "observed" else {}


UA_RING = [(52.3, 23.6), (51.9, 31.8), (52.4, 33.4), (50.4, 36.5), (49.9, 40.1), (47.1, 38.2),
           (45.3, 36.6), (44.4, 33.8), (46.1, 30.2), (48.4, 22.1), (49.6, 22.6), (51.5, 23.6)]
WORLD = {"UKBV": {"prefix": "UK", "rings": [UA_RING]}}


def form(store=None, airports=("FRA", "BCN", "DME", "OVB", "ALA", "DEL"), base="ALA",
         world_zones=WORLD, **kw):
    return N.form_network(store or FakeStore(), airports, base=base, aircraft="A21N",
                          as_of="2026-10-07", econ=fake_core, crossing_fn=crossing_fn,
                          airport_fn=airport_fn, gc_nm=gc_nm, world_zones=world_zones, **kw)


def all_fares(eur=150.0):
    return {f"{AP[x][2]}-{AP[y][2]}/d15_30/direct": (eur, "EUR")
            for x in AP for y in AP if x != y}


class Rights(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cl = load_closures()

    def test_data_file_loads_and_expands_groups(self):
        ids = {c.id for c in self.cl}
        self.assertIn("eu-ban-ru-carriers", ids)
        eu = next(c for c in self.cl if c.id == "eu-ban-ru-carriers")
        self.assertIn("DE", eu.countries)
        self.assertIn("ED", eu.zones)

    def test_freedoms(self):
        kz = lambda a, b: pair_rights("KZ", a, b, "2026-10-07", self.cl)
        self.assertTrue(kz("KZ", "DE").ok)
        self.assertEqual(kz("RU", "RU").reasons[0]["kind"], "cabotage")
        self.assertEqual(kz("DE", "ES").reasons[0]["kind"], "seventh_freedom")

    def test_common_market(self):
        self.assertTrue(pair_rights("DE", "ES", "FR", "2026-10-07", self.cl).ok)

    def test_closures_by_carrier_and_date(self):
        ru = pair_rights("RU", "RU", "DE", "2026-10-07", self.cl)
        self.assertIn("eu-ban-ru-carriers", [r.get("id") for r in ru.reasons])
        self.assertTrue(pair_rights("RU", "RU", "DE", "2021-01-01", self.cl).ok,
                        "закрытие обязано действовать только со своей даты")
        self.assertFalse(pair_rights("DE", "DE", "RU", "2026-10-07", self.cl).ok)


class Formation(unittest.TestCase):

    def test_training_set_from_almaty(self):
        st = {p.key: p.status for p in form(FakeStore(all_fares()))}
        got = {k: v for k, v in st.items() if "ALA" in k}
        self.assertEqual(got["FRA-ALA"], "ok")
        self.assertEqual(got["BCN-ALA"], "ok", "путь через Украину — с обходом")
        self.assertEqual(got["DME-ALA"], "ok")
        self.assertEqual(got["OVB-ALA"], "ok")
        self.assertEqual(got["ALA-DEL"], "ok")
        self.assertEqual(st["DME-OVB"], "rights")
        self.assertEqual(st["FRA-BCN"], "rights")

    def test_closed_sky_gets_a_detour_and_longer_legs(self):
        pairs = {p.key: p for p in form(FakeStore(all_fares()))}
        p = pairs["BCN-ALA"]
        self.assertTrue(p.via, "точки обхода")
        self.assertGreater(p.detour_km, 0)
        self.assertEqual(p.reasons[0]["kind"], "detour")
        straight = pairs["DME-ALA"]
        # плечо с обходом длиннее прямой: ядро получило via
        direct_km = gc_nm(*AP["BCN"][:2], *AP["ALA"][:2]) * 1.852
        self.assertGreater(p.legs[0].block_h, direct_km / 800 + 0.5)
        # обратное плечо идёт теми же точками в обратном порядке
        self.assertAlmostEqual(p.legs[0].block_h, p.legs[1].block_h, places=6)

    def test_no_world_file_means_no_detour_and_a_named_reason(self):
        pairs = {p.key: p for p in form(FakeStore(all_fares()), world_zones={})}
        p = pairs["BCN-ALA"]
        self.assertEqual(p.status, "airspace")
        self.assertIn("zones_world.json", p.reasons[-1]["text"])

    def test_range_cuts_long_pairs(self):
        # Перевозчик ЕС из Барселоны: BCN–DEL 6 774 км поднимает меньше половины
        st = {p.key: p for p in form(FakeStore(all_fares()), base="BCN")}
        self.assertEqual(st["BCN-DEL"].status, "range")
        self.assertIn("поднимет", st["BCN-DEL"].reasons[0]["text"])

    def test_linear_parts_recovered(self):
        p = next(x for x in form(FakeStore(all_fares())) if x.key == "DME-ALA")
        leg = p.legs[0]
        km = p.dist_km
        self.assertAlmostEqual(leg.per_pax_eur, PER_PAX + 2.0 * FUEL_PRICE, places=6)
        self.assertAlmostEqual(leg.fixed_eur, FIX0 + FIX_PER_KM * km + 3.0 * km * FUEL_PRICE,
                               delta=1e-6 * leg.fixed_eur)
        self.assertAlmostEqual(leg.fuel_price, FUEL_PRICE, places=9)
        self.assertFalse(any("нелинейна" in w for w in leg.warnings))

    def test_non_eur_fare_is_refused_not_relabelled(self):
        fares = {"UUDD-UAAA/d15_30/direct": (9000.0, "RUB")}
        p = next(x for x in form(FakeStore(fares)) if x.key == "DME-ALA")
        self.assertIsNone(p.legs[0].fare_eur)
        self.assertIn("RUB", p.legs[0].fare_src)

    def test_market_estimate_from_observed_frequency(self):
        freq = {"UUDD-UAAA/2026-09-01": 14, "UAAA-UUDD/2026-09-14": 14}  # окно 14 сут
        p = next(x for x in form(FakeStore(all_fares(), freq)) if x.key == "DME-ALA")
        self.assertAlmostEqual(p.legs[0].comp_week, 7.0)
        self.assertAlmostEqual(p.market_pax_month,
                               14.0 * N.WEEKS_PER_MONTH * N.MARKET_SEATS * N.MARKET_LF)
        self.assertTrue(p.market_src.startswith("оценка"))


class Simulation(unittest.TestCase):

    def setUp(self):
        freq = {f"{AP[x][2]}-{AP[y][2]}/2026-09-01": 21
                for x in AP for y in AP if x != y}
        freq.update({f"{AP[x][2]}-{AP[y][2]}/2026-09-21": 21
                     for x in AP for y in AP if x != y})
        self.pairs = form(FakeStore(all_fares(260.0), freq))
        self.fleet = N.Fleet("A21N", 400_000.0, "default", 330.0, "default")

    def sim(self, **kw):
        kw.setdefault("fleet_n", 4)
        return N.simulate(self.pairs, fleet=self.fleet, **kw)

    def flown(self, net):
        f = {r.key: r.freq_week for r in net.pairs}
        return [(p, f[p.key]) for p in self.pairs if p.key in f]

    def test_breakeven_lf_zeroes_profit(self):
        net = self.sim()
        self.assertIsNotNone(net.breakeven_lf)
        pr = N._profit(self.flown(net), 4, net.lease_eur_month, net.breakeven_lf, 1.0)
        self.assertAlmostEqual(pr, 0.0, delta=1.0)

    def test_thresholds_are_consistent(self):
        net = self.sim()
        again = self.sim(lease_eur_month=net.lease_breakeven)
        self.assertAlmostEqual(again.profit_at_ref, 0.0, delta=1.0)
        pr = N._profit(self.flown(net), 4, net.lease_eur_month, net.lf_ref,
                       net.fare_mult_breakeven)
        self.assertAlmostEqual(pr, 0.0, delta=1.0)
        pr = N._profit(self.flown(net), 4, net.lease_eur_month, net.lf_ref, 1.0,
                       dfuel=net.fuel_price_breakeven - net.fuel_price_now)
        self.assertAlmostEqual(pr, 0.0, delta=1.0)

    def test_auto_frequency_fits_fleet_hours(self):
        net = self.sim()
        self.assertLessEqual(net.hours_used, 4 * 330.0 + 1e-6)
        self.assertTrue(any("поровну" in w for w in net.warnings))

    def test_overbooked_schedule_is_said(self):
        net = self.sim(freq={"FRA-ALA": 30, "DME-ALA": 30}, fleet_n=1)
        self.assertTrue(any("не выполнить" in w for w in net.warnings))

    def test_fleet_cannot_cover_one_flight(self):
        with self.assertRaises(ValueError):
            self.sim(fleet_n=1, util_h_month=10)

    def test_s_curve_degenerates_to_frequency_share(self):
        net = self.sim(alpha=1.0)
        for r in net.pairs:
            self.assertAlmostEqual(r.s_share, r.freq_share, places=12)

    def test_need_share_is_pax_over_market(self):
        net = self.sim()
        for r in net.pairs:
            self.assertAlmostEqual(r.need_share, r.pax_month / r.market_pax_month)

    def test_unpriced_pair_leaves_with_reason(self):
        fares = all_fares(260.0)
        fares.pop("UNNT-UAAA/d15_30/direct")
        pairs = form(FakeStore(fares))
        net = N.simulate(pairs, fleet=self.fleet, fleet_n=4)
        ex = {p.key: p for p in net.excluded}
        self.assertIn("OVB-ALA", ex)
        self.assertEqual(ex["OVB-ALA"].reasons[-1]["kind"], "no_fare")

    def test_pair_economics_without_lease_allocation(self):
        """Решение 159: у пары — загрузка, при которой она окупает свои
        рейсы, и вклад в парк; сеть в нуле, когда сумма вкладов равна
        лизингу парка. Лизинг по парам не делится."""
        net = self.sim(freq={"FRA-ALA": 3, "DME-ALA": 7, "OVB-ALA": 7, "ALA-DEL": 7})
        lfs = [r.lf_own for r in net.pairs if r.lf_own is not None]
        self.assertEqual(len(lfs), len(net.pairs))
        # ниже самой лёгкой пары все вклады отрицательны — лизинг не покрыть
        self.assertLessEqual(min(lfs) - 1e-9, net.breakeven_lf)
        total = sum(r.contribution_month for r in net.pairs)
        self.assertAlmostEqual(total - 4 * net.lease_eur_month, net.profit_at_ref, delta=1.0)
        # вклад пары при её собственной нулевой загрузке равен нулю
        f = {r.key: r.freq_week for r in net.pairs}
        for r in net.pairs:
            p = next(x for x in self.pairs if x.key == r.key)
            self.assertAlmostEqual(N._profit([(p, f[r.key])], 0, 0.0, r.lf_own, 1.0), 0.0, delta=1.0)

    def test_report_renders(self):
        net = self.sim()
        txt = N.report(net, self.pairs, base="ALA")
        for must in ("СЕТЬ", "НЕ В СЕТИ", "С ОБХОДОМ", "BCN-ALA", "безубыточная загрузка", "рейсы в 0",
                     "ОГОВОРКИ СЕТИ", "ОГОВОРКИ ЯДРА"):
            self.assertIn(must, txt)


class Invariants(unittest.TestCase):

    def test_distribution_rate_matches_core(self):
        """Вторая запись доли дистрибуции объявлена (решение 102) и
        сверяется с ядром: разойтись молча они не должны."""
        src = (ROOT / "flightcostapp" / "econ.py").read_text(encoding="utf-8")
        m = re.search(r"dist_rate\s*=\s*([0-9.]+)", src)
        self.assertIsNotNone(m, "в econ.py не нашлась dist_rate")
        self.assertAlmostEqual(float(m.group(1)), N.DIST_RATE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
