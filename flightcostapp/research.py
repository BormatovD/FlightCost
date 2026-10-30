"""Исследования на сайте (решение 233): лента отчётов и сами отчёты.

Отчёт — самодостаточный HTML из папки `research/<slug>/` (тот же, что
лежит в репозитории рядом с журналами поиска). Сервер публикует его как
есть и добавляет только шапку сайта, канонический адрес, описание и
значок — поэтому отчёт одинаково открывается и с диска, и на сайте.
Список и подписи на трёх языках — `research/index.yaml`.
"""

from __future__ import annotations

import pathlib
import re
from datetime import date

import yaml

from . import seo
from .seo import LANGS, T, esc, site

ROOT = pathlib.Path(__file__).resolve().parents[1] / "research"
INDEX = ROOT / "index.yaml"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")

TXT = {
    "ru": {"h": "Исследования", "title": "Исследования — FlightCost",
           "lead": ("Что мы выяснили, пока собирали данные для калькулятора: каждая цифра — с источником и "
                    "проверенной цитатой, журналы поиска и данные — в открытом репозитории."),
           "read": "Читать отчёт →", "journal": "журнал и данные", "lang_note": "",
           "sources": "Источники", "empty": "Пока ничего не опубликовано.", "feed": "Лента (Atom)"},
    "en": {"h": "Research", "title": "Research — FlightCost",
           "lead": ("What we found while collecting data for the calculator: every number comes with a source and a "
                    "verified quote; search logs and data are in the open repository."),
           "read": "Read the report →", "journal": "log and data", "lang_note": "report in Russian",
           "sources": "Sources", "empty": "Nothing published yet.", "feed": "Feed (Atom)"},
    "de": {"h": "Recherchen", "title": "Recherchen — FlightCost",
           "lead": ("Was wir beim Sammeln der Daten für den Rechner herausgefunden haben: jede Zahl mit Quelle und "
                    "geprüftem Zitat; Suchprotokolle und Daten liegen im offenen Repository."),
           "read": "Bericht lesen →", "journal": "Protokoll und Daten", "lang_note": "Bericht auf Russisch",
           "sources": "Quellen", "empty": "Noch nichts veröffentlicht.", "feed": "Feed (Atom)"},
}
# Маркер связи статьи с расчётом — поле `calc` в index.yaml (те же значки в самих
# статьях, research/_report.py): уже в расчёте / учесть при вводе / в очереди.
CALC = {"in_calc": ("✓", "var(--green)", {"ru": "Уже в расчёте", "en": "Built into the calculator",
                                           "de": "Im Rechner enthalten"}),
        "on_input": ("⚑", "var(--sky)", {"ru": "Учесть при вводе", "en": "Mind when entering data",
                                          "de": "Bei der Eingabe beachten"}),
        "planned": ("◷", "var(--dim)", {"ru": "В очереди на расчёт", "en": "Queued for the calculator",
                                         "de": "Für den Rechner geplant"})}
LEGEND = {"ru": ("уже в расчёте — калькулятор учитывает по умолчанию", "учесть при вводе — расчёт учтёт ваши данные, "
                 "статья подскажет, что держать в голове", "в очереди — выводы ещё не внесены в калькулятор"),
          "en": ("built in — the calculator accounts for it by default", "mind when entering data — the calculation "
                 "uses your inputs, the article says what to keep in mind", "queued — not in the calculator yet"),
          "de": ("im Rechner — standardmäßig berücksichtigt", "bei der Eingabe beachten — die Rechnung nutzt Ihre "
                 "Eingaben, der Artikel sagt, worauf zu achten ist", "geplant — noch nicht im Rechner")}


def calc_mark(it: dict, lang: str) -> str:
    c = CALC.get(str(it.get("calc") or ""))
    if not c:
        return ""
    ic, col, lab = c
    return f'<span class="cm" style="color:{col}">{ic} {esc(lab[lang])}</span>'


