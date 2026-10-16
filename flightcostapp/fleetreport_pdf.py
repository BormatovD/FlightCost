"""PDF отчёта по парку: светлый HTML, напечатанный безголовым Chromium.

Почему Chromium, а не библиотека вёрстки PDF. Документ — тот же HTML,
что на сайте, с сеткой, SVG-графиками и вшитыми шрифтами; печать
браузером даёт ровно то, что видно на экране, без второй вёрстки под
другую библиотеку с другим подмножеством CSS. Цена — Chromium на
сервере (`pip install playwright` и `playwright install --with-deps
chromium`, около 150 МБ). Нет его — отчёт на сайте работает, а PDF
отвечает понятной ошибкой с тем, что поставить; печать из браузера
(Ctrl+P → «Сохранить как PDF») даёт тот же документ.
"""

from __future__ import annotations

import threading

# Один Chromium на процесс одновременно: печать — секунда-две и сотни
# мегабайт памяти, параллельные печати на маленьком сервере не нужны.
_LOCK = threading.Lock()

INSTALL = ("PDF на сервере не настроен: нужен Chromium для печати — "
           "pip install playwright && playwright install --with-deps chromium "
           "(на сервере — в общий каталог, см. deploy/README.md, «PDF отчёта по парку»). "
           "Пока можно распечатать страницу отчёта из браузера в PDF.")


def _launch(p):
    """Свой Chromium playwright, а нет его — уже установленный браузер.

    Скачивание Chromium с cdn.playwright.dev бывает недоступно (сеть,
    VPN); тогда печатает обычный Google Chrome или Edge, если они есть
    на машине. На сервере ставится свой Chromium, и до запасных не доходит."""
    errors = []
    for kw in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
        try:
            return p.chromium.launch(args=["--no-sandbox"], **kw)
        except Exception as exc:                          # noqa: BLE001
            errors.append(str(exc).splitlines()[0])
    raise RuntimeError(INSTALL + " Пробовали: " + " | ".join(errors))


def html_to_pdf(html: str, *, timeout_ms: int = 60000) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(INSTALL) from exc
    with _LOCK:
        try:
            with sync_playwright() as p:
                browser = _launch(p)
                try:
                    page = browser.new_page()
                    page.set_content(html, wait_until="load", timeout=timeout_ms)
                    # Масштаб 0,72: страница вёрстки ~940 px — настольная
                    # раскладка в три колонки, а не телефонная, и шрифт
                    # остаётся читаемым на A4.
                    return page.pdf(format="A4", print_background=True, scale=0.72,
                                    margin={"top": "14mm", "bottom": "14mm",
                                            "left": "12mm", "right": "12mm"})
                finally:
                    browser.close()
        except RuntimeError:
            raise
        except Exception as exc:                          # noqa: BLE001
            if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                raise RuntimeError(INSTALL) from exc
            raise
