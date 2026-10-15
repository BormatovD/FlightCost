"""Отчёт по парку (Ф5, решение 204): объём → рейсы → борты → итог.

Фикстура — ответы сети витрины на пяти типах (FRA, BCN, LIS, MAD, FCO),
посчитанные ядром на хранилище из фикстур тестов; потоки пар заданы.
Числа — прогон модели, не рынок: проверяются свойства плана, документа
и книги, а не величины.
"""

from __future__ import annotations

import copy
import re
import json
import math
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.fleetreport import (DEFAULTS, TypePlan, assumptions,  # noqa: E402
                                       availability_for, build, load_availability)
from flightcostapp.network import WEEKS_PER_MONTH  # noqa: E402

FIX = json.loads((ROOT / "tests" / "fixtures" / "fleetreport_network.json").read_text())


class Plan(unittest.TestCase):

    def setUp(self):
        self.a = assumptions({"share": 0.12})

    def test_volume_frequency_fleet(self):
        tp = TypePlan("A320", FIX["A320"])
        pl = tp.plan(self.a)
        for p in pl["pairs"]:
            self.assertAlmostEqual(p["volume"], 0.12 * p["market"], delta=1e-6)
            self.assertGreaterEqual(p["freq"], self.a["min_freq"])
            carried = sum(x["pax"] for x in p["legs"]) * p["freq"] * WEEKS_PER_MONTH
            self.assertAlmostEqual(carried, p["volume"], delta=1.0)    # всё вывезено
            for x in p["legs"]:
                self.assertLessEqual(x["lf"], 1.0)
            if not p["min_binds"]:
                self.assertLessEqual(max(x["lf"] for x in p["legs"]), self.a["lf_target"] + 1e-9)
        self.assertEqual(pl["n_op"], math.ceil(pl["hours"] / tp.util - 1e-9))
        self.assertEqual(pl["spare"], max(1, math.ceil(pl["n_op"] * self.a["reserve"] - 1e-9)))
        self.assertAlmostEqual(pl["cost"]["ownership"], pl["fleet"] * tp.lease, delta=0.01)
        self.assertAlmostEqual(sum(pl["cost"].values()), pl["cost_total"], delta=0.01)

    def test_price_moves_share_by_elasticity(self):
        tp = TypePlan("A20N", FIX["A20N"])
        cheap = tp.plan(dict(self.a, price=0.9))
        self.assertAlmostEqual(cheap["share"], 0.12 * 0.9 ** -DEFAULTS["elasticity"], places=9)
        self.assertGreater(cheap["pax"], tp.plan(self.a)["pax"])
        capped = tp.plan(dict(self.a, share=0.5, price=0.5))
        self.assertAlmostEqual(capped["share"], DEFAULTS["share_cap"])

    def test_thin_market_favours_small_aircraft(self):
        """На тонком рынке нижняя граница частоты держит большой борт
        полупустым — маленький выигрывает; на толстом — наоборот."""
        rep = build(copy.deepcopy(FIX))
        seats = {t["icao"]: t["seats"] for t in rep["types"]}
        bands = rep["share_bands"]
        self.assertGreater(len(bands), 1)
        self.assertLess(seats[bands[0]["type"]], seats[bands[-1]["type"]])
        thin = rep["share_sweep"][0]["share"]
        big = max(seats, key=seats.get)
        pl = TypePlan(big, FIX[big]).plan(dict(assumptions({}), share=thin))
        self.assertTrue(all(p["min_binds"] for p in pl["pairs"]))

    def test_pairs_without_market_are_named(self):
        res = copy.deepcopy(FIX)
        for t in res.values():
            t["pairs"][0]["market_pax_month"] = None
        rep = build(res)
        note = next(n for n in rep["notes"] if n["code"] == "no_market")
        self.assertIn(f'{FIX["A320"]["pairs"][0]["a"]}-{FIX["A320"]["pairs"][0]["b"]}', note["pairs"])

    def test_failed_type_is_named_not_dropped(self):
        res = copy.deepcopy(FIX)
        res["C919"] = {"error": "ни одной пары с правом летать — сети нет", "network": None}
        rep = build(res)
        c = next(t for t in rep["types"] if t["icao"] == "C919")
        self.assertEqual(c["status"], "failed")
        self.assertIn("сети нет", c["why"])

    def test_range_limit_is_flagged_and_drives_frequency(self):
        """Борт по дальности поднимает меньше плановой загрузки — пара
        помечена, рейсы подобраны по пределу, минус назван."""
        res = copy.deepcopy(FIX)
        lg = res["A21N"]["pairs"][0]["legs"][0]
        lg["max_pax"] = int(lg["seats"] * 0.6)
        a = assumptions({"share": 0.3})
        p = TypePlan("A21N", res["A21N"]).plan(a)["pairs"][0]
        self.assertAlmostEqual(p["range_cap"], lg["max_pax"] / lg["seats"])
        need = p["volume"] / 2 / (WEEKS_PER_MONTH * lg["max_pax"])
        self.assertEqual(p["freq"], max(a["min_freq"], math.ceil(need - 1e-9)))
        rep = build(res, assume={"share": 0.3})
        t = next(x for x in rep["types"] if x["icao"] == "A21N")
        self.assertIn("range_limited", [c["code"] for c in t["cons"]])
        from flightcostapp.fleetreport_doc import render
        self.assertIn('class="rng"', render(rep))

    def test_fare_conv_scales_revenue_not_share(self):
        """Чек к минимуму — уровень выручки, а не цена к рынку: доля и
        рейсы те же, выручка пропорциональна."""
        tp = TypePlan("A20N", FIX["A20N"])
        p1 = tp.plan(dict(self.a, fare_conv=1.0))
        p2 = tp.plan(dict(self.a, fare_conv=1.2))
        self.assertEqual(p1["share"], p2["share"])
        self.assertEqual(p1["fleet"], p2["fleet"])
        self.assertAlmostEqual(p2["revenue"], 1.2 * p1["revenue"], delta=1.0)
        rep = build(copy.deepcopy(FIX), assume={"share": 0.12, "fare_conv": 1})
        self.assertIn("conv_one", [n["code"] for n in rep["notes"]])

    def test_assumptions_accept_percent(self):
        a = assumptions({"share": "15", "lf_target": "82", "reserve": "10", "min_freq": "14"})
        self.assertAlmostEqual(a["share"], 0.15)
        self.assertAlmostEqual(a["lf_target"], 0.82)
        self.assertEqual(a["min_freq"], 14)