MONTHS = {"ru": "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split(),
          "en": "January February March April May June July August September October November December".split(),
          "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split()}


def items() -> list[dict]:
    """Опубликованные исследования, новые сверху; без файла отчёта — не показываются."""
    if not INDEX.exists():
        return []
    doc = yaml.safe_load(INDEX.read_text(encoding="utf-8")) or {}
    out = []
    for it in doc.get("items") or []:
        slug = str(it.get("slug") or "")
        rep = ROOT / str(it.get("report") or "")
        if not SLUG.match(slug) or not rep.is_file() or ROOT not in rep.resolve().parents:
            continue
        if it.get("draft"):           # не прошло моделирование владельцем (PROCESS.md)
            continue
        # Переводы лежат рядом: report.en.html, report.de.html (research/_report.py).
        langs = [str(it.get("lang") or "ru")] + [lg for lg in LANGS if lg != it.get("lang")
                                                  and rep.with_name(f"{rep.stem}.{lg}.html").is_file()]
        out.append({**it, "slug": slug, "path": rep, "date": str(it.get("date") or ""), "langs": langs})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def report_file(it: dict, lang: str):
    """Файл отчёта на языке страницы; перевода нет — оригинал (с пометкой языка)."""
    if lang != it.get("lang") and lang in it.get("langs", []):
        return it["path"].with_name(f"{it['path'].stem}.{lang}.html")
    return it["path"]


def find(slug: str) -> dict | None:
    return next((x for x in items() if x["slug"] == slug), None)


def _tr(it: dict, key: str, lang: str):
    v = it.get(key) or {}
    return v.get(lang) or v.get("en") or v.get("ru") if isinstance(v, dict) else v


def human_date(d: str, lang: str) -> str:
    try:
        x = date.fromisoformat(d)
    except ValueError:
        return d
    m = MONTHS[lang][x.month - 1]
    return f"{m} {x.day}, {x.year}" if lang == "en" else f"{x.day}{'.' if lang == 'de' else ''} {m} {x.year}"


STYLE = """<style>
.rlist{display:grid;gap:14px;margin:18px 0}
.rcard{display:block;border:1px solid var(--line);border-radius:10px;padding:16px 18px;background:var(--panel);
  text-decoration:none;color:var(--ink)}
.rcard:hover{border-color:var(--accent)}
.rcard time{font-size:12.5px;color:var(--dim)}
.rcard h2{margin:4px 0 6px;font-size:19px}
.rcard p{margin:0 0 8px;color:var(--ink)}
.rcard .tg span{display:inline-block;font-size:11.5px;color:var(--dim);border:1px solid var(--line);border-radius:10px;
  padding:1px 8px;margin:0 6px 4px 0}
.rcard .go{font-weight:600;color:var(--ink2)}.rcard .ln{font-size:12px;color:var(--dim);margin-left:8px}
.rfoot{font-size:13px;color:var(--dim)}
.cm{display:inline-block;font-weight:600;font-size:12px;border:1px solid currentColor;border-radius:999px;padding:1px 9px;
  margin-left:8px;vertical-align:1px}
.rleg{font-size:12.5px;color:var(--dim);margin:-6px 0 4px}.rleg span{margin-right:14px}
</style>"""


def index_page(lang: str) -> str:
    t, x = T[lang], TXT[lang]
    cards = []
    for it in items():
        tags = "".join(f"<span>{esc(g)}</span>" for g in (_tr(it, "tags", lang) or []))
        note = (f'<span class="ln">{esc(x["lang_note"])}</span>'
                if lang not in it.get("langs", [it.get("lang")]) and x["lang_note"] else "")
        cards.append(f'<a class="rcard" href="/{lang}/research/{it["slug"]}">'
                     f'<time datetime="{esc(it["date"])}">{esc(human_date(it["date"], lang))}</time>{calc_mark(it, lang)}'
                     f'<h2>{esc(_tr(it, "title", lang))}</h2><p>{esc(_tr(it, "lede", lang))}</p>'
                     f'<div class="tg">{tags}</div><span class="go">{esc(x["read"])}</span>{note}</a>')
    body = [f'<div class="crumbs"><a href="/{lang}/">FlightCost</a> › {esc(x["h"])}</div>',
            f"<h1>{esc(x['h'])}</h1>", f'<p class="lead">{esc(x["lead"])}</p>',
            '<p class="rleg">' + "".join(f'<span style="color:{CALC[k][1]}">{CALC[k][0]} {esc(t)}</span>'
                                        for k, t in zip(CALC, LEGEND[lang])) + "</p>",
            f'<div class="rlist">{"".join(cards) or esc(x["empty"])}</div>',
            f'<p class="rfoot"><a href="/research/feed.xml">{esc(x["feed"])}</a> · '
            f'<a href="{seo.REPO}/tree/main/research">GitHub — {esc(x["journal"])}</a></p>']
    h = seo.head(lang, x["title"], x["lead"], f"{site()}/{lang}/research", seo.alternates("/research"),
                 [seo.crumbs_ld([("FlightCost", f"{site()}/{lang}/"), (x["h"], f"{site()}/{lang}/research")])])
    return seo.shell(lang, "/research", h + STYLE, "\n".join(body), on="research")


def report_page(lang: str, it: dict) -> str:
    """Отчёт как есть + шапка сайта, канонический адрес, описание, значок."""
    page = report_file(it, lang).read_text(encoding="utf-8")
    title = _tr(it, "title", lang)
    desc = _tr(it, "lede", lang) or ""
    canon = f"{site()}/{lang}/research/{it['slug']}"
    meta = (f'<link rel="canonical" href="{esc(canon)}">'
            f'<meta name="description" content="{esc(desc[:300])}">'
            + "".join(f'<link rel="alternate" hreflang="{h}" href="{esc(u)}">'
                      for h, u in seo.alternates(f"/research/{it['slug']}"))
            + f'<meta property="og:type" content="article"><meta property="og:title" content="{esc(title)}">'
            f'<meta property="og:description" content="{esc(desc[:300])}"><meta property="og:url" content="{esc(canon)}">'
            f'<meta property="og:image" content="{site()}/og.png"><meta name="twitter:card" content="summary_large_image">'
            + seo.ICON_LINKS)
    page = page.replace("</head>", meta + "</head>", 1)
    # Шапка сайта — та же, что на остальных страницах (её стили — в ui.css,
    # который отчёт вшивает целиком); крошки — над заголовком отчёта.
    x = TXT[lang]
    bar = (seo.site_header(lang, "research", f"/research/{it['slug']}")
           + f'<div style="max-width:1060px;margin:14px auto 0;padding:0 22px;font-size:12.5px;color:var(--dim)">'
           f'<a style="color:var(--dim)" href="/{lang}/">FlightCost</a> › '
           f'<a style="color:var(--dim)" href="/{lang}/research">{esc(x["h"])}</a>'
           + (f' · {esc(x["lang_note"])}' if lang not in it.get("langs", [it.get("lang")]) and x["lang_note"]
              else "") + "</div>")
    return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + bar, page, count=1)


def feed() -> str:
    """Atom-лента исследований — «как новости»: читалки и агрегаторы."""
    its = items()
    upd = (its[0]["date"] if its else str(date.today())) + "T00:00:00Z"
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">',
           "<title>FlightCost — research</title>", f'<link href="{site()}/en/research"/>',
           f'<link rel="self" href="{site()}/research/feed.xml"/>', f"<id>{site()}/research</id>",
           f"<updated>{upd}</updated>"]
    for it in its:
        for lg in LANGS:
            u = f"{site()}/{lg}/research/{it['slug']}"
            out.append(f"<entry><title>{esc(_tr(it, 'title', lg))}</title><link href=\"{u}\"/><id>{u}</id>"
                       f"<updated>{it['date']}T00:00:00Z</updated><summary>{esc(_tr(it, 'lede', lg))}</summary>"
                       f"<author><name>FlightCost</name></author></entry>")
    out.append("</feed>")
    return "\n".join(out)
