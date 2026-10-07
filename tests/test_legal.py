"""Impressum и политика конфиденциальности держатся на коде, а не на словах.

Политика обещает конкретные вещи: страница не тянет ничего с чужих
серверов, в браузере хранится только выбор языка, журнал пишет усечённый
адрес и без заголовков, полный адрес живёт в памяти не дольше двух минут.
Каждое обещание здесь проверено. Если тест упал — либо чините код, либо
меняйте текст /datenschutz, но не одно без другого.
"""

from __future__ import annotations

import pathlib
import re
import threading
import unittest
from unittest import mock

from flightcostapp import serve

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "flightcostapp" / "web"
PAGES = ("impressum", "datenschutz")

# Всё, что браузер грузит сам, без клика: скрипты, стили, картинки,
# шрифты, запросы из кода. Обычная ссылка <a href="https://…"> сюда не
# попадает — по ней ничего не уходит, пока посетитель не нажмёт.
EXTERNAL_LOAD = [
    re.compile(r'\b(?:src|action|poster)\s*=\s*["\']?(?:https?:)?//', re.I),
    re.compile(r'<link\b[^>]*\bhref\s*=\s*["\']?(?:https?:)?//', re.I),
    re.compile(r'url\(\s*["\']?(?:https?:)?//', re.I),
    re.compile(r'@import\b', re.I),
    re.compile(r'\b(?:fetch|EventSource|WebSocket|sendBeacon)\s*\(\s*["\'`](?:https?:|wss?:)?//', re.I),
    re.compile(r'<iframe\b', re.I),
]


def _scripts(html: str) -> str:
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def _front_sources() -> dict[str, str]:
    """Всё, что уходит в браузер: страницы, модули и сгенерированный CSS."""
    out = {p.name: p.read_text(encoding="utf-8")
           for p in [WEB / "serve.html", *(WEB / f"{k}.html" for k in PAGES),
                     WEB / "geo.js", WEB / "globe.js"] if p.exists()}
    try:
        from flightcostapp.ui import css
        out["ui.css"] = css(inline_fonts=False)
    except ImportError:
        pass
    return out


class LegalPages(unittest.TestCase):

    def test_placeholders_are_exactly_the_fields(self):
        used = set()
        for k in PAGES:
            used |= set(re.findall(r"\{\{(\w+)\}\}",
                                   (WEB / f"{k}.html").read_text(encoding="utf-8")))
        self.assertEqual(used, set(serve.LEGAL_FIELDS),
                         "поле в legal.json без места на странице или наоборот")

    def test_values_are_filled_and_escaped(self):
        vals = {k: "x" for k in serve.LEGAL_FIELDS}
        vals["name"] = "<b>Max & Co</b>"
        for k in PAGES:
            page = serve._legal_page(k, vals).decode("utf-8")
            self.assertNotIn("{{", page)
            self.assertNotIn("не заполнено", page)
            self.assertNotIn("<b>Max", page)
        self.assertIn("&lt;b&gt;Max &amp; Co&lt;/b&gt;",
                      serve._legal_page("impressum", vals).decode("utf-8"))

    def test_missing_value_is_visible_not_blank(self):
        """Пустой Impressum выглядит готовым — поэтому пустоты нет."""
        page = serve._legal_page("impressum", {}).decode("utf-8")
        self.assertIn("[name: не заполнено]", page)

    def test_legal_json_has_no_unknown_keys(self):
        extra = set(serve._legal_values()) - set(serve.LEGAL_FIELDS)
        self.assertFalse(extra, f"лишние ключи в legal.json: {extra}")

    def test_translations_keep_structure(self):
        """Немецкая версия обязательна, переводы — её копии по разделам.

        Раздел, дописанный в одну версию и забытый в другой, — это две
        разные политики на одной странице.
        """
        for k in PAGES:
            page = (WEB / f"{k}.html").read_text(encoding="utf-8")
            secs = dict(re.findall(r'<section lang="(\w+)"[^>]*>(.*?)</section>', page, re.S))
            self.assertEqual(set(secs), {"de", "en", "ru"}, k)
            counts = {lang: body.count("<h2>") for lang, body in secs.items()}
            self.assertEqual(len(set(counts.values())), 1, f"{k}: разделов {counts}")

    def test_pages_reachable_from_showcase(self):
        html = (WEB / "serve.html").read_text(encoding="utf-8")
        for k in PAGES:
            self.assertIn(f'href="/{k}"', html)


class PrivacyPromises(unittest.TestCase):
    """Пункты 2, 4, 5, 6 политики."""

    def test_no_third_party_requests(self):
        for name, text in _front_sources().items():
            for rx in EXTERNAL_LOAD:
                m = rx.search(text)
                self.assertIsNone(
                    m, f"{name}: загрузка с чужого сервера ({m and m.group(0)!r}) — "
                       f"политика обещает, что её нет")

    def test_browser_keeps_only_language(self):
        for name, text in _front_sources().items():
            code = _scripts(text) if name.endswith(".html") else text
            self.assertNotIn("document.cookie", code, name)
            self.assertNotIn("sessionStorage", code, name)
            self.assertNotIn("indexedDB", code, name)
            uses = re.findall(r"localStorage\b(.{0,40})", code)
            for tail in uses:
                self.assertRegex(tail, r'^\.(?:get|set|remove)Item\(\s*"fca\.lang"',
                                 f"{name}: localStorage сверх fca.lang — допишите политику")

    def test_access_log_matches_policy(self):
        caddy = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
        log = caddy[caddy.index("log {"):]
        for must in ("request>remote_ip ip_mask", "request>client_ip ip_mask",
                     "ipv4 24", "ipv6 48", "request>headers delete",
                     "roll_keep_for 7d"):
            self.assertIn(must, log, f"Caddyfile без «{must}», а политика его обещает")

    def test_rate_limiter_forgets_addresses(self):
        ctx = serve.Context.__new__(serve.Context)
        ctx.public = True
        ctx._rl, ctx._rl_lock, ctx._rl_swept = {}, threading.Lock(), 0.0
        clock = [1000.0]
        with mock.patch("time.monotonic", lambda: clock[0]):
            for _ in range(ctx.HEAVY_PER_MIN):
                self.assertTrue(ctx.allow("203.0.113.7"))
            self.assertFalse(ctx.allow("203.0.113.7"), "лимит не сработал")
            clock[0] += 121                       # две минуты с запасом
            ctx.allow("198.51.100.1")             # метла по запросу
            self.assertNotIn("203.0.113.7", ctx._rl,
                             "полный адрес пережил две минуты в памяти")
            clock[0] += 91                        # метла по часам: окно + шаг
            with ctx._rl_lock:
                ctx._rl_sweep(clock[0])
            self.assertFalse(ctx._rl, "без новых запросов адрес остался в памяти")


if __name__ == "__main__":
    unittest.main(verbosity=2)
