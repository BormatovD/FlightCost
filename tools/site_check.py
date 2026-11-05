#!/usr/bin/env python3
"""Проверка сайта браузером — быстрая перед выкладкой, полная перед крупным.

Договорённость чекапа (раздел 1): перед каждой выкладкой — десяток
ключевых страниц на трёх языках и эталонный расчёт; полный обход всех
страниц из sitemap — перед миграцией и крупными обновлениями.

Запуск на сервере (там есть Chromium для PDF и Playwright в окружении):

    PLAYWRIGHT_BROWSERS_PATH=/srv/fca/ms-playwright \\
      /srv/fca/venv/bin/python /srv/fca/app/tools/site_check.py --quick
    ... --full                     # все адреса из sitemap.xml
    ... --base https://flightcost.app --shots /tmp/shots

По каждой странице, на ширине 1280 и 390:
  * ответ 200, нет ошибок скрипта и ошибок в консоли;
  * <html lang> совпадает с языком адреса;
  * на английских и немецких страницах нет русского текста (кроме
    названий источников — порог, а не ноль), с примерами;
  * ссылки с языковой страницы ведут на тот же язык (и /map, /data — с ?lang=);
  * на телефоне нет прокрутки вбок;
  * переключатель валюты есть только там, где есть суммы, и при выборе
    другой валюты меняются все суммы.
Плюс эталонный расчёт FRA–BCN A320 (загрузка 0,82, тариф 95, июль):
сумма рейса, безубыточный чек и доля заготовки против ожидаемых.

Ничего не пишет. Код выхода 1 — есть находки.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

LANGS = ("ru", "en", "de")
QUICK = ["/{l}/", "/{l}/about", "/{l}/types", "/{l}/type/A320", "/{l}/research/", "/{l}/monitor",
         "/{l}/monitor?tab=series",
         "/map?lang={l}", "/data?lang={l}"]
QUICK_PLAIN = ["/", "/impressum", "/datenschutz", "/healthz"]
CYR = re.compile(r"[А-Яа-яЁё]{3,}")
# Названия, которые законно остаются русскими на любом языке: издатели и
# источники, имена перевозчиков. Пополнять по находкам, а не заранее.
CYR_ALLOWED = {"Аэрофлот", "Победа", "Россия", "Росавиация", "ЕМИСС"}
CYR_MAX_WORDS = 3
# Известное и принятое: подписи узлов карты данных пока по-русски (решение 220).
# Печатается отдельной строкой, а не находкой.
KNOWN_CYR = {"/map": "подписи узлов карты по-русски — решение 220"}
NOTES: set = set()
REF = {"origin": "FRA", "destination": "BCN", "ac": "A320", "lf": "0.82", "fare": "95", "month": "7"}


def sitemap_paths(base: str) -> list[str]:
    with urllib.request.urlopen(f"{base}/sitemap.xml", timeout=30) as r:
        root = ET.fromstring(r.read())
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    out = []
    for loc in root.findall(".//s:loc", ns):
        u = urlparse(loc.text.strip())
        out.append(u.path + (f"?{u.query}" if u.query else ""))
    return sorted(set(out))


def lang_of(path: str) -> str | None:
    m = re.match(r"^/(ru|en|de)(/|$)", path)
    if m:
        return m.group(1)
    q = parse_qs(urlparse(path).query)
    return (q.get("lang") or [None])[0]


def check_page(page, base: str, path: str, width: int, shots: str | None) -> list[str]:
    found, errors = [], []
    page.set_viewport_size({"width": width, "height": 900})
    page.on("pageerror", lambda e: errors.append(f"ошибка скрипта: {e}"))
    page.on("console", lambda m: errors.append(f"консоль: {m.text}") if m.type == "error" else None)
    try:
        resp = page.goto(base + path, wait_until="networkidle", timeout=60_000)
    except Exception as e:                                         # noqa: BLE001
        return [f"не открылась: {type(e).__name__}: {str(e)[:120]}"]
    if resp is None or resp.status != 200:
        found.append(f"ответ {resp.status if resp else '—'}")
    page.wait_for_timeout(800)
    lang = lang_of(path)
    info = page.evaluate("""() => {
        // Переключатель языка (hreflang) законно ведёт на другие языки.
        const a = [...document.querySelectorAll('a[href]:not([hreflang])')].map(x => x.getAttribute('href'));
        return {
          lang: document.documentElement.lang || '',
          text: document.body ? document.body.innerText : '',
          sw: document.documentElement.scrollWidth, iw: window.innerWidth,
          links: a,
          curbar: !!document.querySelector('.curbar'),
          money: document.querySelectorAll('.mny, .mnyt').length,
        };
    }""")
    if lang and not info["lang"].lower().startswith(lang):
        found.append(f"<html lang=\"{info['lang']}\"> на странице языка {lang}")
    known = KNOWN_CYR.get(path.split("?")[0])
    if lang in ("en", "de"):
        words = [w for w in CYR.findall(info["text"]) if w not in CYR_ALLOWED]
        if known and len(words) > CYR_MAX_WORDS:
            NOTES.add(f"{path.split('?')[0]}: {known}")
        elif len(words) > CYR_MAX_WORDS:
            uniq = list(dict.fromkeys(words))[:8]
            found.append(f"русский текст: {len(words)} слов — {', '.join(uniq)}")
    if lang:
        bad = []
        for h in info["links"]:
            if not h or h.startswith(("http", "#", "mailto:", "tel:")):
                continue
            hl = lang_of(h)
            # /map и /data без ?lang со страниц самих /map и /data — норма:
            # язык уже сохранён страницей (fca.lang).
            here = path.split("?")[0]
            if h.split("?")[0] in ("/map", "/data") and hl != lang and not (
                    hl is None and here in ("/map", "/data")):
                bad.append(h)
            elif re.match(r"^/(ru|en|de)(/|$)", h) and hl != lang:
                bad.append(h)
        if bad:
            found.append(f"ссылки на другой язык: {', '.join(sorted(set(bad))[:6])}")
    if width < 500 and info["sw"] > info["iw"] + 1:
        found.append(f"прокрутка вбок на телефоне: ширина {info['sw']} при окне {info['iw']}")
    if info["curbar"] and not info["money"]:
        found.append("переключатель валюты без сумм")
    if info["curbar"] and info["money"]:
        before = page.evaluate("() => [...document.querySelectorAll('.mny')].map(e => e.textContent)")
        btns = page.locator(".curbar button[data-cur]:not(.on)")
        if btns.count():
            btns.first.click()
            page.wait_for_timeout(300)
            after = page.evaluate("() => [...document.querySelectorAll('.mny')].map(e => e.textContent)")
            same = sum(1 for x, y in zip(before, after) if x == y and re.search(r"\d", x or ""))
            if same:
                found.append(f"валюта: {same} сумм не пересчитались")
    if shots:
        import pathlib
        p = pathlib.Path(shots)
        p.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root"
        page.screenshot(path=str(p / f"{name}-{width}.png"), full_page=False)
    return found + errors[:5]


def reference(base: str, expect: dict) -> list[str]:
    q = "&".join(f"{k}={v}" for k, v in REF.items())
    t0 = time.monotonic()
    with urllib.request.urlopen(f"{base}/api/route?{q}", timeout=120) as r:
        res = json.loads(r.read())
    dt = time.monotonic() - t0
    a = res.get("answer") or {}
    total, fare, dflt = a.get("cost_total"), a.get("breakeven_fare_eur"), res.get("default_share")
    print(f"эталон FRA–BCN A320: рейс {total:,.0f} EUR, безубыточный чек {fare:,.0f} EUR, "
          f"заготовка {dflt * 100:.0f} %, {dt * 1000:.0f} мс".replace(",", " "))
    out = []
    for key, got in (("total", total), ("fare", fare), ("default", dflt * 100 if dflt is not None else None)):
        want = expect.get(key)
        if want and got is not None and abs(got - want) / want > expect["tol"]:
            out.append(f"эталон: {key} {got:,.1f} против ожидаемых {want:,.1f} "
                       f"(допуск {expect['tol'] * 100:.0f} %)")
    if not a.get("feasible", True):
        out.append("эталон: рейс невыполним")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://flightcost.app")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true", help="ключевые страницы (по умолчанию)")
    g.add_argument("--full", action="store_true", help="все адреса из sitemap.xml")
    ap.add_argument("--shots", help="каталог для снимков экрана")
    ap.add_argument("--expect-total", type=float, default=20537, help="эталон: сумма рейса, EUR")
    ap.add_argument("--expect-fare", type=float, default=148, help="эталон: безубыточный чек, EUR")
    ap.add_argument("--expect-default", type=float, default=42, help="эталон: доля заготовки, %%")
    ap.add_argument("--tol", type=float, default=0.05)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    if a.full:
        paths = sitemap_paths(a.base)
    else:
        paths = [p.format(l=l) for p in QUICK for l in LANGS] + QUICK_PLAIN
    print(f"{a.base}: страниц {len(paths)} × 2 ширины")
    problems: dict[str, list[str]] = {}
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for path in paths:
            if path == "/healthz":
                continue
            for w in (1280, 390):
                ctx = br.new_context(locale="ru-RU", user_agent="Mozilla/5.0 fca-site-check")
                page = ctx.new_page()
                f = check_page(page, a.base, path, w, a.shots)
                ctx.close()
                if f:
                    problems.setdefault(path, []).extend(f"[{w}] {x}" for x in f)
            mark = "✗" if path in problems else "✓"
            print(f"  {mark} {path}")
        br.close()
    try:
        ref = reference(a.base, {"total": a.expect_total, "fare": a.expect_fare,
                                 "default": a.expect_default, "tol": a.tol})
        if ref:
            problems["эталон"] = ref
    except Exception as e:                                         # noqa: BLE001
        problems["эталон"] = [f"не посчитался: {e}"]
    print()
    for n in sorted(NOTES):
        print(f"известно: {n}")
    if not problems:
        print("находок нет")
        return 0
    print(f"находки на {len(problems)} страницах:")
    for p, fs in problems.items():
        print(f"\n{p}")
        for x in dict.fromkeys(fs):
            print(f"  · {x}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
