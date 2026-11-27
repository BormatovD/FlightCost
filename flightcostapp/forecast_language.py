"""Presentation translations for the published forecast and its lazy-loaded research data."""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path

WEB = Path(__file__).with_name("web")
# The static report body before its data contains editorial markup and download links.
# Keep scripts, addresses, model identifiers and original spreadsheet names intact.
TOKENS = re.compile(r"(<(?:script|style)\b[^>]*>.*?</(?:script|style)>|<!--.*?-->|<[^>]+>)", re.I | re.S)
ATTRIBUTES = re.compile(r'\b(aria-label|aria-description|title|alt|placeholder)="([^"]*)"')


@lru_cache(maxsize=2)
def catalogue(lang: str):
    messages = json.loads((WEB / f"forecast-messages-{lang}.json").read_text(encoding="utf-8"))
    script = (WEB / "forecast-language.js").read_text(encoding="utf-8")
    chart = (WEB / "forecast-payload-chart.js").read_text(encoding="utf-8")
    payload = json.dumps(messages, ensure_ascii=False, separators=(",", ":")).replace("<", r"\u003c")
    loader = f'<script id="forecast-messages" type="application/json">{payload}</script><script>{script}\n{chart}</script>'
    return messages["text"], loader


def localize_intro(head: bytes, lang: str) -> bytes:
    messages, loader = catalogue(lang)

    def translate(raw: str) -> str:
        key = " ".join(html.unescape(raw).split())
        if not key or key not in messages:
            return raw
        return re.sub(r"\S(?:[\s\S]*\S)?", lambda _: html.escape(messages[key], quote=True), raw, count=1)

    before, body, intro = head.decode("utf-8").partition("<body>")
    before = re.sub(r"<title>(.*?)</title>", lambda m: "<title>" + translate(m[1]) + "</title>", before, count=1)
    before = before.replace("<head>", "<head>" + loader, 1)
    pieces = TOKENS.split(intro)
    for i, piece in enumerate(pieces):
        if i % 2 == 0:
            pieces[i] = translate(piece)
        elif not piece.lower().startswith(("<script", "<style", "<!--")):
            pieces[i] = ATTRIBUTES.sub(lambda m: f'{m[1]}="{translate(m[2])}"', piece)
    return (before + body + "".join(pieces)).encode("utf-8")
