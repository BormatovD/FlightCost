"""Оформление объявлено один раз и доезжает до каждой страницы.

До `ui.css` палитра была объявлена пять раз в пяти файлах, и три копии
разошлись молча: «справочник» в разборе был зелёным, в витрине —
голубым. Второе объявление того же цвета — тот же класс отказа, что два
отпечатка состава (решение 87), и ловится оно только проверкой, потому
что страница с разъехавшимся цветом выглядит совершенно нормально.

Три утверждения:

  1. В исходниках страниц нет ни одного hex-литерала цвета и ни одного
     имени шрифта. Цвет — только `var(--…)`, шрифт — только `var(--sans)`
     и `var(--mono)`.
  2. Каждая собранная страница содержит ui.css со шрифтами внутри:
     страница открывается без сервера, и внешняя ссылка на шрифт была бы
     тихим откатом на системный.
  3. Шкала карты монотонна: светлота растёт от --ramp-0 к --ramp-6.
     «Ярче = дороже» — единственное направление, которое читается на
     чёрном фоне как величина (решение 86); перестановка двух ступеней
     не сломает ни одной страницы и не будет замечена.

Запуск: python3 tests/test_ui.py
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp import ui  # noqa: E402

PAGES = [
    ROOT / "flightcostapp" / "web" / "serve.html",
    ROOT / "flightcostapp" / "explain.py",
    ROOT / "flightcostapp" / "heatmap.py",
    ROOT / "flightcostapp" / "graph.py",
    ROOT / "flightcostapp" / "inventory.py",
]
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?=[;) ])")
FONT_NAMES = re.compile(
    r"system-ui|ui-sans-serif|ui-monospace|Segoe|Menlo|Helvetica|"
    r"IBM Plex|Arial|Roboto|Consolas", re.I)


def _lum(hex6: str) -> float:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


class Tokens(unittest.TestCase):

    def test_pages_have_no_colour_or_font_literals(self):
        bad = {}
        for p in PAGES:
            text = p.read_text(encoding="utf-8")
            hits = HEX.findall(text) + FONT_NAMES.findall(text)
            if hits:
                bad[p.name] = sorted(set(hits))
        self.assertEqual(bad, {}, "цвет или шрифт объявлен вне ui.css")

    def test_ui_css_declares_every_provenance_variable(self):
        css = ui.css(inline_fonts=False)
        for var in set(ui.PROV_VAR.values()) | set(ui.PROV_FILL.values()):
            name = var[len("var("):-1]
            self.assertIn(f"{name}:", css, f"{name} нет в ui.css")

    def test_inline_css_embeds_every_font(self):
        css = ui.css(inline_fonts=True)
        self.assertNotIn("НЕТ ФАЙЛА ШРИФТА", css)
        self.assertNotRegex(css, r"url\(fonts/", "ссылка на файл шрифта пережила вшивание")
        self.assertEqual(css.count("data:font/woff2;base64,"), 3,
                         "ожидаются три начертания: Sans 400, Sans 600, Mono 400")

    def test_ramp_is_monotonic_in_lightness(self):
        css = ui.css(inline_fonts=False)
        steps = []
        for i in range(7):
            m = re.search(rf"--ramp-{i}:\s*([^;]+);", css)
            self.assertIsNotNone(m, f"--ramp-{i} нет в ui.css")
            v = m.group(1).strip()
            if v.startswith("#"):
                steps.append(_lum(v))
            else:                                   # rgba(r,g,b,a) над чёрным
                r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", v))
                steps.append(a * _lum("#%02x%02x%02x" % (int(r), int(g), int(b))))
        for lo, hi in zip(steps, steps[1:]):
            self.assertLess(lo, hi, f"шкала не монотонна: {steps}")

    def test_toggle_exists_on_both_maps(self):
        serve = (ROOT / "flightcostapp" / "web" / "serve.html").read_text(encoding="utf-8")
        heat = (ROOT / "flightcostapp" / "heatmap.py").read_text(encoding="utf-8")
        self.assertIn("nozones", serve, "в витрине нет выключателя слоя зон")
        self.assertIn("plain", heat, "на карте сборов нет выключателя раскраски")


if __name__ == "__main__":
    unittest.main(verbosity=2)