class Document(unittest.TestCase):

    def test_renders_in_every_language_and_theme(self):
        from flightcostapp.fleetreport_doc import render
        rep = build(copy.deepcopy(FIX), assume={"share": 0.12})
        for lang in ("ru", "en", "de"):
            for theme in ("light", "dark"):
                h = render(copy.deepcopy(rep), theme=theme, lang=lang, cur="USD", rate=1.1)
                self.assertNotIn("None", h)
                self.assertIn("<svg", h)
                self.assertIn("USD", h)
        h = render(copy.deepcopy(rep))
        for sec in ("Что реально можно получить", "Лётно-технические характеристики",
                    "Экономика кресла", "Примерка на сеть", "Цена и доля", "Плюсы и минусы"):
            self.assertIn(sec, h)
        self.assertLess(h.index("Лётно-технические"), h.index("Экономика кресла"))
        self.assertLess(h.index("Экономика кресла"), h.index("Примерка на сеть"))

    def test_highlight_and_tooltips(self):
        """Выделение типа задаётся в разметке (работает и в PDF), у точек
        графика — подписи с плечами, RASK — у каждого типа свой."""
        from flightcostapp.fleetreport_doc import render
        rep = build(copy.deepcopy(FIX), assume={"share": 0.12})
        h = render(copy.deepcopy(rep))
        self.assertNotIn("data-hl=", h.split("<body")[1].split(">")[0])
        icaos = [t["icao"] for t in rep["types"] if t.get("status") == "ok"]
        h = render(copy.deepcopy(rep), hl=icaos[-1].lower())
        self.assertIn(f'data-hlk="{icaos[-1]}"', h)
        self.assertIn("data-tip=", h)
        self.assertIn("→", h.split('class="rask"')[1][:400])
        slots = {s for s in re.findall(r'class="rask" data-t="(\d)"', h)}
        self.assertEqual(len(slots), len(icaos))
        self.assertIn('data-hl="1"] [data-t]:not([data-t="1"])', h)
        h = render(copy.deepcopy(rep), hl="XXXX")
        self.assertNotIn("data-hlk=", h)


def _chromium() -> bool:
    try:
        from flightcostapp.fleetreport_pdf import html_to_pdf
        html_to_pdf("<p>x</p>")
        return bool(shutil.which("pdftotext"))
    except Exception:                                    # noqa: BLE001
        return False


