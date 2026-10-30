"""Общее для отчётов исследований: числа по-русски, рисунки, оформление сайта.

Отчёт — самодостаточный HTML: стили и шрифты сайта вшиты (flightcostapp.ui.css),
внешних запросов нет; на сайте его публикует раздел «Исследования» (решение 233).
"""

from __future__ import annotations

import html
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flightcostapp.ui import css  # noqa: E402

e = html.escape

# ---------- языки ----------
# Статья собирается на трёх языках: сборщик вызывает `set_lang` и строит её
# заново; `T(ru, en, de)` выбирает текст, `n` форматирует число по языку.
# Русский — report.html, остальные — report.<язык>.html рядом.
LANGS = ("ru", "en", "de")
LANG = "ru"


def set_lang(lang: str) -> None:
    global LANG
    assert lang in LANGS, lang
    LANG = lang


def T(ru: str, en: str, de: str) -> str:
    return {"ru": ru, "en": en, "de": de}[LANG]


def out_name(lang: str) -> str:
    return "report.html" if lang == "ru" else f"report.{lang}.html"


class Tr:
    """Перевод строк, пришедших из данных исследования (пробелы, сомнения, названия):
    `<папка>/i18n.yaml` — {русская строка: {en: …, de: …}}. Нет перевода — русский
    текст и запись в `missing` (сборщик печатает список, чтобы его дописать)."""

    def __init__(self, folder):
        import yaml
        f = pathlib.Path(folder) / "i18n.yaml"
        self.d = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}
        self.missing: set = set()

    def __call__(self, s):
        if LANG == "ru" or not s:
            return s
        v = (self.d.get(s) or {}).get(LANG)
        if not v:
            self.missing.add(s)
            return s
        return v


def n(x, d=0, sign=False):
    """Число по языку статьи: ru «1 234,5», en «1,234.5», de «1.234,5»; минус — «−»;
    sign — «+» у положительных."""
    if x is None:
        return "—"
    s = f"{x:,.{d}f}"
    if LANG == "ru":
        s = s.replace(",", "\u00a0").replace(".", ",")
    elif LANG == "de":
        s = s.replace(",", "\u0001").replace(".", ",").replace("\u0001", ".")
    return ("+" if sign and round(x, d) > 0 else "") + s.replace("-", "−")


# ---------- валюта ----------
# Деньги, посчитанные нами, помечаются `money(...)`: на странице их можно
# показать в EUR, USD, RUB, INR или CNY (переключатель под заголовком; выбор
# общий с калькулятором — localStorage «fca.cur»). Курс: на сайте — тот же,
# что у калькулятора (/api/fx: ЕЦБ, ЦБ РФ, с датой), с диска — вшитый снимок
# research/_fx.json с его датой. Цифры из первоисточников (цитаты, ставки
# тарифов, графики) остаются в валюте документа.
CURS = ("EUR", "USD", "RUB", "INR", "CNY")


def money(v, cur="EUR", d=0, sign=False, unit="", nc=False, tag="span") -> str:
    """Наша расчётная сумма, которую переключатель валюты пересчитывает.
    nc — без кода валюты (подписи рисунков, ячейки под общим заголовком: код валюты стоит в
    подписи через `curname`); tag="tspan" — внутри SVG."""
    if v is None:
        return "—"
    code = "" if nc else f" {cur}{e(unit)}"
    return (f'<{tag} class="mny" data-v="{v:.6g}" data-c="{cur}" data-d="{d}" data-s="{int(sign)}" '
            f'data-u="{e(unit)}"{" data-nc=1" if nc else ""}>{n(v, d, sign)}{code}</{tag}>')


def curname(cur="EUR", tag="span") -> str:
    """Код валюты в подписи рисунка или заголовке столбца — меняется вместе с переключателем."""
    return f'<{tag} class="mcur" data-c="{cur}">{cur}</{tag}>'


def _fx() -> dict:
    import json
    return json.loads((pathlib.Path(__file__).resolve().parent / "_fx.json").read_text(encoding="utf-8"))


def cur_bar() -> str:
    fx = _fx()
    lab = T("Валюта", "Currency", "Währung")
    orig = T("как в источнике", "as in the source", "wie in der Quelle")
    note = T(f"курс на {fx['as_of']}, на сайте — актуальный", f"rate as of {fx['as_of']}, live on the website",
             f"Kurs vom {fx['as_of']}, auf der Website aktuell")
    opts = "".join(f'<button type="button" data-cur="{c}">{c}</button>' for c in CURS)
    return (f'<div class="curbar"><span>{lab}:</span><button type="button" data-cur="" class="on">{orig}</button>'
            f'{opts}<span class="curnote" title="{e(fx.get("source", ""))}">{note}</span></div>')


