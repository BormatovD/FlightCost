"""Сноски витрины — одной формой: пояснение ⓘ, а не строка текста под полем.

Решение 184. Строки-сноски копились по одной («без него запас неполон»,
«ноль в лизинге…», «их нет в справочнике…») и съедали левую колонку. Тест
держит договорённость: в статической разметке под полями не появляется
нового пояснительного текста — только значения с id (82%, × 1,00), а
пояснение уходит в `hint()` / `data-hk`.
"""

from __future__ import annotations

import pathlib
import re
import unittest

WEB = pathlib.Path(__file__).resolve().parents[1] / "flightcostapp" / "web"
CYR = re.compile(r"[А-Яа-яЁё]")


class Hints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        html = (WEB / "serve.html").read_text(encoding="utf-8")
        cls.markup = html[:html.index('<script type="module">')]
        cls.script = html[html.index('<script type="module">'):]

    def test_no_static_footnote_text_under_fields(self):
        bad = []
        for m in re.finditer(r'<div class="rv"[^>]*>(.*?)</div>', self.markup, re.S):
            body = re.sub(r'<span id="[^"]+">[^<]*</span>', "", m.group(1))
            if CYR.search(re.sub(r"<[^>]+>", "", body)):
                bad.append(re.sub(r"\s+", " ", m.group(1))[:80])
        self.assertEqual(bad, [], f"сноска текстом под полем, а не пояснением: {bad}")

    def test_every_hint_slot_is_filled_by_script(self):
        slots = set(re.findall(r'data-hk="([\w-]+)"', self.markup))
        filled = set(re.findall(r'setHint\("([\w-]+)"', self.script))
        self.assertEqual(sorted(slots - filled), [], "пояснение в разметке, которое никто не заполняет")

    def test_hint_styles_live_in_ui_css(self):
        css = (WEB / "ui.css").read_text(encoding="utf-8")
        self.assertIn(".hint.o", css)
        self.assertIn("#hintpop", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
