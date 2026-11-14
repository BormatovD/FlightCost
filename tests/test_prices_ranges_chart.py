"""Published price ranges remain intervals; their midpoint is an explicit scenario."""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from flightcostapp import prices as PR
from flightcostapp import seo


CRJ9 = {
    "icao": "CRJ9", "kind": "lease", "value_low": 100, "value_high": 115,
    "scale": "k", "currency": "USD", "month": "2022-07", "age": None,
    "publisher": "TrueNoord",
    "source": "https://www.truenoord.com/wp-content/uploads/2022/07/"
              "TrueNoord-Insight-Regional-Jet-Market-Report-2022.pdf",
    "quote": "these may now be as low as US$100-115,000 in order to ensure that stored inventory "
             "is returned to service",
    "note": "Стр. 33, §6.3.1; возможный низкий диапазон месячной аренды для возврата находящихся "
            "на хранении самолётов в эксплуатацию. Июль 2022; точный возраст не указан.",
}


class Markup(HTMLParser):

    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.elements, self.text = [], []
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)

    def find(self, tag, cls=None):
        return [attrs for name, attrs in self.elements if name == tag
                and (cls is None or cls in attrs.get("class", "").split())]


class PriceRangeCharts(unittest.TestCase):

    def render(self, observations, lang="en", **kwargs):
        with mock.patch.object(PR, "of", return_value=observations):
            return seo.prices_block(lang, "CRJ9", **kwargs)

    def test_real_single_range_has_visible_interval_midpoint_and_published_bounds(self):
        for lang, midpoint in (("ru", "107,5"), ("en", "107.5"), ("de", "107,5")):
            with self.subTest(lang=lang):
                body = self.render([CRJ9], lang)
                doc = Markup(body)
                bars, dots = doc.find("path", "range-bar"), doc.find("circle", "midpoint")
                self.assertEqual(len(bars), 1)
                self.assertEqual(len(dots), 1)
                self.assertFalse(doc.find("polygon"), "one July estimate has no temporal area")
                self.assertFalse(doc.find("polyline"))
                # One x coordinate, published low/high caps, and their actual arithmetic midpoint.
                x, upper, lower, cap_left, _, cap_right, *_ = map(
                    float, re.findall(r"-?\d+(?:\.\d+)?", bars[0]["d"]))
                self.assertGreater(lower, upper)
                self.assertAlmostEqual(float(dots[0]["cx"]), x)
                self.assertAlmostEqual(float(dots[0]["cy"]), (upper + lower) / 2, delta=0.1)
                self.assertLess(cap_left, x)
                self.assertGreater(cap_right, x)
                self.assertIn("USD 100–115 k", body)
                self.assertIn(f'{seo.T[lang]["ts_midpoint"]}: USD {midpoint} k', body)
                self.assertIn(f'{midpoint} · {seo.T[lang]["ts_midpoint"]}', body)
                self.assertIn(seo.T[lang]["ts_age_unknown"], body)
                self.assertIn("2022-07", body)
                # Context makes this low stored-aircraft scenario distinct from a general market rate.
                self.assertIn(seo.esc(CRJ9["quote"]), body)
                self.assertIn(seo.esc(CRJ9["note"]), body)
                self.assertEqual(len(doc.find("details", "price-source")), 1)

    def test_midpoint_action_targets_accepted_observation_in_current_language(self):
        for lang in seo.LANGS:
            with self.subTest(lang=lang):
                doc = Markup(self.render([CRJ9], lang))
                action, = doc.find("a", "price-use")
                target = urlsplit(action["href"])
                self.assertEqual(target.path, f"/{lang}/calc")
                self.assertEqual(parse_qs(target.query), {
                    "ac": ["CRJ9"], "lease_observation": [PR.observation_id(CRJ9)]})
                self.assertIn(seo.T[lang]["ts_use_midpoint"], doc.text)

    def test_upper_bound_is_included_in_y_scale(self):
        doc = Markup(self.render([dict(CRJ9, value_low=100, value_high=900)]))
        bar, = doc.find("path", "range-bar")
        _, upper, lower, *_ = map(float, re.findall(r"-?\d+(?:\.\d+)?", bar["d"]))
        self.assertGreaterEqual(upper, 10, "the published high bound must stay inside the plot")
        self.assertLessEqual(lower, 164)
        self.assertTrue(any(text in ("800", "1,000") for text in doc.text))

    def test_compatible_dates_fill_only_between_the_two_observed_months(self):
        first = dict(CRJ9, age=10)
        second = dict(first, month="2023-07", value_low=120, value_high=135)
        doc = Markup(self.render([second, first]))       # input order does not change time order
        band, = doc.find("polygon", "range-band")
        self.assertEqual(len(doc.find("path", "range-bar")), 2)
        self.assertEqual(len(doc.find("circle", "midpoint")), 2)
        coords = [tuple(map(float, p.split(","))) for p in band["points"].split()]
        self.assertEqual(len(coords), 4)
        point_xs = {float(dot["cx"]) for dot in doc.find("circle", "midpoint")}
        self.assertEqual({x for x, _ in coords}, point_xs)
        self.assertEqual(len(point_xs), 2)
        midline, = doc.find("polyline", "range-midline")
        midpoints = [tuple(map(float, p.split(","))) for p in midline["points"].split()]
        self.assertEqual(midpoints, [(float(p["cx"]), float(p["cy"]))
                                    for p in doc.find("circle", "midpoint")])

    def test_different_age_source_and_kind_are_not_one_band(self):
        first = dict(CRJ9, age=10)
        for changes in ({"age": "new"}, {"age": 12}, {"age": None},
                        {"source": "https://other.example/report.pdf"}, {"kind": "value"}):
            with self.subTest(changes=changes):
                second = dict(first, month="2023-07", **changes)
                doc = Markup(self.render([first, second]))
                self.assertFalse(doc.find("polygon", "range-band"))
                self.assertFalse(doc.find("polyline", "range-midline"))
                self.assertEqual(len(doc.find("path", "range-bar")), 2)
        # Appraisal and deal share the aircraft-price chart, but still cannot form one band.
        first = dict(CRJ9, kind="value", scale="m", value_low=10, value_high=12, age="new")
        doc = Markup(self.render([first, dict(first, kind="deal", month="2023-07")]))
        self.assertEqual(len(doc.find("svg")), 1)
        self.assertFalse(doc.find("polygon", "range-band"))
        self.assertFalse(doc.find("a", "price-use"), "purchase prices are not monthly lease scenarios")

    def test_scalar_and_same_month_estimates_do_not_create_a_band(self):
        first = dict(CRJ9, age=10)
        scalar = {k: v for k, v in dict(first, month="2022-08", value=110).items()
                  if k not in ("value_low", "value_high")}
        second = dict(first, month="2022-09", value_low=105, value_high=120)
        doc = Markup(self.render([first, scalar, second]))
        self.assertFalse(doc.find("polygon", "range-band"))
        self.assertEqual(len(doc.find("circle")), 3)
        self.assertEqual(len(doc.find("circle", "midpoint")), 2)
        same_month = Markup(self.render([first, dict(first, value_low=105, value_high=120)]))
        self.assertFalse(same_month.find("polygon", "range-band"))
        self.assertEqual(len(same_month.find("path", "range-bar")), 2)

    def test_parametric_line_remains_separate_from_range_scenario(self):
        with mock.patch.object(seo, "param_lease_usd", return_value=[(2022.5, 140), (2026.5, 160)]), \
             mock.patch.object(PR, "lessor_yield", return_value={}), \
             mock.patch.object(PR, "real_level", return_value=None):
            doc = Markup(self.render([CRJ9], lease_eur=140000, new_gen=False))
        self.assertEqual(len(doc.find("polyline", "l3")), 1)
        self.assertEqual(len(doc.find("path", "range-bar")), 1)
        self.assertFalse(doc.find("polygon", "range-band"))

    def test_original_currency_bounds_survive_without_a_usd_conversion(self):
        for low, high, scale, shown, midpoint in [
            (100.25, 115.5, "k", "EUR 100.25–115.5 k", "EUR 107.875 k"),
            (100000.1, 115000.2, "", "EUR 100,000.1–115,000.2", "EUR 107,500.15"),
        ]:
            with self.subTest(scale=scale):
                body = self.render([dict(CRJ9, currency="EUR", scale=scale, value_low=low, value_high=high)])
                self.assertIn(shown, body)
                self.assertIn("computed midpoint: " + midpoint, body)
                self.assertNotIn("<svg", body)

    def test_existing_scalar_remains_a_single_quoted_point(self):
        scalar = {k: v for k, v in dict(CRJ9, value=180, age="new").items()
                  if k not in ("value_low", "value_high")}
        doc = Markup(self.render([scalar]))
        self.assertEqual(len(doc.find("circle", "k-lease")), 1)
        self.assertFalse(doc.find("circle", "midpoint"))
        self.assertFalse(doc.find("path", "range-bar"))
        self.assertFalse(doc.find("polygon", "range-band"))
        self.assertFalse(doc.find("a", "price-use"))
        self.assertIn("USD 180 k", doc.text)

    def test_external_context_and_svg_titles_are_escaped(self):
        body = self.render([dict(CRJ9, publisher='TrueNoord <script>alert("x")</script>',
                                 note='<img src=x onerror="alert(1)">')])
        doc = Markup(body)
        self.assertFalse(doc.find("script"))
        self.assertFalse(doc.find("img"))
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&lt;img", body)


if __name__ == "__main__":
    unittest.main()
