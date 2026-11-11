"""Цены и лизинг самолётов из публикаций: проверка черновика, приёмка, ряд (страница типа)."""

from __future__ import annotations

import json
import tempfile
import unittest
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
             "quote": "list price of $129.5 million", "source": "https://example.org/a"},
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
            self.assertEqual(PR.market_now(obs2, True, since=2023), (2024, 380.0))
            self.assertIsNone(PR.market_now(obs2, False, since=2023))
            self.assertIsNone(PR.market_now(obs["observations"], True, since=2023))   # только 2019 — не «сейчас»
            r = PR.real_level(obs2, True, (2019, 2019), 2025, {2019: 100.0, 2024: 110.0, 2025: 120.0})
            self.assertAlmostEqual(r, 480.0)
            pl = seo.param_lease_usd(100000, range(2019, 2027))
            self.assertAlmostEqual(pl[-1][1], 116.0, places=6)          # 2026: 100 тыс. EUR × 1,16
            self.assertLess(pl[0][1], pl[-1][1])                        # раньше — дешевле в номинале
        finally:
            PR.PATH = old


if __name__ == "__main__":
    unittest.main()