CUR_CSS = """<style>.curbar{display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;font-size:12.5px;color:var(--dim);
margin:-8px 0 16px}.curbar button{font:inherit;color:var(--dim);background:none;border:1px solid var(--line);
border-radius:999px;padding:1px 9px;cursor:pointer}.curbar button.on{color:var(--ink);border-color:var(--sky)}
.curnote{margin-left:4px}.mny.cv{border-bottom:1px dotted var(--dim)}.verdict b .mny{font-size:inherit;color:inherit}</style>"""


def cur_js() -> str:
    import json
    fx = _fx()
    loc = {"ru": "ru-RU", "en": "en-US", "de": "de-DE"}[LANG]
    return """<script>(function(){
var R=%s,LOC=%s,cur="";
function fmt(v,d,s){var t=new Intl.NumberFormat(LOC,{minimumFractionDigits:d,maximumFractionDigits:d}).format(v);
t=t.replace(/-/g,"\u2212");return (s&&v>0?"+":"")+t;}
function show(c){cur=c;document.querySelectorAll(".curbar button").forEach(function(b){
b.classList.toggle("on",(b.getAttribute("data-cur")||"")===c);});
document.querySelectorAll(".mny").forEach(function(m){var v=+m.dataset.v,s=m.dataset.c,d=+m.dataset.d,u=m.dataset.u||"";
var to=c&&R[c]&&R[s]?c:s;var x=to===s?v:v/R[s]*R[to];var dd=to===s?d:(Math.abs(x)>=100?0:d);
var nc=m.hasAttribute("data-nc");m.textContent=fmt(x,dd,m.dataset.s==="1")+(nc?"":" "+to+u);
if(m.classList)m.classList.toggle("cv",to!==s&&!nc);
if(!nc)m.title=to!==s?fmt(v,d,false)+" "+s:"";});
document.querySelectorAll(".mcur").forEach(function(m){var s=m.dataset.c;m.textContent=c&&R[c]&&R[s]?c:s;});}
document.querySelectorAll(".curbar button").forEach(function(b){b.addEventListener("click",function(){
var c=b.getAttribute("data-cur")||"";try{localStorage.setItem("fca.cur",c||"")}catch(e){}show(c);});});
var saved="";try{saved=localStorage.getItem("fca.cur")||""}catch(e){}
show(saved);
if(location.protocol.indexOf("http")===0){fetch("/api/fx").then(function(r){return r.json()}).then(function(q){
for(var k in q.rates){if(q.rates[k]&&q.rates[k].rate)R[k]=q.rates[k].rate;}R.EUR=1;
var n=document.querySelector(".curnote");if(n&&q.as_of)n.textContent=n.textContent.replace(/\\d{4}-\\d{2}-\\d{2}/,q.as_of);
show(cur);}).catch(function(){});}
})();</script>""" % (json.dumps(fx["rates"]), json.dumps(loc))


def pct(x, d=1):
    return "—" if x is None else n(x * 100, d) + "%"


