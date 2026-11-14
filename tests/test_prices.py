"""Цены и лизинг самолётов из публикаций: проверка черновика, приёмка, ряд (страница типа)."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

import yaml

from flightcostapp import prices as PR
from flightcostapp import seo

OBS = {"observations": [
    {"icao": "A21N", "kind": "list", "value": 129.5, "scale": "m", "currency": "USD", "month": "2018-01",
     "age": "new", "quote": "list price of $129.5 million", "source": "https://example.org/a"}],
    "searched": {"A21N": "2026-11-01"}}

# Реальный пустой черновик прогона 20261110-210302-prices-20261110.
EMPTY_DRAFT = {
    "observations": [],
    "searched": ["AT76 (ATR 72-600)", "B772 (777-200ER)", "CRJ9 (CRJ900)", "DH8D (Dash 8-400)"],
    "doubts": [
        "Проверены все 16 заданных RSS-лент, но доступные фрагменты выдачи и открытые статьи не дали "
        "проверяемых цен, ставок лизинга, оценок стоимости или цены за один борт с дословной цитатой "
        "из самой статьи. Поэтому наблюдения не включены.",
        "В выдаче по ATR встретилась формулировка о заказе 40 самолётов на $1 млрд по каталожной цене, "
        "но первичная статья не открылась (403), а делить общую сумму заказа на число бортов нельзя.",
        "В сообщении WLFC о покупке и обратном лизинге шести Dash 8-400 с Porter цена не указана; "
        "число бортов не является ценой за борт.",
    ],
}

AT76_QUOTE = ("New ATR72-600 lease rates are in the range of US$180,000 per month, although naked, "
              "almost new, unplaced aircraft from previous forward orders have been recently offered for lower rates")
CRJ9_QUOTE = ("these may now be as low as US$100-115,000 in order to ensure that stored inventory "
              "is returned to service")


class Drafts(unittest.TestCase):

    def test_check(self):
        blob = json.dumps({"observations": [
            {"icao": "a21n", "kind": "deal", "value": 58, "scale": "m", "currency": "USD", "month": "2025-06",
             "age": "new", "quote": "sold for $58m each to the lessor", "source": "https://ex.org/1"},
            {"icao": "B38M", "kind": "lease", "value": 360, "scale": "k", "currency": "USD", "month": "2025-03",
             "quote": "lease rates around $340,000 a month", "source": "https://ex.org/2"},
            {"icao": "A20N", "kind": "deal", "value": 3.1, "scale": "bn", "currency": "USD", "month": "2025-01",
             "quote": "an order for 30 A320neo worth $3.1 billion", "source": "https://ex.org/3"},
            {"icao": "A21N", "kind": "list", "value": 129.5, "scale": "m", "currency": "USD", "month": "2018-01",
             "age": "new", "quote": "list price of $129.5 million", "source": "https://example.org/a"},
            {"icao": "A320", "kind": "price", "value": 1, "month": "2025"}],
            "searched": ["A21N", "B38M"]}).encode()
        r = PR.check(blob, OBS)
        v = [x["verdict"] for x in r["rows"]]
        self.assertEqual(v, ["clean", "look", "look", "skip", "reject"])
        self.assertIn("числа нет в цитате", r["rows"][1]["reasons"])
        self.assertTrue(any("вне полосы" in x for x in r["rows"][2]["reasons"]))
        self.assertTrue(any("сумму заказа" in x for x in r["rows"][2]["reasons"]))
        self.assertEqual(r["searched"], ["A21N", "B38M"])

    def test_merge_and_due(self):
        p = Path(tempfile.mkdtemp()) / "_observations.yaml"
        p.write_text("# шапка\n" + yaml.safe_dump(OBS, allow_unicode=True), "utf-8")
        PR.merge([{"icao": "B38M", "kind": "lease", "value": 340, "scale": "k", "currency": "USD", "month": "2025-03",
                   "quote": "around $340,000 a month", "source": "https://ex.org/2", "verdict": "clean",
                   "reasons": []}], ["B38M", "A21N"], p, date(2026, 11, 10))
        d = yaml.safe_load(p.read_text("utf-8"))
        self.assertEqual(len(d["observations"]), 2)
        self.assertNotIn("verdict", d["observations"][1])
        self.assertEqual(d["searched"]["B38M"], "2026-11-10")
        self.assertEqual(PR.due(["A21N", "B38M", "A359"], {"searched": {"A21N": "2026-11-01"}}, limit=2),
                         ["B38M", "A359"])
        self.assertAlmostEqual(PR.usd({"value": 340, "scale": "k", "currency": "EUR"}, {"EUR": 0.9}), 340e3 / 0.9)

    def test_searched_normalizes_codes_without_guessing_names(self):
        values = [" at76 (ATR 72-600) ", "AT76", " b772 ", "B772 (777-200ER)",
                  "ATR 72-600", "Boeing 777-200ER", "Airbus A320neo", "A320neo", "unknown",
                  "A320 extra", "A320 (Airbus) extra", "", None, 777200, {"icao": "A320"}]
        self.assertEqual(PR.normalize_searched(values), ["AT76", "B772"])
        checked = PR.check(json.dumps({"observations": [], "searched": values}).encode(), OBS)
        self.assertEqual(checked["searched"], ["AT76", "B772"])

    def test_empty_production_draft_advances_queue_without_prices(self):
        searched = ["AT76", "B772", "CRJ9", "DH8D"]
        types = ["A20N", "A21N", "B38M", "B39M", *searched]
        doc = dict(OBS, searched={t: "2026-11-01" for t in types[:4]})
        self.assertEqual(PR.due(types, doc), searched)
        checked = PR.check(json.dumps(EMPTY_DRAFT).encode(), doc)
        self.assertEqual(checked["rows"], [])
        self.assertEqual(checked["searched"], searched)
        self.assertEqual(checked["doubts"], EMPTY_DRAFT["doubts"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_observations.yaml"
            p.write_text(yaml.safe_dump(doc, allow_unicode=True), "utf-8")
            self.assertEqual(PR.merge([], checked["searched"], p, date(2026, 11, 10)), [])
            after = PR.load(p)
            self.assertEqual(after["observations"], OBS["observations"])
            self.assertEqual({t: after["searched"][t] for t in searched},
                             {t: "2026-11-10" for t in searched})
            self.assertEqual(PR.due(types, after), types[:4])

    def test_legacy_searched_keys_keep_latest_date(self):
        doc = dict(OBS, searched={" a21n (A321neo) ": "2026-11-10", "A21N": "2026-11-01",
                                  "AT76": "2026-11-09"})
        self.assertEqual(PR.due(["A21N", "AT76"], doc, limit=1), ["AT76"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_observations.yaml"
            p.write_text(yaml.safe_dump(doc, allow_unicode=True), "utf-8")
            PR.merge([], ["a21n (A321neo)", "AT76 (ATR 72-600)", "ATR 72-600"],
                     p, date(2026, 11, 8))
            after = PR.load(p)
            self.assertEqual(after["searched"], {"A21N": "2026-11-10", "AT76": "2026-11-09"})
            self.assertEqual(after["observations"], OBS["observations"])


class MoneyRanges(unittest.TestCase):

    @staticmethod
    def observation(quote, **values):
        return {"icao": "CRJ9", "kind": "lease", "value": 100, "scale": "k", "currency": "USD",
                "month": "2022-07", "quote": quote, "source": "https://example.org/report", **values}

    def checked(self, quote, **values):
        blob = json.dumps({"observations": [self.observation(quote, **values)]}).encode()
        return PR.check(blob, doc={})["rows"][0]

    def test_rejection_marker_cannot_come_from_raw_draft(self):
        for kind, verdict in [("lease", "clean"), ("unknown", "reject")]:
            with self.subTest(kind=kind):
                row = self.checked(AT76_QUOTE, icao="AT76", value=180, kind=kind,
                                   rejection_code="money_range")
                self.assertEqual(row["verdict"], verdict)
                self.assertNotIn("rejection_code", row)
        self.assertEqual(self.checked(CRJ9_QUOTE, rejection_code="forged")["rejection_code"],
                         "money_range")

    def test_published_monetary_range_forms_are_rejected(self):
        for quote, currency in [
            (CRJ9_QUOTE, "USD"), ("US$100–115,000 per month", "USD"),
            ("USD100000–115000", "USD"), ("$100k-$115k", "USD"),
            ("100–115 thousand USD", "USD"), ("US $ 100 — 115 thousand", "USD"),
            ("$100,000 to $115,000", "USD"), ("100 000–115 000 US dollars", "USD"),
            ("USD 100\u202f000–115\u202f000", "USD"), ("US$100'000–115'000", "USD"),
            ("EUR100.000–115.000", "EUR"), ("€100,0–115,0 thousand", "EUR"),
            ("£100–115 thousand", "GBP"),
        ]:
            with self.subTest(quote=quote):
                row = self.checked(quote, currency=currency)
                self.assertEqual((row["verdict"], row.get("rejection_code")), ("reject", "money_range"))
        # Другая граница, иной масштаб записи и середина — тоже не отдельные ставки.
        for value, scale in [(115, "k"), (100000, ""), (107.5, "k")]:
            with self.subTest(value=value, scale=scale):
                self.assertEqual(self.checked(CRJ9_QUOTE, value=value, scale=scale)["rejection_code"],
                                 "money_range")

    def test_single_amount_model_age_and_years_are_not_ranges(self):
        for quote in [AT76_QUOTE, "ATR72-600 lease rate US$180,000 per month",
                      "ATR 72-600 US$180,000 per month",
                      "Aircraft aged 3–5 years lease for USD 180,000",
                      "During 2019–2022 the lease rate was US$180,000",
                      "Boeing 777-200ER and ATR 72-600: rate US$180,000"]:
            with self.subTest(quote=quote):
                self.assertEqual(self.checked(quote, value=180)["verdict"], "clean")
        self.assertEqual(self.checked("Boeing 737-800 US$48 million", value=48, scale="m",
                                      kind="value")["verdict"], "clean")

    def test_independent_amount_outside_range_stays_reviewable(self):
        for quote, value in [
            ("New aircraft US$180,000; older aircraft US$100–115,000", 180),
            ("US$100,000–115,000; a separate contract is US$100,000", 100),
            ("$100k–115k; a separate contract is 100 thousand USD", 100),
            ("$100k–115k; a separate contract is USD 0.1 million", 100),
            ("$100k–115k; a separate contract is USD 100.000,50", 100.0005),
        ]:
            with self.subTest(quote=quote):
                row = self.checked(quote, value=value)
                self.assertNotEqual(row["verdict"], "reject")
                self.assertNotIn("rejection_code", row)
        for quote in ["US$100–115k; a separate amount is EUR100,000",
                      "US$100–115k; unrelated item US$1.2.3"]:
            with self.subTest(quote=quote):
                self.assertEqual(self.checked(quote)["rejection_code"], "money_range")
        # Настоящий диапазон рядом не должен заставить модельный код
        # поглотить US$ и скрыть самостоятельную денежную сумму.
        row = self.checked("Boeing 737-800 US$48 million; older aircraft US$25–30 million",
                           value=48, scale="m", kind="value")
        self.assertEqual(row["verdict"], "clean")

    def test_production_quotes_accept_only_at76(self):
        # Две цитаты из прогона 20261111-060100-prices-20261111. Фильтр
        # приёмки точно как в master: «look» тоже принимается, значит
        # диапазону нужен именно reject, а не дополнительная оговорка.
        rows = [self.observation(AT76_QUOTE, icao="AT76", value=180, month="2019-12", age="new"),
                self.observation(CRJ9_QUOTE)]
        checked = PR.check(json.dumps({"observations": rows}).encode(), doc={})["rows"]
        self.assertEqual([r["verdict"] for r in checked], ["clean", "reject"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.yaml"
            accepted = [r for r in checked if r["verdict"] in ("clean", "look")]
            PR.merge(accepted, [], path, date(2026, 11, 11))
            self.assertEqual([r["icao"] for r in PR.load(path)["observations"]], ["AT76"])


class Intervals(unittest.TestCase):

    @staticmethod
    def observation(**values):
        return {"icao": "CRJ9", "kind": "lease", "value_low": 100, "value_high": 115,
                "scale": "k", "currency": "USD", "month": "2022-07", "age": None,
                "quote": CRJ9_QUOTE, "source": "https://example.org/report", **values}

    def checked(self, row, doc=None):
        return PR.check(json.dumps({"observations": [row]}).encode(), doc=doc or {})["rows"][0]

    def test_bounds_midpoint_and_currency_helpers(self):
        row = self.observation()
        self.assertTrue(PR.is_range(row))
        self.assertEqual(PR.bounds(row), (100, 115))
        self.assertEqual(PR.midpoint(row), 107.5)
        self.assertEqual(PR.amount_bounds(row), (100000, 115000))
        self.assertEqual(PR.usd_bounds(row), (100000, 115000))
        self.assertEqual(PR.usd(row), 107500)
        scalar = {"value": 100, "scale": "k", "currency": "USD"}
        self.assertFalse(PR.is_range(scalar))
        self.assertEqual(PR.bounds(scalar), (100, 100))
        self.assertEqual(PR.usd(scalar), 100000)
        eur = self.observation(currency="EUR")
        self.assertIsNone(PR.usd_bounds(eur))
        self.assertIsNone(PR.usd(eur))
        lo, hi = PR.usd_bounds(eur, {"EUR": 0.9})
        self.assertAlmostEqual(lo, 100000 / 0.9)
        self.assertAlmostEqual(hi, 115000 / 0.9)
        self.assertAlmostEqual(PR.usd(eur, {"EUR": 0.9}), 107500 / 0.9)

    def test_actual_quote_and_equivalent_published_bounds(self):
        for quote in [CRJ9_QUOTE, "USD100000–115000", "$100k-$115k", "100–115 thousand USD",
                      "US $100,000 to $115,000", "US$100–115.000", "100 000–115 000 USD",
                      "USD100,000–115k", "USD100k–115,000", "US$0.1–0.115 million"]:
            with self.subTest(quote=quote):
                row = self.checked(self.observation(quote=quote))
                self.assertEqual(row["verdict"], "clean", row)
                self.assertNotIn("value", row)
        full = self.observation(value_low=100000, value_high=115000, scale="")
        self.assertEqual(self.checked(full)["verdict"], "clean")
        local = self.observation(quote="EUR 100.000,50–115.000,50", currency="EUR",
                                 value_low=100.0005, value_high=115.0005)
        self.assertEqual(self.checked(local)["verdict"], "clean")

    def test_range_requires_both_endpoints_in_same_monetary_range(self):
        for changes in [dict(value_high=116), dict(value_low=101), dict(scale="m"), dict(currency="EUR"),
                        dict(quote="One lease US$100,000; a different lease US$115,000"),
                        dict(quote="ATR 72-600 US$180,000 per month", value_low=72, value_high=600),
                        dict(quote="During 2019–2022 the lease was USD180,000", value_low=2019, value_high=2022),
                        dict(quote="Aircraft aged 3–5 years lease for USD180,000", value_low=3, value_high=5)]:
            with self.subTest(changes=changes):
                row = self.checked(self.observation(**changes))
                self.assertEqual((row["verdict"], row.get("rejection_code")), ("reject", "range_evidence"))

    def test_between_and_explicit_monetary_bounds(self):
        for quote in ("between US$100,000 and US$115,000 per month",
                      "между 100 и 115 thousand USD в месяц"):
            with self.subTest(quote=quote):
                row = self.checked(self.observation(quote=quote))
                self.assertEqual(row["verdict"], "clean", row)
                scalar = self.observation(quote=quote)
                del scalar["value_low"], scalar["value_high"]
                scalar["value"] = 100
                rejected = self.checked(scalar)
                self.assertEqual((rejected["verdict"], rejected.get("rejection_code")),
                                 ("reject", "money_range"))

    def test_and_without_between_is_not_a_range(self):
        for quote in ("Lease quotes are US$100,000 and US$115,000 per month",
                      "Ставки US$100,000 и US$115,000 в месяц"):
            with self.subTest(quote=quote):
                row = self.checked(self.observation(quote=quote))
                self.assertEqual((row["verdict"], row.get("rejection_code")),
                                 ("reject", "range_evidence"))
                scalar = self.observation(quote=quote)
                del scalar["value_low"], scalar["value_high"]
                scalar["value"] = 100
                self.assertEqual(self.checked(scalar)["verdict"], "clean")

    def test_formal_errors_never_receive_evidence_marker(self):
        invalid = [dict(value=107.5), dict(value_low="100"), dict(value_low=True), dict(value_high=None),
                   dict(value_low=float("nan")), dict(value_high=float("inf")), dict(value_low=0),
                   dict(value_low=116), dict(source=[]), dict(age={})]
        rows = [self.observation(**change) for change in invalid]
        missing = self.observation()
        del missing["value_high"]
        rows.append(missing)
        for raw in rows:
            with self.subTest(raw=raw):
                row = self.checked(dict(raw, rejection_code="range_evidence"))
                self.assertEqual(row["verdict"], "reject")
                self.assertNotIn("rejection_code", row)
        for values in ({"value": False}, {"value": float("nan")}, {"value": 10 ** 400}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    PR.bounds(values)

    def test_plausibility_checks_both_bounds(self):
        for lo, hi in [(1, 100), (100, 4000)]:
            row = self.checked(self.observation(value_low=lo, value_high=hi, quote=f"US${lo}k–{hi}k"))
            self.assertEqual(row["verdict"], "look")
            self.assertTrue(any("вне полосы" in reason for reason in row["reasons"]))

    def test_quarterly_range_keeps_period_and_publication_date(self):
        row = self.observation(month="2026-Q1", published_on="2026-06-03", age="new")
        for bad in ("2026-Q0", "2026-Q5", "2026-13", "2026-00", "26"):
            self.assertEqual(self.checked(dict(row, month=bad))["verdict"], "reject")
        self.assertEqual(self.checked(dict(row, published_on="20260603"))["verdict"], "reject")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.yaml"
            with mock.patch.object(PR, "PATH", path):
                checked = self.checked(row)
                self.assertEqual(checked["verdict"], "clean")
                PR.merge([checked], [], path)
                self.assertIsNone(PR.annual_lease("CRJ9", "2026-06-02", 0))
                m = PR.annual_lease("CRJ9", "2026-06-03", 0)
                self.assertEqual((m["month"], m["low"], m["high"]), ("2026-Q1", 100000, 115000))
                self.assertEqual(m["sources"][0]["published_on"], "2026-06-03")
                self.assertEqual(PR.find_observation(m["id"])["month"], "2026-Q1")

    def test_year_precision_uses_publication_date_and_survives_acceptance(self):
        row = self.checked(self.observation(month=2026, published_on="2026-03-12", age="new"))
        self.assertEqual((row["verdict"], row["month"]), ("clean", "2026"))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(PR, "PATH", Path(tmp) / "prices.yaml"):
            PR.merge([row], [])
            self.assertIsNone(PR.annual_lease("CRJ9", "2026-03-11", 0))
            market = PR.annual_lease("CRJ9", "2026-03-12", 0)
            self.assertEqual((market["month"], market["midpoint"]), ("2026", 107500))
            self.assertEqual(market["sources"][0]["published_on"], "2026-03-12")
            self.assertIsNone(PR.annual_lease("CRJ9", "2027-01-01", 0))

    def test_merge_preserves_interval_and_aggregates_use_midpoint(self):
        row = self.checked(self.observation(age="new", month="2019-07"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.yaml"
            lines = PR.merge([row], ["CRJ9"], path=path, today=date(2026, 11, 11))
            self.assertIn("100–115", lines[0])
            saved = PR.load(path)["observations"][0]
            self.assertEqual((saved["value_low"], saved["value_high"]), (100, 115))
            self.assertNotIn("value", saved)
            self.assertNotIn("midpoint", saved)
            with mock.patch.object(PR, "PATH", path):
                self.assertEqual(PR.annual_lease("CRJ9", "2019-12-31", age=0)["midpoint"], 107500)
            self.assertAlmostEqual(PR.real_level([saved], True, (2019, 2019), 2025,
                                                 {2019: 100.0, 2024: 110.0, 2025: 120.0}), 129.0)

    def test_dedup_uses_bounds_date_age_and_normalized_units(self):
        original = self.observation()
        same = self.observation(value_low=100000, value_high=115000, scale="")
        doc = {"observations": [original]}
        self.assertEqual(self.checked(same, doc)["verdict"], "skip")
        for changed in [self.observation(month="2023-07"), self.observation(age=10),
                        self.observation(value_low=90, value_high=125, quote="US$90k–125k")]:
            with self.subTest(changed=changed):
                self.assertEqual(self.checked(changed, doc)["verdict"], "clean")
        rows = PR.check(json.dumps({"observations": [original, same]}).encode(), doc={})["rows"]
        self.assertEqual([r["verdict"] for r in rows], ["clean", "skip"])

    def test_stable_ids_and_accepted_lookup(self):
        row = self.observation(age=10)
        ident = PR.observation_id(row)
        self.assertRegex(ident, r"^[0-9a-f]{64}$")
        same = self.observation(value_low=100000, value_high=115000, scale="", age=10.0,
                                icao="crj9", note="new note", quote="different excerpt", checked="2030-01-01")
        self.assertEqual(PR.observation_id(same), ident)
        for changed in [self.observation(age=5), self.observation(month="2023-07", age=10),
                        self.observation(value_low=90, value_high=125, age=10),
                        self.observation(currency="EUR", age=10)]:
            self.assertNotEqual(PR.observation_id(changed), ident)
        doc = {"observations": [row]}
        found = PR.find_observation(ident, doc)
        self.assertEqual(found, row)
        found["note"] = "caller edit"
        self.assertNotIn("note", row)
        self.assertIsNone(PR.find_observation("0" * 64, doc))
        self.assertIsNone(PR.find_observation(PR.observation_id(self.observation(age=5)), doc))
        self.assertIsNone(PR.find_observation("draft-path", doc))


class TypePage(unittest.TestCase):

    def test_blocks(self):
        self.assertIn("Form 41", seo.toir_block("en", "A320"))
        self.assertIn("<polyline", seo.toir_block("ru", "A320"))
        self.assertEqual(seo.toir_block("en", "C919"), "")
        p = Path(tempfile.mkdtemp()) / "_observations.yaml"
        p.write_text(yaml.safe_dump(OBS), "utf-8")
        old = PR.PATH
        PR.PATH = p
        try:
            html = seo.prices_block("de", "A21N")
            self.assertIn("Listenpreis", html)
            self.assertIn('href="https://example.org/a"', html)
            self.assertEqual(seo.prices_block("de", "A320"), "")
            # заготовка лизинга — линией в долларах каждого года
            obs = dict(OBS, observations=OBS["observations"] + [
                {"icao": "A21N", "kind": "lease", "value": 400, "scale": "k", "currency": "USD", "month": "2019-10",
                 "age": "new", "quote": "400", "source": "https://example.org/b"}])
            p.write_text(yaml.safe_dump(obs), "utf-8")
            h = seo.prices_block("ru", "A21N", 400000, True)
            self.assertIn("class=l3", h)
            self.assertIn("для нового борта", h)
            self.assertIn("доходность парка AerCap", h)
            obs2 = obs["observations"] + [
                {"icao": "A21N", "kind": "lease", "value": 380, "scale": "k", "currency": "USD", "month": "2024-02",
                 "age": "new", "quote": "380", "source": "https://example.org/c"}]
            p.write_text(yaml.safe_dump({"observations": obs2}), "utf-8")
            self.assertEqual(PR.annual_lease("A21N", "2024-12-31")["midpoint"], 380000)
            self.assertIsNone(PR.annual_lease("A21N", "2024-12-31", age=12))
            self.assertIsNone(PR.annual_lease("A21N", "2026-01-01"))
            r = PR.real_level(obs2, True, (2019, 2019), 2025, {2019: 100.0, 2024: 110.0, 2025: 120.0})
            self.assertAlmostEqual(r, 480.0)
            pl = seo.param_lease_usd(100000, range(2019, 2027))
            self.assertAlmostEqual(pl[-1][1], 116.0, places=6)          # 2026: 100 тыс. EUR × 1,16
            self.assertLess(pl[0][1], pl[-1][1])                        # раньше — дешевле в номинале
        finally:
            PR.PATH = old


if __name__ == "__main__":
    unittest.main()
