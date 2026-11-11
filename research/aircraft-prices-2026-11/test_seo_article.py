"""Regression checks for the single published price-research article."""
from __future__ import annotations

import importlib.util
from html import unescape
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('seo_article', HERE / 'seo_article.py')
seo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seo)


class PriceSeoTest(unittest.TestCase):
    def test_source_anchors_match_research_values(self):
        seo.validate_numbers(HERE)

    def test_three_pages_have_one_canonical_and_matching_hreflang(self):
        for lang, filename in seo.LANGS.items():
            with self.subTest(lang=lang):
                html = (HERE / filename).read_text(encoding='utf-8')
                self.assertEqual(html.count('rel="canonical"'), 1)
                self.assertIn(f'href="{seo.seo_url(lang)}"', html)
                self.assertEqual(html.count('name="description"'), 1)
                self.assertEqual(html.count('id="fca-seo-answer"'), 1)
                self.assertEqual(html.count('id="fca-seo-faq"'), 1)
                self.assertEqual(html.count('id="fca-seo-flight"'), 1)
                self.assertEqual(html.count('<h1>'), 1)
                self.assertIn('index,follow', html)
                for l in seo.LANGS:
                    self.assertIn(f'hreflang="{l}" href="{seo.seo_url(l)}"', html)
                self.assertIn(f'href="https://flightcost.app/{lang}/calc"', html)
                self.assertIn(f'href="https://flightcost.app/{lang}/type/A20N"', html)
                self.assertIn(f'href="https://flightcost.app/{lang}/type/A21N"', html)
                self.assertIn(seo.IBA_SOURCE, html)
                self.assertEqual(seo.apply_to_html(html, lang), html)  # idempotence
                self.assertLess(html.find('id="fca-seo-answer"'), html.find('class="verdict"'))
                self.assertGreater(html.find('id="fca-seo-faq"'), html.find('id="fca-seo-answer"'))
                self.assertIn('name="robots" content="index,follow"', html)

                ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
                self.assertEqual(len(ld), 2)
                objects = [json.loads(unescape(x)) for x in ld]
                self.assertEqual(objects[0]['@type'], 'Article')
                self.assertEqual(objects[0]['inLanguage'], lang)
                self.assertEqual(objects[0]['mainEntityOfPage']['@id'], seo.seo_url(lang))
                self.assertEqual(objects[1]['@type'], 'BreadcrumbList')
                self.assertEqual(objects[1]['itemListElement'][-1]['item'], seo.seo_url(lang))
                self.assertNotIn('"@type":"FAQPage"', html)

    def test_article_published_demand_not_published(self):
        txt = (HERE.parent / 'index.yaml').read_text(encoding='utf-8')
        price = txt.split('  - slug: aircraft-prices-2026-11\n', 1)[1].split('  - slug: demand-2026-11\n', 1)[0]
        demand = txt.split('  - slug: demand-2026-11\n', 1)[1].split('  - slug:', 1)[0]
        self.assertIn('draft: false', price)
        self.assertIn('draft: true', demand)
        self.assertEqual(txt.count('slug: aircraft-prices-2026-11'), 1)

    def test_explanation_not_mislabelled_total_cost(self):
        html = (HERE / 'report.html').read_text(encoding='utf-8')
        self.assertIn('Это только владение, а не полная себестоимость рейса', html)
        self.assertIn('не объявленная цена сделки', html)
        self.assertNotIn('Черновик исследования', html)


if __name__ == '__main__':
    unittest.main()