@unittest.skipUnless(_chromium(), "нет Chromium или pdftotext — PDF не проверить")
class Pdf(unittest.TestCase):
    """Заголовок раздела не остаётся внизу страницы без того, что под ним."""

    HEADS = ("Что реально можно получить", "Лётно-технические характеристики",
             "Экономика кресла", "Из чего складывается кресло-км", "Примерка на сеть",
             "Цена и доля", "Тонкий и толстый рынок", "Плюсы и минусы", "Что важно понимать",
             "Источники")

    def test_no_orphan_headings(self):
        from flightcostapp.fleetreport_doc import render
        from flightcostapp.fleetreport_pdf import html_to_pdf
        from flightcostapp.ui import css
        d = pathlib.Path(tempfile.mkdtemp())
        for share, types in ((0.05, list(FIX)), (0.3, ["A320", "B738", "A21N"])):
            rep = build({k: FIX[k] for k in types}, assume={"share": share})
            f = d / "r.pdf"
            f.write_bytes(html_to_pdf(render(rep, theme="light", css_text=css(inline_fonts=True))))
            pages = subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True,
                                   text=True).stdout.split("\f")
            for n, txt in enumerate(pages, start=1):
                lines = [x.strip() for x in txt.splitlines() if x.strip()]
                for h in self.HEADS:
                    idx = [i for i, x in enumerate(lines) if x.startswith(h)]
                    self.assertFalse(idx and len(lines) - 1 - idx[-1] <= 2,
                                     f"стр. {n}: «{h}» внизу страницы без содержания")


class Availability(unittest.TestCase):

    def setUp(self):
        self.av = load_availability()

    def test_neo_is_not_ceo(self):
        self.assertEqual(availability_for("A20N", "Airbus A320neo", self.av)["kind"], "production")
        self.assertEqual(availability_for("A320", "Airbus A320", self.av)["kind"], "secondary")

    def test_own_type_by_name(self):
        a = availability_for("USER:RW214", "Ту-214 Red Wings", self.av)
        self.assertEqual(a["key"], "T204")
        self.assertIsNone(availability_for("USER:NMA", "Boeing NMA", self.av))

    def test_every_type_is_complete(self):
        from flightcostapp.fleetreport import load_specs
        specs = load_specs()["types"]
        for k, t in self.av["types"].items():
            self.assertIn(t["kind"], ("production", "waiting", "secondary", "ended", "restricted"), k)
            self.assertIn(t["review"], self.av["reviews"], k)
            self.assertTrue(t["points"] and t["price"], k)
            self.assertTrue(self.av["reviews"][t["review"]]["sources"], k)
            self.assertIn(k, specs, f"{k}: нет таблицы ЛТХ из обзора")


@unittest.skipUnless(shutil.which("soffice"), "нет LibreOffice — формулы не пересчитать")
class Excel(unittest.TestCase):
    """Книга пересчитывается LibreOffice и приходит к числам плана; правка
    доли на «Допущениях» меняет итог так же, как план."""

    @classmethod
    def setUpClass(cls):
        import openpyxl
        from flightcostapp.fleetreport_xlsx import build_xlsx
        cls.rep = build(copy.deepcopy(FIX), assume={"share": 0.12})
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "r.xlsx").write_bytes(build_xlsx(cls.rep, FIX))
        wb = openpyxl.load_workbook(d / "r.xlsx")
        wb["Допущения"]["B5"] = 0.25                      # доля потока
        wb.save(d / "s25.xlsx")
        cls.vals = {}
        for name in ("r.xlsx", "s25.xlsx"):
            subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir",
                            str(d / "out"), str(d / name)], check=True,
                           capture_output=True, timeout=180)
            wb = openpyxl.load_workbook(d / "out" / name, data_only=True)
            v = wb["Сводка"]
            heads = [c.value for c in v[4]][1:]
            got = {}
            for row in v.iter_rows(min_row=5):
                if row[0].value in ("Результат за месяц", "Бортов всего"):
                    got[row[0].value] = dict(zip(heads, [c.value for c in row[1:]]))
            cls.vals[name] = got
            errs = [c.coordinate for ws in wb for r in ws.iter_rows() for c in r
                    if isinstance(c.value, str) and c.value.startswith("#")]
            assert not errs, f"ошибки формул в {name}: {errs[:5]}"

    def test_workbook_equals_plan(self):
        for t in self.rep["types"]:
            self.assertAlmostEqual(self.vals["r.xlsx"]["Результат за месяц"][t["name"]],
                                   t["plan"]["result"], delta=5.0)
            self.assertEqual(self.vals["r.xlsx"]["Бортов всего"][t["name"]], t["plan"]["fleet"])

    def test_share_change_matches_plan(self):
        for t in self.rep["types"]:
            pl = TypePlan(t["icao"], FIX[t["icao"]]).plan(assumptions({"share": 0.25}))
            self.assertAlmostEqual(self.vals["s25.xlsx"]["Результат за месяц"][t["name"]],
                                   pl["result"], delta=5.0)
            self.assertEqual(self.vals["s25.xlsx"]["Бортов всего"][t["name"]], pl["fleet"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
