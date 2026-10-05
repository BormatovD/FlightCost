"""Оформление: один источник для всех страниц.

`web/ui.css` — токены (шрифт, палитра, цвета происхождения) и общие
примитивы. Этот модуль его читает и раздаёт:

  css(inline_fonts=True)   текст ui.css со шрифтами, вшитыми как data:-URI —
                           для статических страниц, которые открываются
                           без сервера (разбор маршрута, карта данных,
                           витрина хранилища, карта сборов)
  css(inline_fonts=False)  тот же текст со ссылками на fonts/*.woff2 —
                           для `fca serve`, который отдаёт шрифты файлами

Второго списка цветов в Python быть не должно. Провенанс ссылается на
имя переменной CSS, а не на hex: PROV_VAR["store"] == "var(--doc)".
Если страница вставляет цвет в разметку (полоса состава, точка легенды),
она вставляет `var(--…)`, и ui.css на странице обязан быть — иначе
переменная не разрешится и цвет молча пропадёт. Проверка на это в
`test_ui.py`: каждая страница содержит `--doc:` в своём <style>.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

WEB = Path(__file__).parent / "web"
FONTS = WEB / "fonts"

# ПРОИСХОЖДЕНИЕ → переменная. Ключи — как в трассировке модели.
#   store      число из документа или справочника
#   source     внешний источник до разбора (узел карты данных)
#   input      задано пользователем
#   override   заменено вручную через --set
#   derived    выведено формулой из других шагов
#   default    ВЫДУМАНО: константа в коде вместо данных
#   fleet      параметрическая заготовка флота — та же природа, что default
#   estimated  ярус 3, параметрика — та же природа
# Три последних одним цветом намеренно: пользователю важно одно —
# это число никто не публиковал.
PROV_VAR = {
    "store":     "var(--doc)",
    "source":    "var(--src)",
    "input":     "var(--user)",
    "override":  "var(--override)",
    "derived":   "var(--calc)",
    "default":   "var(--guess)",
    "fleet":     "var(--guess)",
    "estimated": "var(--guess)",
}
PROV_FILL = {k: v.replace(")", "-f)") for k, v in PROV_VAR.items()}


def prov_var(kind: str) -> str:
    """Цвет для неизвестного вида провенанса — оранжевый, не серый.

    Неизвестный ключ означает, что модель завела новый вид происхождения,
    а оформление о нём не знает. Серый спрятал бы это; оранжевый покажет
    как «неподтверждённое», что и верно по существу.
    """
    return PROV_VAR.get(kind, "var(--guess)")


_URL = re.compile(r"url\((fonts/[^)]+\.woff2)\)")


def css(inline_fonts: bool = True) -> str:
    text = (WEB / "ui.css").read_text(encoding="utf-8")
    if not inline_fonts:
        return text

    def repl(m: re.Match) -> str:
        p = WEB / m.group(1)
        if not p.exists():
            # Отсутствующий файл шрифта — не тихий откат на системный.
            # Страница выйдет, но скажет об этом в комментарии рядом.
            return f"url({m.group(1)}) /* НЕТ ФАЙЛА ШРИФТА: {p.name} */"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"url(data:font/woff2;base64,{b64})"

    return _URL.sub(repl, text)


def style_tag(inline_fonts: bool = True) -> str:
    return f"<style>\n{css(inline_fonts)}\n</style>"