def line_chart(series, *, w=640, h=260, ylab="", yfmt=lambda v: n(v), x_every=2, cur=None):
    """series: [(подпись, цвет, {x: y}, пунктир)]. Ось X — общие ключи.
    cur — валюта оси Y: подписи шкалы пересчитываются переключателем, код валюты в подписи оси
    (ylab с «{cur}» на месте кода)."""
    if cur:
        yfmt = lambda v: money(v, cur, nc=True, tag="tspan")  # noqa: E731
    xs = sorted({int(k) for _, _, s, _ in series for k in s})
    ys = [v for _, _, s, _ in series for v in s.values()]
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    L, T, B = (62 if cur else 46), 14, 28   # пересчитанные в рубли и рупии подписи шире
    R = max(118, 8 * max(len(nm) for nm, *_ in series) + 12)
    X = lambda x: L + (x - xs[0]) / ((xs[-1] - xs[0]) or 1) * (w - L - R)   # noqa: E731
    Y = lambda y: T + (hi - y) / (hi - lo) * (h - T - B)                     # noqa: E731
    g = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{yfmt(v)}</text>')
    for x in xs:
        if (x - xs[0]) % x_every == 0 or x == xs[-1]:
            g.append(f'<text x="{X(x):.1f}" y="{h - 8}" text-anchor="middle" class="ax">{x}</text>')
    labs = []
    for name, col, s, dash in series:
        pts = sorted((int(k), v) for k, v in s.items())
        d = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in pts)
        da = ' stroke-dasharray="5 4"' if dash else ""
        g.append(f'<polyline points="{d}" fill="none" stroke="{col}" stroke-width="2"{da}/>')
        x, y = pts[-1]
        labs.append([Y(y) + 4, X(x) + 6, col, name])
    # Подписи концов линий не должны наезжать друг на друга: раздвигаются по вертикали
    # (только подписи с близким x — у линий разной длины они и так разнесены).
    labs.sort()
    for i in range(1, len(labs)):
        near = abs(labs[i][1] - labs[i - 1][1]) < 8 * max(len(labs[i][3]), len(labs[i - 1][3]))
        if near and labs[i][0] - labs[i - 1][0] < 15:
            labs[i][0] = labs[i - 1][0] + 15
    for ty, tx, col, name in labs:
        g.append(f'<text x="{tx:.1f}" y="{ty:.1f}" class="lab" fill="{col}">{e(name)}</text>')
    if ylab:
        lab = e(ylab).replace("{cur}", curname(cur, "tspan")) if cur else e(ylab)
        g.append(f'<text x="{L}" y="{T - 2}" class="ax">{lab}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">{"".join(g)}</svg>'


def bars(rows, fmt=pct):
    top = max(v for _, v, _ in rows) or 1
    out = []
    for lab, v, sub in rows:
        out.append(f'<div class="bar"><span class="bn">{e(lab)}</span><div class="track"><div class="fill" '
                   f'style="width:{v / top * 100:.1f}%"></div></div><div class="val">{fmt(v)}'
                   f'{f"<small>{e(sub)}</small>" if sub else ""}</div></div>')
    return f'<div class="bars">{"".join(out)}</div>'


EXTRA = """
.doc{background:var(--bg);color:var(--ink);font:15px/1.6 var(--sans);margin:0}
.wrap{max-width:1060px;margin:0 auto;padding:34px 22px 70px}
h1{font-size:clamp(26px,3.4vw,38px);line-height:1.12;color:var(--ink2);margin:0 0 12px;font-weight:600}
h2{font-size:22px;color:var(--ink2);margin:0 0 10px;font-weight:600}
h3{font-size:15.5px;color:var(--ink2);margin:20px 0 6px;font-weight:600}
section{border-top:1px solid var(--line);padding:30px 0 8px}
p,li{max-width:80ch}.lede{font-size:16.5px;color:var(--ink)}.lede b{color:var(--ink2)}
.small,.meta{font-size:13px;color:var(--dim)}
code{font:12.5px var(--mono);color:var(--ink2)}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:8px 0 12px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;color:var(--dim);font-weight:600;font-size:12px;padding:7px 10px;border-bottom:1px solid var(--line);background:var(--panel)}
td{padding:6px 10px;border-bottom:1px solid var(--line2);vertical-align:top}
td:first-child{white-space:nowrap}
td.r,th.r{text-align:right;white-space:nowrap}td.s{font-size:12px;color:var(--dim)}
tr.dimrow td{color:var(--dim)}
.grid2{display:grid;grid-template-columns:1.2fr 1fr;gap:26px;align-items:start}
.chart{width:100%;height:auto}.chart .ax{font:11px var(--sans);fill:var(--dim)}.chart .lab{font:12px var(--sans);font-weight:600}
.bars{display:grid;gap:8px;margin:12px 0}
.bar{display:grid;grid-template-columns:140px 1fr 190px;gap:10px;align-items:center;font-size:13.5px}
.track{height:10px;background:var(--raise);border-radius:5px;overflow:hidden}.fill{height:100%;background:var(--sky)}
.val{font-weight:600;color:var(--ink2)}.val small{display:block;font-weight:400;color:var(--dim);font-size:12px}
.kv{display:grid;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.kv div{display:flex;justify-content:space-between;gap:12px;font-size:13.5px}.kv span{color:var(--dim)}.kv b{color:var(--ink2)}
details{margin:8px 0}summary{cursor:pointer;color:var(--ink2)}
.verdict{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:18px 0 6px}
.verdict div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.verdict b{display:block;color:var(--ink2);font-size:15px;margin-bottom:4px}.verdict span{font-size:13px;color:var(--dim)}
@media(max-width:760px){.grid2{grid-template-columns:1fr}.bar{grid-template-columns:96px 1fr 120px}.wrap{padding:22px 16px 50px}}
"""



def page(title: str, body: str) -> str:
    js = cur_js() if 'class="mny"' in body else ""
    return (f'<!doctype html><html lang="{LANG}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title>'
            f'<style>{css(inline_fonts=True)}{EXTRA}</style>{CUR_CSS}</head>'
            f'<body class="doc"><div class="wrap">{body}</div>{js}</body></html>')


class Sources:
    """Ссылки [n] на источники по шагам журналов `trace/*.jsonl` папки исследования.

    `cite("a1-017", "o1-073")` → верхний индекс со ссылками; один адрес — один
    номер, номера — по порядку первого упоминания; `html()` — список в конце."""

    def __init__(self, folder):
        import json as _json
        self.step, self.num, self.title = {}, {}, {}
        for f in sorted(pathlib.Path(folder).glob("trace/*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    o = _json.loads(line)
                except ValueError:
                    continue
                if o.get("url"):
                    self.step[o["id"]] = (o["url"], o.get("title") or "")

    def url(self, url, title=""):
        """Источник без шага журнала (например, документ, открытый владельцем)."""
        if url not in self.num:
            self.num[url] = len(self.num) + 1
            self.title[url] = title
        return self.num[url]

    def cite(self, *ids) -> str:
        nums = []
        for i in ids:
            if i.startswith("http"):
                k = self.url(i)
            elif i in self.step:
                k = self.url(*self.step[i])
            else:
                continue
            if k not in nums:
                nums.append(k)
        if not nums:
            return ""
        return "<sup class=cite>" + ",".join(f'<a href="#src{k}">{k}</a>' for k in sorted(nums)) + "</sup>"

    def html(self) -> str:
        return (f'<details><summary>{T("Источники", "Sources", "Quellen")} ({len(self.num)})</summary><ol class="src">'
                + "".join(f'<li id="src{k}"><a href="{e(u)}" rel="nofollow">{e(self.title.get(u) or u)}</a></li>'
                          for u, k in sorted(self.num.items(), key=lambda x: x[1])) + "</ol></details>")


# Общие стили статьи (цепочка-схема, ссылки на источники, список источников).
ARTICLE_CSS = """<style>.chart .lab2{font:12.5px var(--sans);fill:var(--ink)}
sup.cite{font-size:10.5px;margin-left:1px}sup.cite a{color:var(--sky-t);text-decoration:none}
.chain{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:14px 0 18px}
.chain div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.chain b{display:block;color:var(--ink2);font-size:14px}.chain span{font-size:12.5px;color:var(--dim)}
ol.src{font-size:12.5px;color:var(--dim)}ol.src a{color:var(--dim);overflow-wrap:anywhere}
.ok{color:var(--green-t)}.no{color:var(--orange)}
.formula{font:14px var(--mono);color:var(--ink2);background:var(--panel);border:1px solid var(--line);
border-radius:8px;padding:12px 14px;line-height:1.8}</style>"""


def chain(steps) -> str:
    return '<div class="chain">' + "".join(f'<div><b>{e(a)}</b><span>{e(b)}</span></div>' for a, b in steps) + "</div>"


def whisker(rows, *, lo, hi, ticks, fmt, label_w=190, w=760, extra=None, cur=None) -> str:
    """Точки с разбросом: rows — [(подпись, значение, (от, до), цвет)].
    cur — валюта значений: подписи пересчитываются переключателем валюты (шкала линейная от
    нуля, поэтому геометрия при пересчёте не меняется — меняются только подписи)."""
    if cur:
        f0 = fmt
        fmt = lambda v: money(v, cur, nc=True, tag="tspan") if isinstance(v, (int, float)) else f0(v)  # noqa: E731
    L, R, ROW = label_w, 80, 30
    X = lambda v: L + (min(max(v, lo), hi) - lo) / (hi - lo) * (w - L - R)   # noqa: E731
    H = 26 + ROW * len(rows)
    g = []
    for t in ticks:
        g.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="14" y2="{H - 14}" stroke="var(--line)"/>'
                 f'<text x="{X(t):.1f}" y="{H - 2}" text-anchor="middle" class="ax">{fmt(t)}</text>')
    for i, (name, m, (a, b), col) in enumerate(rows):
        y = 26 + i * ROW
        g.append(f'<text x="{L - 10}" y="{y + 4}" text-anchor="end" class="lab2">{e(name)}</text>'
                 f'<line x1="{X(a):.1f}" x2="{X(b):.1f}" y1="{y}" y2="{y}" stroke="{col}" stroke-width="2"/>'
                 f'<line x1="{X(a):.1f}" x2="{X(a):.1f}" y1="{y - 5}" y2="{y + 5}" stroke="{col}"/>'
                 f'<line x1="{X(b):.1f}" x2="{X(b):.1f}" y1="{y - 5}" y2="{y + 5}" stroke="{col}"/>'
                 f'<circle cx="{X(m):.1f}" cy="{y}" r="5" fill="{col}"/>'
                 f'<text x="{X(b) + 8:.1f}" y="{y + 4}" class="lab" fill="var(--ink2)">{fmt(m)}</text>')
        if extra:
            g.append(extra(i, y, X))
    return f'<svg viewBox="0 0 {w} {H}" class="chart" role="img">{"".join(g)}</svg>'


# Маркер «как это связано с расчётом» — на карточке в ленте и под заголовком статьи.
# Источник один — поле `calc` в research/index.yaml (сервер читает его же):
#   in_calc  — калькулятор уже учитывает это по умолчанию;
#   on_input — расчёт учтёт, если ввести свои данные: статья — что держать в голове при вводе;
#   planned  — выводы статьи ещё не внесены в калькулятор.
# Те же три значка — у пунктов «Что меняем в калькуляторе» (`mark`).
CALC = {"in_calc": ("✓", ("Уже в расчёте", "Built into the calculator", "Im Rechner enthalten"), "var(--green)"),
        "on_input": ("⚑", ("Учесть при вводе", "Mind when entering data", "Bei der Eingabe beachten"), "var(--sky)"),
        "planned": ("◷", ("В очереди на расчёт", "Queued for the calculator", "Für den Rechner geplant"),
                    "var(--dim)")}
CALC_CSS = """<style>
.calc{display:inline-flex;align-items:center;gap:6px;font:600 12.5px var(--sans);border:1px solid currentColor;
  border-radius:999px;padding:2px 10px;margin:0 8px 0 0;white-space:nowrap}
.calcrow{display:flex;flex-wrap:wrap;align-items:center;gap:6px 0;margin:-2px 0 16px;font-size:13px;color:var(--dim)}
li .calc{font-size:11px;padding:0 7px;margin-right:6px;vertical-align:1px}
.legend-calc{font-size:12.5px;color:var(--dim);margin:6px 0 10px}
</style>"""


def mark(kind: str) -> str:
    ic, txt, col = CALC[kind]
    return f'<span class="calc" style="color:{col}">{ic} {e(T(*txt))}</span>'


def calc_badge(slug: str) -> str:
    """Маркер статьи с пояснением — из index.yaml (одна правда для сайта и файла)."""
    import yaml
    doc = yaml.safe_load((pathlib.Path(__file__).resolve().parent / "index.yaml").read_text(encoding="utf-8"))
    it = next(x for x in doc["items"] if x["slug"] == slug)
    note = (it.get("calc_note") or {}).get(LANG) or ""
    # Под маркером — переключатель валюты: оба говорят, как читать цифры статьи.
    return CALC_CSS + f'<div class="calcrow">{mark(it["calc"])}<span>{e(note)}</span></div>' + cur_bar()


def article_title(slug: str) -> str:
    """Заголовок вкладки — из index.yaml на языке статьи."""
    import yaml
    doc = yaml.safe_load((pathlib.Path(__file__).resolve().parent / "index.yaml").read_text(encoding="utf-8"))
    it = next(x for x in doc["items"] if x["slug"] == slug)
    return f"{it['title'][LANG]} · FlightCost"


def write_all(here, slug: str, build, tr: "Tr | None" = None) -> None:
    """Собрать статью на трёх языках: report.html, report.en.html, report.de.html."""
    for lg in LANGS:
        set_lang(lg)
        out = pathlib.Path(here) / out_name(lg)
        out.write_text(build(), encoding="utf-8")
        print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} КБ")
    set_lang("ru")
    if tr is not None and tr.missing:
        print(f"нет перевода для {len(tr.missing)} строк данных — дописать в i18n.yaml:")
        for x in sorted(tr.missing):
            print("  -", x[:140])
