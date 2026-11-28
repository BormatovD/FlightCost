"""Render an offline review document. Only owner-approved snapshots become public."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import zipfile
from datetime import date
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

SEED_HASHES = {
    2: "1a9e354a27b58522bbecc40f4df4446801a0a0af9720fc3a6da62f0496a31f60",
    3: "41c1567fee66d7c3220b30d19f9a28e86193f6764f047c9d02d67ab473c51091",
    4: "831597d716297881e61f7d1b75684ae852f35ef27ee1481e36fa678cd5c7519e",
}
STYLE = """body{background:#0e0e0e;color:#e6e6e6;font:16px/1.6 'IBM Plex Sans',system-ui,sans-serif;margin:0}
main{max-width:56rem;margin:auto;padding:2rem clamp(1rem,4vw,3rem)}h1,h2{color:#fff;line-height:1.2}
h2{margin-top:2rem}a{color:#27b4f0}p,figcaption,td,th{overflow-wrap:anywhere}
figure{margin:1rem 0}img{max-width:100%;height:auto}figcaption{color:#aaa}table{border-collapse:collapse}
th,td{border-bottom:1px solid #444;text-align:left;padding:.4rem}.table-scroll{overflow:auto}"""


def article_slug(n):
    return f"demand-series-{n:02d}-2026-11"


def string(value, limit, field):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Invalid {field}")
    return value.strip()


def array(value, limit, field, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= limit:
        raise ValueError(f"Invalid {field}")
    return value


class EditableText(HTMLParser):
    """Match editorial edits only against visible text, keeping the trusted seed markup."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0] + [m.end() for m in re.finditer("\n", source)]
        self.visible = False
        self.skip = 0
        self.ranges = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.visible = True
        if tag in ("style", "script", "svg", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag == "body":
            self.visible = False
        if tag in ("style", "script", "svg", "noscript"):
            self.skip -= 1

    def handle_data(self, data):
        if self.visible and not self.skip:
            line, col = self.getpos()
            start = self.offsets[line-1] + col
            end = self.source.find("<", start)
            self.ranges.append((start, end if end >= 0 else len(self.source), data))


def seed_document(payload, n, archive):
    if payload.get("seed") != f"{n:02d}":
        raise ValueError("Missing editorial seed")
    with zipfile.ZipFile(archive) as z:
        data = z.read(f"{n:02d}/index.html")
        seed_tables = {}
        trend_csv = None
        if n == 2:
            for figure, name in {"scenario":"scenarios.csv", "backtest":"wape_backtest.csv",
                                 "spread":"spread.csv", "coverage":"coverage.csv", "transfer":"independent_od.csv"}.items():
                seed_tables[figure] = (name, base64.b64encode(z.read("02/" + name)).decode())
        if n == 3:
            trend_csv = base64.b64encode(z.read("03/illustrative-trend-2019-2025.csv")).decode()
    if hashlib.sha256(data).hexdigest() != SEED_HASHES[n]:
        raise ValueError("Seed does not match the reviewed editorial archive")
    page = data.decode()
    # The supplied article 02 links to five absent PNG files. Its own figures
    # already embed the same images. Make their download links work offline too.
    def fix_figure(match):
        fragment = match.group()
        img = re.search(r'<img\b[^>]*\bsrc="(data:image/png;base64,[A-Za-z0-9+/=]+)"', fragment)
        if img:
            fragment = re.sub(r'href="assets/([a-z0-9.-]+\.png)"',
                              lambda m: f'download="{m[1]}" href="{img[1]}"', fragment)
        key = re.search(r'<figure\b[^>]*\bid="fig-([a-z]+)"', fragment)
        if key and key[1] in seed_tables:
            name, content = seed_tables[key[1]]
            link = f' · <a download="{name}" href="data:text/csv;charset=utf-8;base64,{content}">Таблица CSV</a>'
            fragment = fragment.replace('</figcaption>', link + '</figcaption>', 1)
        if trend_csv and "Оранжевая линия — механическое продолжение" in fragment:
            link = (' · <a download="illustrative-trend-2019-2025.csv" href="data:text/csv;charset=utf-8;base64,'
                    + trend_csv + '">Данные линии тренда · CSV</a>')
            fragment = fragment.replace('</figcaption>', link + '</figcaption>', 1)
        return fragment
    page = re.sub(r"<figure\b[^>]*>.*?</figure>", fix_figure, page, flags=re.S)
    for edit in array(payload.get("edits", []), 250, "edits"):
        before = string(edit["before"], 10000, "before")
        after = string(edit["after"], 12000, "after")
        matches = []
        for start, end, part in EditableText(page).ranges:
            matches.extend((start,end,part) for _ in re.finditer(re.escape(before), part))
        if len(matches) != 1:
            raise ValueError("Each seed edit must identify one visible passage")
        start, end, part = matches[0]
        page = page[:start] + escape(part.replace(before,after,1), quote=False) + page[end:]
    # The Telegram caption, index metadata, and the offline document must
    # agree after an author requests a new headline or standfirst.
    def update_text(pattern, text):
        def sub(m):
            current = " ".join(unescape(re.sub(r"<[^>]*>", " ", m[2])).split())
            return m[0] if current == text else m[1]+escape(text)+m[3]
        return re.sub(pattern, sub, page, count=1, flags=re.S)
    page = update_text(r"(<h1\b[^>]*>)(.*?)(</h1>)", payload["title"].strip())
    page = update_text(r'(<p\b[^>]*class="hero-sub"[^>]*>)(.*?)(</p>)', payload["lede"].strip())
    return page


def render(payload, root):
    n = payload["article"]
    title = string(payload.get("title"), 240, "title")
    lede = string(payload.get("lede"), 1800, "lede")
    if n in SEED_HASHES:
        path = Path(os.environ.get("FCA_EDITORIAL_SEED_ZIP",
                                   root/"sources"/"flightcost-articles-02-04-editorial-v3.zip"))
        return seed_document(payload, n, path).encode()
    sections = array(payload.get("sections"), 40, "sections", 1)
    sources = array(payload.get("sources"), 80, "sources", 1)
    title_html = escape(title)
    parts = ['<!doctype html><html lang="ru"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width, initial-scale=1">'
             f'<title>{title_html}</title><style>{STYLE}</style></head><body><main>'
             f'<h1>{title_html}</h1><p>{escape(lede)}</p>']
    topics = Path(os.environ.get("FCA_EDITORIAL_TOPICS", root/"reference"/"topics"))
    for section in sections:
        parts.append(f'<h2>{escape(string(section.get("heading"), 400, "heading"))}</h2>')
        for para in array(section.get("paragraphs"), 80, "paragraphs", 1):
            parts.append(f"<p>{escape(string(para, 20000, 'paragraph'))}</p>")
        fig = section.get("figure")
        if fig:
            name = string(fig.get("asset"), 100, "figure filename")
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*\.png", name):
                raise ValueError("Invalid figure filename")
            png = (topics/f"{n:02d}"/"assets"/name).read_bytes()
            if len(png) > 5_000_000 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid figure")
            caption = escape(string(fig.get("caption"), 1200, "figure caption"))
            parts.append('<figure><img alt="" src="data:image/png;base64,' +
                         base64.b64encode(png).decode() + f'"><figcaption>{caption}</figcaption></figure>')
        tab = section.get("table")
        if tab:
            cols = array(tab.get("columns"), 20, "table columns", 1)
            parts.append('<div class="table-scroll"><table><thead><tr>' + ''.join(
                f'<th>{escape(string(c, 200, "column"))}</th>' for c in cols) + '</tr></thead><tbody>')
            for row in array(tab.get("rows"), 200, "table rows", 1):
                if not isinstance(row,list) or len(row) != len(cols) or any(type(x) not in (str,int,float) for x in row):
                    raise ValueError("Invalid table row")
                parts.append('<tr>' + ''.join(f'<td>{escape(str(x))}</td>' for x in row) + '</tr>')
            parts.append('</tbody></table></div>')
    parts.append('<h2>Источники</h2><ul>')
    for item in sources:
        label = string(item.get("label"), 500, "source label")
        url = string(item.get("url"), 2000, "source URL")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or any(c.isspace() for c in url):
            raise ValueError("Expected HTTPS source")
        parts.append(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>')
    parts.append('</ul></main></body></html>')
    result = ''.join(parts).encode()
    if len(result) > 15_000_000:
        raise ValueError("Article exceeds file-size limit")
    return result


def public_items(items):
    location = os.environ.get("FCA_EDITORIAL_PUBLISHED")
    if not location:
        return items
    by_slug = {item["slug"]: item for item in items}
    for number in range(2, 19):
        slug = article_slug(number)
        # Only a planned entry in the public registry can expose an archived issue.
        old = by_slug.get(slug)
        if old is None or not old.get("planned_release"):
            continue
        folder = Path(location)/f"{number:02d}"
        try:
            meta = json.loads((folder/"article.json").read_bytes())
            date.fromisoformat(meta["date"])
            title = string(meta["title"], 240, "title")
            lede = string(meta["lede"], 1800, "lede")
            if meta["article"] != number or not (folder/"report.html").is_file():
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        by_slug[slug] = {**old, "slug":slug, "path":folder/"report.html", "lang":"ru", "langs":["ru"],
                         "date":meta["date"], "title":title, "lede":lede, "calc":"planned",
                         "tags":old.get("tags", {"ru":["прогноз","пассажирский спрос"]}), "site_chrome":True,
                         "planned_release":False, "hide_from_feed":False}
    return list(by_slug.values())
