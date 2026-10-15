"""Отчёт по парку документом: светлый HTML → PDF, тёмный — на сайте.

Порядок — как в обзорах типов владельца (решение 204): что за машины
(размеры, доступность, ЛТХ), во что обходится кресло (CASK и RASK по
длине плеча), примерка на сеть (объём → рейсы → борты → итог), цена и
доля, плюсы и минусы, что важно понимать. Документ собирается на
сервере из словаря `fleetreport.build`: один текст для PDF и для сайта,
различие — тема и полоса с вводами сверху.

Подписи — по-русски в коде, перевод — из того же каталога, что у
витрины (`web/i18n.json`): `T("…")`. Тест ловит фразу без перевода.
Числа — в формате языка читателя; деньги — в валюте показа по курсу.
"""

from __future__ import annotations

import html
import json
import math
import urllib.parse
from pathlib import Path

WEB = Path(__file__).parent / "web"
_CAT = None


def _catalog() -> dict:
    global _CAT
    if _CAT is None:
        p = WEB / "i18n.json"
        _CAT = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _CAT


class Doc:
    """Язык, валюта и форматирование чисел одного документа."""

    def __init__(self, lang="ru", cur="EUR", rate=1.0):
        self.lang = lang if lang in ("ru", "en", "de") else "ru"
        self.cur, self.rate = cur, float(rate or 1.0)

    def T(self, s: str) -> str:                       # noqa: N802 — как _t в витрине
        if self.lang == "ru":
            return s
        return (_catalog().get(self.lang) or {}).get(" ".join(s.split()), s)

    def n(self, x, d=0) -> str:
        if x is None or (isinstance(x, float) and not math.isfinite(x)):
            return "—"
        s = f"{x:,.{d}f}"
        if self.lang == "ru":
            return s.replace(",", " ").replace(".", ",")
        if self.lang == "de":
            return s.replace(",", " ").replace(".", ",")
        return s

    def pct(self, x, d=0) -> str:
        return "—" if x is None else f"{self.n(x * 100, d)}%"

    def money(self, eur, sign=False, unit=True) -> str:
        if eur is None:
            return "—"
        v = eur * self.rate
        s = "+" if sign and v > 0 else ("−" if v < 0 else "")
        a = abs(v)
        cu = f" {self.cur}" if unit else ""
        if a >= 1e6:
            return f"{s}{self.n(a / 1e6, 2)} {self.T('млн')}{cu}"
        if a >= 1e4:
            return f"{s}{self.n(a / 1e3, 0)} {self.T('тыс.')}{cu}"
        return f"{s}{self.n(a, 0)}{cu}"

    def ct(self, eur_ct, d=2) -> str:
        return "—" if eur_ct is None else self.n(eur_ct * self.rate, d)


e = html.escape


# ── силуэт ──────────────────────────────────────────────────────────────
# Тот же рисунок, что в витрине (serve.html, silhouette; решение 188):
# вид сверху из чисел типа. Здесь — путь в метрах, нос в (0,0), хвост
# вниз: так силуэты разных типов ложатся друг на друга в одном масштабе.

def silhouette_parts(g: dict) -> dict | None:
    if not g or not g.get("span") or not g.get("length"):
        return None
    b, L = float(g["span"]), float(g["length"])
    s = b / 2
    mach, mount = g.get("mach"), g.get("mount")
    prop = mach is not None and mach < 0.65 and mount != "rear"
    rear = mount == "rear"
    w = g.get("width") or (2.3 if b < 22 else 2.95 if b < 31 else 3.9 if b < 45 else 5.7 if b < 62 else 6.6)
    sw_deg = g.get("sweep") if g.get("sweep") is not None else (
        2 if prop else max(15, min(37, 25 + ((mach or 0.78) - 0.78) * 80)))
    sw = math.radians(sw_deg)
    AR = 12 if prop else (8.8 if b > 50 else 9.4)
    lam = 0.5 if prop else 0.27
    S = b * b / AR
    cr = 2 * S / (b * (1 + lam))
    ct = lam * cr
    yq = L * (0.53 if rear else 0.42 if prop else 0.44)
    y0 = yq - 0.25 * cr
    tle = math.tan(sw) + 0.25 * (cr - ct) / s
    kx = 0.34 * s
    yk = y0 + tle * kx + (cr - (cr - ct) * kx / s) * (1 if prop else 0.95)

    def half(sg):
        if prop:
            return [(0, y0), (sg * s, y0 + tle * s), (sg * s, y0 + tle * s + ct), (0, y0 + cr)]
        return [(0, y0), (sg * s, y0 + tle * s), (sg * s, y0 + tle * s + ct), (sg * kx, yk),
                (sg * w * 0.5, yk + 0.02 * cr), (0, yk + 0.02 * cr)]
    bh = (0.37 if rear else 0.3 if prop else 0.35) * b
    sh = bh / 2
    crh = (0.11 if rear else 0.1) * L * (0.8 if prop else 1)
    cth = 0.4 * crh
    th = math.tan(sw + (0.1 if prop else 0.09))
    yh = L * (0.995 if rear else 0.975) - crh

    def tail(sg):
        return [(0, yh), (sg * sh, yh + th * sh), (sg * sh, yh + th * sh + cth), (0, yh + crh)]
    ln = min(1.7 * w, 0.14 * L)
    lt = min((2.9 if b > 50 else 2.5) * w, 0.3 * L)
    f = lambda v: f"{v:.2f}"                                   # noqa: E731
    fus = (f"M0,0 C{f(w*.3)},0 {f(w/2)},{f(ln*.4)} {f(w/2)},{f(ln)} L{f(w/2)},{f(L-lt)} "
           f"C{f(w/2)},{f(L-lt*.4)} {f(w*.14)},{f(L-lt*.06)} {f(w*.1)},{f(L)} L{f(-w*.1)},{f(L)} "
           f"C{f(-w*.14)},{f(L-lt*.06)} {f(-w/2)},{f(L-lt*.4)} {f(-w/2)},{f(L-lt)} "
           f"L{f(-w/2)},{f(ln)} C{f(-w/2)},{f(ln*.4)} {f(-w*.3)},0 0,0Z")
    n = max(1, int(g.get("engines") or 2))
    mtow = g.get("mtow")
    dn = max(0.9, 0.04 * b) if prop else (max(0.9, 0.32 * math.sqrt(mtow / n)) if mtow else 0.055 * b)
    lnac = 1.25 * cr if prop else 2.0 * dn
    pods = []
    if rear:
        for i in range(n):
            sg, col = (1 if i % 2 else -1), i // 2
            pods.append((sg * (w / 2 + dn * (0.62 + col * 1.1)), L * 0.74))
    else:
        st = [0.38, 0.66] if n >= 4 else [0.34] if n == 3 else [0.3 if prop else 0.34]
        for fr in st:
            for sg in (-1, 1):
                x = sg * fr * s
                pods.append((x, y0 + tle * abs(x) - (0.45 if prop else 0.62) * lnac))
        if n == 3:
            pods.append((0, L * 0.72))
    pts = lambda p: " ".join(f"{x:.2f},{y:.2f}" for x, y in p)  # noqa: E731
    polys = [pts(half(-1)), pts(half(1)), pts(tail(-1)), pts(tail(1))]
    eng = "".join(f'<rect x="{x - dn / 2:.2f}" y="{y:.2f}" width="{dn:.2f}" height="{lnac:.2f}" '
                  f'rx="{dn / 2.2:.2f}"/>' for x, y in pods)
    top = min([0.0] + [y for _, y in pods])
    return {"polys": polys, "fus": fus, "eng": eng, "span": b, "length": L, "top": top}


def silhouette_svg(g, px_per_m=3.0, color="currentColor") -> str:
    p = silhouette_parts(g)
    if not p:
        return ""
    pad = 0.6
    W, H = p["span"] + 2 * pad, p["length"] - p["top"] + 2 * pad
    body = "".join(f'<polygon points="{x}"/>' for x in p["polys"]) + f'<path d="{p["fus"]}"/>'
    return (f'<svg width="{W * px_per_m:.0f}" height="{H * px_per_m:.0f}" '
            f'viewBox="{-p["span"] / 2 - pad:.2f} {p["top"] - pad:.2f} {W:.2f} {H:.2f}" '
            f'aria-hidden="true"><g fill="{color}">{body}{p["eng"]}</g></svg>')


def overlay_svg(types: list, m: str = "м") -> str:
    """Все типы друг на друге: носы совмещены, один масштаб."""
    parts = [(t, silhouette_parts(t.get("geom"))) for t in types]
    parts = [(t, p) for t, p in parts if p]
    if not parts:
        return ""
    span = max(p["span"] for _, p in parts)
    top = min(p["top"] for _, p in parts)
    length = max(p["length"] for _, p in parts)
    pad = 1.5
    W, H = span + 2 * pad, length - top + 2 * pad + 3
    g = []
    for t, p in sorted(parts, key=lambda tp: -tp[1]["span"] * tp[1]["length"]):
        c = f"var(--t{t['slot']})"
        body = "".join(f'<polygon points="{x}"/>' for x in p["polys"]) + f'<path d="{p["fus"]}"/>'
        g.append(f'<g fill="{c}" fill-opacity=".10" stroke="{c}" stroke-width="{span * .006:.2f}" '
                 f'stroke-linejoin="round">{body}{p["eng"]}</g>')
    # Масштабная линейка 10 м.
    y = length + pad + 1
    x0 = -span / 2
    ruler = (f'<g stroke="var(--d-ink2)" stroke-width="{span * .004:.2f}"><line x1="{x0:.2f}" y1="{y:.2f}" '
             f'x2="{x0 + 10:.2f}" y2="{y:.2f}"/><line x1="{x0:.2f}" y1="{y - .6:.2f}" x2="{x0:.2f}" '
             f'y2="{y + .6:.2f}"/><line x1="{x0 + 10:.2f}" y1="{y - .6:.2f}" x2="{x0 + 10:.2f}" '
             f'y2="{y + .6:.2f}"/></g><text x="{x0 + 11:.2f}" y="{y + .6:.2f}" font-size="{span * .035:.2f}" '
             f'fill="var(--d-ink2)">10 {m}</text>')
    return (f'<svg viewBox="{-span / 2 - pad:.2f} {top - pad:.2f} {W:.2f} {H:.2f}" role="img" '
            f'class="overlay">{"".join(g)}{ruler}</svg>')


# ── графики ─────────────────────────────────────────────────────────────

def _nice(x):
    if x <= 0:
        return 1
    p = 10 ** math.floor(math.log10(x))
    for k in (1, 2, 2.5, 5, 10):
        if x <= k * p:
            return k * p
    return 10 * p


def cask_chart(D: Doc, types: list) -> str:
    """CASK каждого типа и RASK рынка по длине плеча, ¢ на кресло-км."""
    pts = [(c["dist"], c["cask_ct"]) for t in types for c in t["curve"] if c["cask_ct"]]
    rask = [(c["dist"], c["rask_ct"]) for c in types[0]["curve"] if c["rask_ct"]] if types else []
    if not pts:
        return ""
    xmax = _nice(max(x for x, _ in pts) * 1.05)
    top = max(y for _, y in pts + rask) * D.rate * 1.05
    step = _nice(top / 5)
    ymax = math.ceil(top / step) * step
    W, H, l, r, t, b = 760, 350, 52, 130, 36, 40
    X = lambda x: l + x / xmax * (W - l - r)                   # noqa: E731
    Y = lambda y: t + (1 - y * D.rate / ymax) * (H - t - b)   # noqa: E731
    g = []
    ny = int(round(ymax / step))
    for i in range(ny + 1):                                     # сетка и оси
        yv = step * i
        yy = t + (1 - i / ny) * (H - t - b)
        g.append(f'<line x1="{l}" x2="{W - r}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>'
                 f'<text x="{l - 8}" y="{yy + 4:.1f}" text-anchor="end" class="ax">{D.n(yv, 1 if step < 1 else 0)}</text>')
    for i in range(6):
        xv = xmax * i / 5
        xx = X(xv)
        g.append(f'<text x="{xx:.1f}" y="{H - b + 18}" text-anchor="middle" class="ax">{D.n(xv)}</text>')
    g.append(f'<text x="{W - r}" y="{H - 4}" text-anchor="end" class="ax">{D.T("км по прямой")}</text>')
    g.append(f'<text x="{l - 40}" y="14" class="ax">{D.cur}-{D.T("цент на кресло-км")}</text>')
    for x, y in rask:
        g.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3.2" class="rask"><title>RASK {D.ct(y)}</title></circle>')
    labels = []
    for tp in types:
        by = {}
        for c in tp["curve"]:
            if c["cask_ct"]:
                by.setdefault(round(c["dist"]), []).append(c["cask_ct"])
        line = sorted((x, sum(v) / len(v)) for x, v in by.items())
        if not line:
            continue
        col = f"var(--t{tp['slot']})"
        d = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(line))
        g.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2"/>')
        for x, y in line:
            g.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4" fill="{col}" class="pt">'
                     f'<title>{e(tp["short"])}: {D.ct(y)} @ {D.n(x)} km</title></circle>')
        labels.append([Y(line[-1][1]), X(line[-1][0]), tp["short"], col])
    labels.sort()                                               # подписи без наложения
    for i in range(1, len(labels)):
        labels[i][0] = max(labels[i][0], labels[i - 1][0] + 13)
    for yy, xx, name, col in labels:
        g.append(f'<text x="{W - r + 8}" y="{yy + 4:.1f}" class="lab" fill="{col}">{e(name)}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
            f'aria-label="{e(D.T("CASK по длине плеча"))}">{"".join(g)}</svg>')


def bars(D: Doc, label: str, items: list, fmt, lo_best=True, note: str = "") -> str:
    """Строка сравнения: подпись слева, полоса каждого типа в одном масштабе."""
    vals = [v for _, v, _ in items if v is not None]
    if not vals:
        return ""
    top = max(abs(v) for v in vals) or 1
    best = (min if lo_best else max)(vals)
    rows = []
    for t, v, extra in items:
        w = 0 if v is None else abs(v) / top * 100
        neg = v is not None and v < 0
        rows.append(f'<div class="bar"><span class="bn">{e(t["short"])}</span><div class="track"><div class="fill{" neg" if neg else ""}" '
                    f'style="width:{w:.1f}%;background:var(--t{t["slot"]})"></div>'
                    f'</div><div class="val'
                    f'{" best" if v == best and len(vals) > 1 else ""}">{fmt(v)}'
                    f'{f"<small>{extra}</small>" if extra else ""}</div></div>')
    return (f'<div class="barrow"><div class="lab">{label}{f"<small>{note}</small>" if note else ""}</div>'
            f'<div class="barset">{"".join(rows)}</div></div>')


# ── тексты по кодам ─────────────────────────────────────────────────────

def pc_text(D: Doc, x: dict) -> str:
    T, c = D.T, x["code"]
    if c == "best_result":
        return f'{T("лучший итог:")} {D.money(x["v"], True)}/{T("мес")}, {T("на")} {D.money(x["gap"])} {T("больше следующего")}'
    if c == "worst_result":
        return f'{T("худший итог: на")} {D.money(x["gap"])}/{T("мес")} {T("меньше лучшего")}'
    if c == "cheapest_pax":
        return f'{T("самый дешёвый пассажир:")} {D.money(x["v"])}'
    if c == "dearest_pax":
        return f'{T("самый дорогой пассажир:")} {D.money(x["v"])}'
    if c == "lowest_cask":
        return f'{T("самое дешёвое кресло-км:")} {D.ct(x["v"])} {T("цента")}'
    if c == "fewest_aircraft":
        return f'{T("меньше всех бортов:")} {x["v"]}'
    if c == "most_aircraft":
        return f'{T("больше всех бортов:")} {x["v"]}'
    if c == "fuel_lean":
        return f'{T("меньше всех топлива на кресло:")} {D.n(x["v"], 2)} {T("кг на 100 кресло-км")}'
    if c == "fuel_heavy":
        return f'{T("больше всех топлива на кресло:")} {D.n(x["v"], 2)} {T("кг на 100 кресло-км")}'
    if c == "min_freq_binds":
        return (f'{T("на")} {x["n"]} {T("из")} {x["of"]} {T("пар объёма не хватает на")} {x["freq"]} '
                f'{T("рейсов в неделю — летает с загрузкой от")} {D.pct(x["lf"])}')
    if c == "idle_hours":
        return f'{T("налёт")} {D.n(x["v"])} {T("ч/мес на борт из")} {D.n(x["max"])}: {T("борт целиком не загружен")}'
    if c == "range_limited":
        return (f'{T("не везёт полный салон по дальности: на")} {x["n"]} {T("из")} {x["of"]} {T("пар")} '
                f'{T("загрузка не выше")} {D.pct(x["cap"])} ({e(", ".join(x["pairs"]))}) — '
                f'{T("нужно больше рейсов")}')
    if c == "range_cut":
        return f'{T("не долетает: пар отсечено по дальности —")} {x["n"]}'
    if c == "rates_default":
        names = {"lease": T("лизинг"), "util": T("налёт"), "maint": T("ТОиР"), "crew": T("экипаж")}
        return f'{T("ставки — заготовка, не данные:")} {", ".join(names.get(f, f) for f in x["fields"])}'
    if c.startswith("avail_"):
        head = {"production": T("заказать можно"), "secondary": T("новым не купить"),
                "waiting": T("ещё не поставляется"), "restricted": T("поставки ограничены"),
                "ended": T("снят с производства")}.get(c[6:], T("поставки"))
        return f'{head}: {e(x.get("status") or "")}'
    return e(c)


def note_text(D: Doc, x: dict) -> tuple[str, str]:
    T, c = D.T, x["code"]
    if c == "elasticity":
        return (T("Отклик доли на цену — допущение"),
                f'{T("Доля при цене ниже рынка считается как доля × (цена к рынку)^(−эластичность), эластичность")} '
                f'{D.n(x["v"], 1)}. {T("Открытых данных об отклике доли на цену по парам нет: это ввод, а не измерение. Проверьте вывод при другой эластичности.")}')
    if c == "partial_pairs":
        return (T("Не все типы летают все пары"),
                f'{", ".join(x["pairs"])}: {T("пары есть не у всех типов (дальность, права), итоги сравнивают немного разные сети.")}')
    if c == "no_market":
        return (T("Пары без потока не считаются"),
                f'{", ".join(x["pairs"])}: {T("потока нет ни в статистике, ни в оценке — задайте его на вкладке «Рынок» витрины.")}')
    if c == "market_estimated":
        return (T("Поток — оценка по наблюдённым рейсам"),
                f'{", ".join(x["pairs"])}: {T("опубликованной статистики по паре нет, поток оценён по рейсам ADS-B × кресла × загрузка.")}')
    if c == "no_parts":
        return (T("Статьи плеч не разложены"),
                f'{", ".join(x["types"])}: {T("сеть посчитана старой версией — пересчитайте её на витрине.")}')
    if c == "conv_one":
        return (T("Средний чек принят равным минимуму"),
                T("Рыночная цена плеча — медиана дневных минимумов, а не средний чек. Множитель «чек к минимуму» = 1: выручка занижена у всех типов одинаково, итоги — ниже реальных. Задайте его на странице отчёта или в сети; на сравнение типов и на эластичность он не влияет — она считается от нашей цены к рыночной, а множитель общий у нас и у рынка."))
    if c == "share_cap":
        return (T("Доля упёрлась в потолок"),
                f'{T("Доля после отклика на цену ограничена")} {D.pct(x["v"])} {T("рынка: больше — уже не «отжать», а занять рынок.")}')
    return (c, "")


# ── документ ────────────────────────────────────────────────────────────

CSS = """
.doc{background:var(--d-paper);color:var(--d-ink);font:15px/1.5 var(--sans);
  font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.doc .wrap{max-width:1120px;margin:0 auto;padding:36px 24px 70px}
.doc h1{font-size:clamp(26px,3.6vw,40px);line-height:1.08;letter-spacing:-.02em;font-weight:600;
  margin:0 0 14px;max-width:26ch;color:var(--d-head)}
.doc h2{font-size:23px;line-height:1.2;font-weight:600;margin:0 0 6px;color:var(--d-head)}
.doc h3{font-size:16px;font-weight:600;margin:0 0 4px;color:var(--d-head)}
.doc p{margin:0 0 10px;max-width:76ch}
.doc .lede{font-size:18px;line-height:1.45;max-width:70ch}
.doc .meta{color:var(--d-ink2);font-size:13.5px;margin-bottom:22px}
.doc section{padding:38px 0 6px;border-top:1px solid var(--d-rule)}
.doc .sec-head{margin-bottom:20px}.doc .sec-head p{color:var(--d-ink2);margin:0}
.doc .small{font-size:13px;color:var(--d-ink2)}
.doc .hero{display:grid;grid-template-columns:1.15fr 1fr;gap:34px;align-items:start}
.doc .overlay{width:100%;height:auto;max-height:480px;display:block}
.doc .legend{display:grid;gap:12px}
.doc .legend .item{display:grid;grid-template-columns:14px 1fr;gap:12px}
.doc .sw{width:14px;height:14px;border-radius:3px;margin-top:4px}
.doc .legend b{display:block;font-size:15.5px;color:var(--d-head)}
.doc .legend span{color:var(--d-ink2);font-size:13px}
.doc .keyfacts{border-top:1px solid var(--d-rule2);padding-top:6px;overflow-x:auto}
.doc table.kf{font-size:12px;min-width:0}
.doc table.kf th,.doc table.kf td{padding:4px 6px;border-bottom:1px solid var(--d-rule2);position:static;background:none}
.doc table.kf thead th{font-weight:600;border-bottom:1px solid var(--d-rule);font-size:11.5px}
.doc table.kf tbody th{color:var(--d-ink2);font-weight:400;width:auto}
.doc table.kf td{color:var(--d-ink);font-weight:600}
.doc h2,.doc .sec-head{break-after:avoid}
.doc .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.doc .card{background:var(--d-card);border:1px solid var(--d-rule);border-radius:10px;padding:18px 18px 14px;min-width:0}
.doc .card.top{border-top:4px solid var(--tc)}
.doc .card ul{margin:0;padding-left:18px}.doc .card li{margin:4px 0;font-size:14px}
.doc .tag{display:inline-block;font-size:12px;padding:2px 8px;border-radius:4px;margin:6px 0 10px;font-weight:600}
.doc .tag.ok{background:var(--d-ok-f);color:var(--d-ok)}.doc .tag.no{background:var(--d-no-f);color:var(--d-no)}
.doc .tag.mid{background:var(--d-mid-f);color:var(--d-mid)}
.doc .price{font-size:21px;font-weight:600;margin:10px 0 0;color:var(--d-head)}
.doc .price small{display:block;font-size:12.5px;font-weight:400;color:var(--d-ink2);margin-top:2px}
.doc .tblwrap{overflow-x:auto;border:1px solid var(--d-rule);border-radius:10px;background:var(--d-card)}
.doc table{border-collapse:collapse;width:100%;font-size:13.5px}
.doc th,.doc td{padding:8px 11px;text-align:left;vertical-align:top;border-bottom:1px solid var(--d-rule2)}
.doc thead th{background:var(--d-card);border-bottom:2px solid var(--d-rule);font-weight:600;color:var(--d-head)}
.doc tbody th{font-weight:400;color:var(--d-ink2);width:22%;position:sticky;left:0;background:var(--d-card);z-index:1}
.doc tr.group th{position:static}
.doc tr.group th{background:var(--d-paper);color:var(--d-head);font-weight:600;font-size:13px}
.doc td .sm,.doc th .sm{display:block;font-size:12px;color:var(--d-ink2);font-weight:400}
.doc td.r,.doc th.r{text-align:right;white-space:nowrap}
.doc td.best{font-weight:600}
.doc td.best::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px;background:currentColor}
/* Красный — плохо (убыток, полупустой борт); оранжевый — ограничение
   дальностью и допущения. На тёмной теме --d-warn оранжевый, поэтому
   «плохо» — своим токеном, чтобы два смысла не слились. */
.doc td.bad,.doc .bad{color:var(--d-bad)}
.doc .rng{display:inline-block;margin-left:6px;padding:0 6px;border-radius:3px;font-size:11px;font-weight:600;
  color:var(--d-rng);background:var(--d-rng-f);border:1px solid var(--d-rng);white-space:nowrap}
.doc .est{border-bottom:1px dotted var(--d-ink2)}
.doc .bars{display:grid;gap:20px}
.doc .barrow{display:grid;grid-template-columns:200px 1fr;gap:16px;align-items:start}
.doc .barrow .lab{font-size:14px;color:var(--d-ink2);padding-top:1px}
.doc .barrow .lab small{display:block;font-size:12px}
.doc .barset{display:grid;gap:5px}
.doc .bar{display:grid;grid-template-columns:150px 1fr 150px;align-items:center;gap:10px}
.doc .bn{font-size:12px;color:var(--d-ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.doc .track{height:12px;background:var(--d-track);border-radius:3px;position:relative;overflow:hidden}
.doc .fill{position:absolute;left:0;top:0;bottom:0;border-radius:3px}
.doc .fill.neg{background-image:repeating-linear-gradient(135deg,transparent 0 4px,var(--d-paper) 4px 6px)}
.doc .val{font-size:13px;text-align:right}.doc .val.best{font-weight:600}
.doc .val small{display:block;font-size:11.5px;color:var(--d-ink2)}
.doc .chart{width:100%;height:auto;display:block}
.doc .chart .grid{stroke:var(--d-rule2);stroke-width:1}
.doc .chart .ax{font-size:11.5px;fill:var(--d-ink2)}
.doc .chart .lab{font-size:12.5px;font-weight:600}
.doc .chart .rask{fill:none;stroke:var(--d-ink2);stroke-width:1.4}
.doc .kv{display:grid;grid-template-columns:repeat(3,1fr);gap:10px 18px;font-size:13.5px}
.doc .kv div{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid var(--d-rule2);padding:3px 0}
.doc .kv b{font-weight:600;color:var(--d-head)}
.doc .assume{background:var(--d-card);border:1px solid var(--d-rule);border-radius:10px;padding:14px 16px;margin-bottom:18px}
.doc .assume .guess{color:var(--d-warn)}
.doc .pc{list-style:none;padding:0;margin:0 0 6px}
.doc .pc li{padding:3px 0 3px 18px;position:relative;font-size:13.5px}
.doc .pc li::before{position:absolute;left:0;font-weight:600}
.doc .pc.pro li::before{content:"+";color:var(--d-ok)}.doc .pc.con li::before{content:"−";color:var(--d-warn)}
.doc .verdict{display:grid;gap:12px}
.doc .verdict .card p{margin:0;max-width:none}.doc .verdict .card b{display:block;margin-bottom:3px;font-size:15.5px;color:var(--d-head)}
.doc .sources{font-size:13px;color:var(--d-ink2)}.doc .sources ol{padding-left:20px;margin:0}.doc .sources li{margin:4px 0}
.doc .sil{color:var(--tc)}
@media screen and (max-width:860px){
  .doc .hero{grid-template-columns:1fr}.doc .grid3,.doc .kv{grid-template-columns:1fr}
  .doc .barrow{grid-template-columns:1fr;gap:6px}.doc .bar{grid-template-columns:96px 1fr 104px}
  .doc .wrap{padding:22px 16px 50px}
  .doc table{min-width:620px}.doc tbody th{min-width:130px}
}
/* Печать: заголовок не остаётся внизу страницы без того, что под ним.
   break-after:avoid Chromium соблюдает только между дробимыми блоками, а
   прокручиваемая обёртка таблицы для него монолитна — поэтому в печати
   обёртка без прокрутки, строки не рвутся, шапка таблицы повторяется, а
   у заголовка невидимый «хвост»: если под ним меньше ~45 мм, он уходит
   на следующую страницу вместе с началом раздела. */
@media print{.doc .wrap{padding:0}.doc section{break-inside:auto}.doc .card,.doc .barrow,.doc .chart{break-inside:avoid}
  .doc .tblwrap{overflow:visible}.doc table{min-width:0}.doc thead{display:table-header-group}
  .doc tr{break-inside:avoid}.doc .sec-head,.doc h2,.doc h3{break-inside:avoid;break-after:avoid}
  .doc .sec-head::after,.doc h3::after,.doc .sources h2::after{content:"";display:block;height:170px;margin-bottom:-170px}
  .doc tbody th{position:static}
  .noprint{display:none!important}}
"""


def _tag(kind):
    return {"production": "ok", "waiting": "no", "restricted": "no", "ended": "no"}.get(kind, "mid")


def render(rep: dict, *, theme="light", lang="ru", cur="EUR", rate=1.0,
           toolbar: str = "", css_text: str = "") -> str:
    """HTML документа целиком. `css_text` — ui.css (со шрифтами для PDF)."""
    D = Doc(lang, cur, rate)
    T = D.T
    a = rep["assume"]
    ctx = rep.get("context") or {}
    ok = sorted([t for t in rep["types"] if t.get("status") == "ok"], key=lambda t: t["rank"])
    bad = [t for t in rep["types"] if t.get("status") != "ok"]
    for i, t in enumerate(ok + bad):
        t["slot"] = (i % 5) + 1
        av = t.get("availability") or {}
        t["short"] = av.get("name") or t["name"] or t["icao"]
    L = next(t for t in ok if t["icao"] == rep["leader"])
    pairs = rep.get("common_pairs") or []
    H = []

    # ── заголовок и вывод
    title = (f'{T("Какой тип брать под")} {D.pct(a["share"])} {T("потока на")} {len(pairs) or "—"} '
             f'{T("парах из")} {e(ctx.get("base") or "—")}')
    lede = [f'{T("Выгоднее всего")} <b>{e(L["short"])}</b>: {D.money(L["plan"]["result"], True)} '
            f'{T("в месяц")}, {L["plan"]["fleet"]} {T("бортов")}, {T("себестоимость пассажира")} '
            f'{D.money(L["plan"]["cost_per_pax"])}.']
    if len(ok) > 1:
        bands = rep.get("share_bands") or []
        if len(bands) > 1:
            name = {t["icao"]: t["short"] for t in ok}
            lede.append(T("Но ответ зависит от объёма:") + " " + "; ".join(
                f'{T("при доле")} {D.pct(b["from"])}–{D.pct(b["to"])} — {e(name.get(b["type"], b["type"]))}'
                for b in bands) + ".")
        elif bands:
            lede.append(T("Лидер не меняется при доле рынка от 2 до 60% — выбор устойчив к объёму."))
    if (L.get("availability") or {}).get("kind") not in (None, "production"):
        lede.append(f'{T("При этом")} {e(L["short"])} — {e(L["availability"]["status"]).lower()}: '
                    f'{T("выгодность на бумаге не значит, что борт можно получить.")}')
    H.append(f'<h1>{title}</h1><p class="lede">{" ".join(lede)}</p>')
    month = f', {T("месяц")} {ctx["month"]}' if ctx.get("month") else ""
    fx = "" if D.cur == "EUR" else f' ({D.n(D.rate, 4)} {D.cur} {T("за")} 1 EUR)'
    H.append(f'<p class="meta">{T("База")} {e(ctx.get("base") or "—")}, {T("аэропорты")} '
             f'{e(", ".join(ctx.get("airports") or []))}{month}. '
             f'{T("Расчёт FlightCostApp на")} {e(rep.get("as_of") or "")}; {T("ЛТХ и поставки — обзоры на")} '
             f'{e(rep.get("availability_as_of") or "—")}. {T("Деньги — в")} {D.cur}{fx}.</p>')

    # ── силуэты и легенда
    leg = []
    for t in ok + bad:
        av = t.get("availability") or {}
        sub = av.get("tagline") or (f'{t.get("seats") or "—"} {T("кресел в расчёте")}')
        leg.append(f'<div class="item"><span class="sw" style="background:var(--t{t["slot"]})"></span>'
                   f'<div><b>{e(av.get("full_name") or t["name"])}</b><span>{e(sub)}</span></div></div>')
    g = lambda t, k: (t.get("geom") or {}).get(k)               # noqa: E731
    kf = [(T("Размах × длина, м"), lambda t: f'{D.n(g(t, "span"), 1)} × {D.n(g(t, "length"), 1)}' if g(t, "span") else "—"),
          (T("Взлётная масса, т"), lambda t: D.n(g(t, "mtow"), 1) if g(t, "mtow") else "—"),
          (T("Кресел в расчёте"), lambda t: str(t.get("seats") or "—")),
          (T("Цена борта"), lambda t: e((t.get("availability") or {}).get("price") or "—"))]
    hd = "".join('<th style="color:var(--t%d)">%s</th>' % (t["slot"], e(t["short"])) for t in ok)
    keyf = ('<table class="kf"><thead><tr><th></th>' + hd + "</tr></thead><tbody>"
            + "".join(f"<tr><th>{k}</th>" + "".join(f"<td>{f(t)}</td>" for t in ok) + "</tr>" for k, f in kf)
            + "</tbody></table>")
    H.append(f'<div class="hero"><div>{overlay_svg(ok, T("м"))}<p class="small">{T("Вид сверху, носы совмещены, один масштаб. Схема по размаху, длине, стреловидности и двигателям — узнаваемая, но не чертёж.")}</p></div>'
             f'<div class="legend">{"".join(leg)}<div class="keyfacts">{keyf}</div></div></div>')

    # ── доступность
    cards = []
    for t in ok + bad:
        av = t.get("availability")
        if not av:
            cards.append(f'<div class="card top" style="--tc:var(--t{t["slot"]})"><h3>{e(t["short"])}</h3>'
                         f'<span class="tag mid">{T("сведений о поставках нет")}</span>'
                         f'<p class="small">{T("Типа нет в обзорах — блок заполняется, когда обзор появится.")}</p></div>')
            continue
        cards.append(f'<div class="card top" style="--tc:var(--t{t["slot"]})"><h3>{e(av["name"])}</h3>'
                     f'<span class="tag {_tag(av.get("kind"))}">{e(av["status"])}</span>'
                     f'<ul>{"".join(f"<li>{e(p)}</li>" for p in av["points"])}</ul>'
                     f'<p class="price">{e(av["price"])}<small>{e(av["price_note"])}</small></p></div>')
    stale = any((t.get("availability") or {}).get("stale") for t in ok)
    H.append(f'<section><div class="sec-head"><h2>{T("Что реально можно получить")}</h2><p>'
             f'{T("Сведения о рынке поставок — не расчёт: производство, сертификация, двигатели, цены.")}'
             f'{" <b class=bad>" + T("Сведениям больше полугода — сверьте перед решением.") + "</b>" if stale else ""}'
             f'{" " + T("Тексты обзоров — на русском.") if D.lang != "ru" else ""}</p></div>'
             f'<div class="grid3">{"".join(cards)}</div></section>')

    # ── ЛТХ
    H.append(_specs_section(D, ok + bad))

    # ── экономика кресла
    chart = cask_chart(D, ok)
    arts = [("fuel", T("Топливо")), ("maintenance", T("ТОиР")), ("crew", T("Экипаж")),
            ("airport_charges", T("Аэропорт")), ("terminal", T("Терминальный сбор")),
            ("enroute", T("Аэронавигация")), ("ground_handling", T("Обслуживание")),
            ("other", T("Прочее")), ("distribution", T("Дистрибуция")), ("ownership", T("Лизинг"))]
    per = lambda t, k: t["plan"]["cost"][k] / t["plan"]["ask"] * 100 if t["plan"]["ask"] else None  # noqa: E731
    th = "".join(f'<th class="r" style="color:var(--t{t["slot"]})">{e(t["short"])}</th>' for t in ok)
    trs = []

    def crow(lab, vals, low=True, strong=False):
        vv = [v for v in vals if v is not None]
        best = (min if low else max)(vv) if len(vv) > 1 and max(vv) - min(vv) > 0.005 * max(abs(x) for x in vv) else None
        cells = "".join(f'<td class="r{" best" if v is not None and v == best else ""}">{D.ct(v)}</td>' for v in vals)
        lab = f"<b>{lab}</b>" if strong else lab
        return f"<tr><th>{lab}</th>{cells}</tr>"
    for k, lab in arts:
        vals = [per(t, k) for t in ok]
        if any(abs(v or 0) > 0.005 for v in vals):
            trs.append(crow(lab, vals))
    trs.append(crow(T("Всего"), [t["plan"]["cask_ct"] for t in ok], strong=True))
    trs.append(crow(f'{T("Выручка")} (RASK)', [t["plan"]["rask_ct"] for t in ok], low=False))
    trs.append(crow(T("Разница"), [t["plan"]["rask_ct"] - t["plan"]["cask_ct"] for t in ok], low=False, strong=True))
    cost_tbl = (f'<div class="tblwrap"><table><thead><tr><th>{T("Статья")}</th>{th}</tr></thead>'
                f'<tbody>{"".join(trs)}</tbody></table></div>')
    H.append(f'<section><div class="sec-head"><h2>{T("Экономика кресла: CASK и RASK")}</h2><p>'
             f'{T("Себестоимость кресло-километра у каждого типа на плечах этой сети при плановой загрузке")} '
             f'{D.pct(a["lf_target"])}, {T("с лизингом через налёт. Кружки — выручка на кресло-км на тех же плечах (RASK): где линия типа ниже кружков, плечо окупается.")}</p></div>'
             f'{chart}<p class="small">{T("Короткие плечи дороже на кресло-км у всех: взлёт, посадка и сборы приходятся на меньший пробег. Разница типов — в наклоне и уровне линии.")}</p>'
             f'<h3 style="margin-top:22px">{T("Из чего складывается кресло-км в плане")}</h3>'
             f'<p class="small">{D.cur}-{T("цент на кресло-км при объёме плана: у типа, которому мало пассажиров на минимальную частоту, загрузка ниже и кресло дороже.")}</p>'
             f'{cost_tbl}<p class="small">{T("Точка — дешевле всех по статье; в строках выручки и разницы — больше всех.")}</p></section>')

    # ── примерка на сеть
    H.append(_plan_section(D, rep, ok))

    # ── цена и доля
    H.append(_sweep_section(D, rep, ok))

    # ── плюсы и минусы
    pcs = []
    for t in ok:
        pros = "".join(f"<li>{pc_text(D, x)}</li>" for x in t["pros"])
        cons = "".join(f"<li>{pc_text(D, x)}</li>" for x in t["cons"])
        pcs.append(f'<div class="card top" style="--tc:var(--t{t["slot"]})"><h3>#{t["rank"]} {e(t["short"])}</h3>'
                   f'<p class="small">{D.money(t["plan"]["result"], True)}/{T("мес")} · {t["plan"]["n_op"]}+{t["plan"]["spare"]} '
                   f'{T("бортов")} · {T("загрузка")} {D.pct(t["plan"]["lf"])}</p>'
                   + ('<ul class="pc pro">' + pros + "</ul>" if pros else "")
                   + ('<ul class="pc con">' + cons + "</ul>" if cons else "") + "</div>")
    for t in bad:
        pcs.append(f'<div class="card top" style="--tc:var(--t{t["slot"]})"><h3>{e(t["short"])}</h3>'
                   f'<p class="bad">{e(t.get("why") or "")}</p></div>')
    H.append(f'<section><div class="sec-head"><h2>{T("Плюсы и минусы на этой сети")}</h2><p>'
             f'{T("Выведены из расчёта плана; поставки — из обзоров.")}</p></div><div class="grid3">{"".join(pcs)}</div></section>')

    # ── что важно понимать
    vs = []
    for x in rep.get("notes") or []:
        h, txt = note_text(D, x)
        vs.append(f'<div class="card"><p><b>{h}</b>{txt}</p></div>')
    vs.append(f'<div class="card"><p><b>{T("Что этот отчёт не говорит")}</b>'
              f'{T("Спрос не прогнозируется: доля рынка — ваш ввод, поток пары — статистика или оценка. Расписание проверено суммой часов, без разворотов, ночёвок и окон аэропортов. Права на линии и закрытое небо учтены при сборке сети.")}</p></div>')
    H.append(f'<section><div class="sec-head"><h2>{T("Что важно понимать, принимая решение")}</h2></div>'
             f'<div class="verdict">{"".join(vs)}</div></section>')

    # ── источники
    src, seen = [], set()
    for t in ok + bad:
        av = t.get("availability") or {}
        if av.get("review") and av["review"] not in seen:
            seen.add(av["review"])
            src.append(f'<li><b>{e(av.get("review_title") or "")}</b>. {e(av.get("basis") or "")}<ul>'
                       + "".join(f"<li>{e(s)}</li>" for s in av.get("sources") or []) + "</ul></li>")
    src.append(f'<li>{T("Расчёт рейса — ядро FlightCostApp: сборы аэропортов и аэронавигации, топливо по типу, ставки флота; происхождение каждого числа — в разборе маршрута на flightcost.app.")}</li>')
    H.append(f'<section class="sources"><h2>{T("Источники")}</h2><ol>{"".join(src)}</ol></section>')

    body = "".join(H)
    return (f'<!doctype html><html lang="{D.lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(T("Отчёт по парку"))} — {e(ctx.get("base") or "")}</title>'
            f'<style>{css_text}{CSS}</style></head>'
            f'<body class="doc{" light" if theme == "light" else ""}" style="margin:0">'
            f'{toolbar}<div class="wrap">{body}</div></body></html>')


def _specs_section(D: Doc, types: list) -> str:
    T = D.T
    rows: list[tuple[str, str]] = []
    vals: dict = {}
    reviews = {(t.get("availability") or {}).get("review") for t in types}
    one_review = len(reviews) == 1 and None not in reviews
    # Строка — параметр, а не пара (группа, параметр): обзоры разных
    # классов кладут одно и то же («Крейсерское число М») в разные группы.
    # Группа — из первого обзора, порядок групп — общий.
    for t in types:
        for s in t.get("specs") or []:
            k = s["param"]
            if k not in vals:
                rows.append((s["group"], k))
                vals[k] = {}
            vals[k][t["icao"]] = s
    order = ["Геометрия и салон", "Массы", "Силовая установка", "Полёт", "Аэродром и условия",
             "Стоимость владения и эксплуатации"]
    rows.sort(key=lambda gk: order.index(gk[0]) if gk[0] in order else len(order))
    head = "".join(f'<th style="color:var(--t{t["slot"]})">{e(t["short"])}</th>' for t in types)
    out, grp = [], None
    # Своё: из справочника проекта — то, с чем считал расчёт.
    g = lambda t, k: (t.get("geom") or {}).get(k)               # noqa: E731
    own = [(T("Кресел в расчёте"), lambda t: t.get("seats")),
           (T("Взлётная масса в расчёте, т"), lambda t: D.n(g(t, "mtow"), 1) if g(t, "mtow") else None),
           (T("Лизинг в расчёте, в месяц"), lambda t: D.money(t.get("lease_eur_month"))
            + (f' <span class="sm">{T("заготовка")}</span>' if (t.get("prov") or {}).get("lease") == "default" else "")),
           (T("Налёт в расчёте, ч/мес"), lambda t: D.n(t.get("util_h_month"))),
           (T("ТОиР: за час / за цикл"), lambda t: f'{D.money((t.get("rates") or {}).get("maint_fh"))} / '
                                                    f'{D.money((t.get("rates") or {}).get("maint_fc"))}')]
    out.append(f'<tr class="group"><th colspan="{len(types) + 1}">{T("С чем считал расчёт")}</th></tr>')
    for lab, f in own:
        out.append(f'<tr><th>{lab}</th>' + "".join(
            f'<td>{"—" if t.get("status") != "ok" or f(t) in (None, "") else f(t)}</td>' for t in types) + "</tr>")
    for k in rows:
        if k[0] != grp:
            grp = k[0]
            out.append(f'<tr class="group"><th colspan="{len(types) + 1}">{e(grp)}</th></tr>')
        cells = []
        for t in types:
            s = vals[k[1]].get(t["icao"])
            if not s:
                cells.append("<td>—</td>")
                continue
            cls = " class=\"best\"" if (one_review and s.get("best")) else ""
            v = f'<span class="est">{e(s["value"])}</span>' if s.get("est") else e(s["value"])
            note = '<span class="sm">%s</span>' % e(s["note"]) if s.get("note") else ""
            cells.append(f"<td{cls}>{v}{note}</td>")
        out.append(f"<tr><th>{e(k[1])}</th>{''.join(cells)}</tr>")
    miss = [t["short"] for t in types if not t.get("specs")]
    return (f'<section><div class="sec-head"><h2>{T("Лётно-технические характеристики")}</h2><p>'
            f'{T("Сверху — с чем считал расчёт; ниже — таблицы обзоров, значения как в обзоре, пунктир — оценка.")}'
            f'{" " + T("Точка — лучшее в строке.") if one_review else " " + T("Типы из разных обзоров: лучшее в строке не отмечается.")}'
            f'{" " + T("Нет в обзорах:") + " " + e(", ".join(miss)) + "." if miss else ""}</p></div>'
            f'<div class="tblwrap"><table><thead><tr><th>{T("Параметр")}</th>{head}</tr></thead>'
            f'<tbody>{"".join(out)}</tbody></table></div></section>')


def _plan_section(D: Doc, rep: dict, ok: list) -> str:
    T, a = D.T, rep["assume"]
    kv = [(T("Наша доля потока при рыночной цене"), D.pct(a["share"])),
          (T("Наша цена к рыночной"), f'× {D.n(a["price"], 2)}'),
          (T("Средний чек к минимальному"), (f'<span class="guess">× {D.n(a["fare_conv"], 2)}</span>'
                                             if abs((a.get("fare_conv") or 1) - 1) < 1e-9
                                             else f'× {D.n(a["fare_conv"], 2)}')),
          (T("Эластичность доли по цене"), f'<span class="guess">{D.n(a["elasticity"], 1)} · {T("допущение")}</span>'),
          (T("Плановая загрузка"), D.pct(a["lf_target"])),
          (T("Частота не реже"), f'{a["min_freq"]} {T("рейсов в неделю")}'),
          (T("Резерв парка"), f'{D.pct(a["reserve"])}, {T("не меньше борта")}')]
    eff = ok[0]["plan"]["share"]
    head = (f'<div class="assume"><div class="kv">{"".join(f"<div><span>{k}</span><b>{v}</b></div>" for k, v in kv)}</div>'
            f'<p class="small" style="margin:8px 0 0">{T("Доля после отклика на цену:")} <b>{D.pct(eff, 1)}</b>. '
            f'{T("Объём пары = поток × доля; рейсов — сколько нужно, чтобы вывезти объём при плановой загрузке, но не меньше нижней границы; бортов — налёт расписания на налёт борта, вверх до целого, плюс резерв.")}</p></div>')
    P = lambda t: t["plan"]                                      # noqa: E731
    brs = [
        bars(D, T("Итог в месяц"), [(t, P(t)["result"], "") for t in ok], lambda v: D.money(v, True), lo_best=False),
        bars(D, T("Бортов, с резервом"), [(t, P(t)["fleet"], f'{P(t)["n_op"]} + {P(t)["spare"]} {T("резерв")}') for t in ok],
             lambda v: D.n(v)),
        bars(D, T("Рейсов туда-обратно в неделю"), [(t, P(t)["freq_week"], "") for t in ok], lambda v: D.n(v)),
        bars(D, T("Загрузка"), [(t, P(t)["lf"], "") for t in ok], D.pct, lo_best=False),
        bars(D, T("Себестоимость пассажира"), [(t, P(t)["cost_per_pax"], f'{T("выручка")} {D.money(P(t)["rev_per_pax"])}') for t in ok],
             D.money),
        bars(D, T("Налёт борта, ч/мес"), [(t, P(t)["util_used"], f'{T("из")} {D.n(t["util_h_month"])}') for t in ok],
             lambda v: D.n(v), lo_best=False),
    ]
    # Пары: объём, частота и загрузка у каждого типа.
    keys = rep.get("common_pairs") or []
    vol = {p["key"]: p for p in ok[0]["plan"]["pairs"]}
    th = "".join(f'<th class="r" style="color:var(--t{t["slot"]})">{e(t["short"])}</th>' for t in ok)
    trs = []
    for k in keys:
        pv = vol.get(k) or {}
        cells = []
        for t in ok:
            p = next((x for x in t["plan"]["pairs"] if x["key"] == k), None)
            if not p:
                cells.append("<td class=r>—</td>")
                continue
            rng = ""
            if p.get("range_cap") is not None:
                rng = (f'<span class="rng" title="{e(T("дальность: на плече поднимает не больше"))} '
                       f'{D.pct(p["range_cap"])} {e(T("кресел"))}">{T("дальность")} ≤{D.pct(p["range_cap"])}</span>')
            cells.append(f'<td class="r{" bad" if p["min_binds"] else ""}">{p["freq"]}/{T("нед")} · {D.pct(p["lf"])}{rng}</td>')
        trs.append(f'<tr><th>{e(k)}<span class="sm">{D.n(pv.get("dist"))} {T("км")} · {T("поток")} '
                   f'{D.n(pv.get("market"))}/{T("мес")}</span></th><td class="r">{D.n(pv.get("volume"))}</td>{"".join(cells)}</tr>')
    tbl = (f'<div class="tblwrap" style="margin-top:22px"><table><thead><tr><th>{T("Пара")}</th>'
           f'<th class="r">{T("наших пасс./мес")}</th>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
           f'<p class="small">{T("В ячейке — рейсов туда-обратно в неделю и загрузка. Красным — частоту держит нижняя граница: объёма на эту частоту не хватает, борт летает полупустым.")} '
           f'<span class="rng">{T("дальность")} ≤80%</span> — {T("на плече борт по дальности поднимает не больше этой доли кресел: рейсы подобраны по этому пределу, а не по плановой загрузке, и их больше.")}</p>')
    return (f'<section><div class="sec-head"><h2>{T("Примерка на сеть: этот объём на этом типе")}</h2>'
            f'<p>{T("Объём перевозок один на все типы; рейсы, борты и деньги — у каждого свои.")}</p></div>'
            f'{head}<div class="bars">{"".join(brs)}</div>{tbl}</section>')


def _sweep_section(D: Doc, rep: dict, ok: list) -> str:
    T = D.T
    ps = rep["price_sweep"]
    th = "".join(f'<th class="r" style="color:var(--t{t["slot"]})">{e(t["short"])}</th>' for t in ok)
    trs = []
    for row in ps:
        best = max(row["types"].values(), key=lambda v: v["result"])["result"]
        cells = "".join(
            f'<td class="r{" best" if row["types"][t["icao"]]["result"] == best else ""}'
            f'{" bad" if row["types"][t["icao"]]["result"] < 0 else ""}">{D.money(row["types"][t["icao"]]["result"], True, unit=False)}'
            f'<span class="sm">{row["types"][t["icao"]]["fleet"]} {T("бортов")}</span></td>' for t in ok)
        cur = abs(row["price"] - rep["assume"]["price"]) < 1e-9
        trs.append(f'<tr><th>{"<b>" if cur else ""}× {D.n(row["price"], 2)}{"</b>" if cur else ""}'
                   f'<span class="sm">{T("доля")} {D.pct(row["share"], 1)}</span></th>{cells}</tr>')
    ss = rep["share_sweep"]
    th2 = th
    trs2 = []
    for row in ss:
        best = max(row["types"].values(), key=lambda v: v["result"])["result"]
        cells = "".join(
            f'<td class="r{" best" if row["types"][t["icao"]]["result"] == best else ""}'
            f'{" bad" if row["types"][t["icao"]]["result"] < 0 else ""}">{D.money(row["types"][t["icao"]]["result"], True, unit=False)}'
            f'<span class="sm">{row["types"][t["icao"]]["fleet"]} {T("бортов")}</span></td>' for t in ok)
        trs2.append(f'<tr><th>{D.pct(row["share"])}</th>{cells}</tr>')
    best_p = "; ".join(f'{e(t["short"])} — × {D.n(t["best_price"], 2)}' for t in ok)
    return (f'<section><div class="sec-head"><h2>{T("Цена и доля")}</h2><p>'
            f'{T("Ниже цена — больше доля по допущению об эластичности — больше пассажиров и бортов. Итог в месяц, в")} {D.cur}; '
            f'{T("точка — лучший тип в строке, красным — убыток.")}</p></div>'
            f'<div class="tblwrap"><table><thead><tr><th>{T("Цена к рынку")}</th>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
            f'<p class="small">{T("Лучшая цена по итогу:")} {best_p}.</p>'
            f'<h3 style="margin-top:24px">{T("Тонкий и толстый рынок")}</h3>'
            f'<p class="small">{T("Та же сеть при рыночной цене и разной доле: маленький борт выигрывает, пока объёма мало и частоту держит нижняя граница; большой — когда пассажиров хватает на его кресла.")}</p>'
            f'<div class="tblwrap"><table><thead><tr><th>{T("Доля потока")}</th>{th2}</tr></thead><tbody>{"".join(trs2)}</tbody></table></div></section>')


def toolbar(D: Doc, query: dict, a: dict) -> str:
    """Полоса над документом на сайте: допущения формой, скачать PDF и Excel."""
    T = D.T
    keep = {k: v for k, v in query.items() if k not in a}
    hidden = "".join(f'<input type="hidden" name="{e(k)}" value="{e(str(v))}">' for k, v in keep.items())
    qs = urllib.parse.urlencode(query)

    def fld(name, lab, val, step, unit=""):
        return (f'<label>{lab}<input name="{name}" type="number" step="{step}" value="{val}">'
                f'{f"<i>{unit}</i>" if unit else ""}</label>')
    return (f'<form class="tb noprint" method="get" action="/report">{hidden}'
            f'{fld("share", T("Доля потока"), round(a["share"] * 100, 1), "0.5", "%")}'
            f'{fld("price", T("Цена к рынку"), a["price"], "0.01", "×")}'
            f'{fld("fare_conv", T("Чек к минимуму"), a.get("fare_conv") or 1, "0.01", "×")}'
            f'{fld("elasticity", T("Эластичность"), a["elasticity"], "0.1")}'
            f'{fld("lf_target", T("Плановая загрузка"), round(a["lf_target"] * 100), "1", "%")}'
            f'{fld("min_freq", T("Рейсов в неделю не меньше"), a["min_freq"], "1")}'
            f'{fld("reserve", T("Резерв парка"), round(a["reserve"] * 100), "1", "%")}'
            f'<button class="go">{T("Пересчитать")}</button>'
            f'<a class="go" href="/api/fleetreport.pdf?{e(qs)}">PDF</a>'
            f'<a class="go" href="/api/fleetreport.xlsx?{e(qs)}">Excel</a></form>'
            f'<style>.tb{{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:flex-end;padding:12px 24px;'
            f'border-bottom:1px solid var(--d-rule);background:var(--d-card);position:sticky;top:0;z-index:5}}'
            f'.tb label{{display:flex;flex-direction:column;font-size:11.5px;color:var(--d-ink2);gap:3px}}'
            f'.tb input{{width:88px;background:var(--d-paper);color:var(--d-ink);border:1px solid var(--d-rule);'
            f'border-radius:5px;padding:5px 7px;font:13px var(--sans)}}.tb i{{display:none}}'
            f'.tb .go{{background:var(--d-paper);border:1px solid var(--d-rule);color:var(--d-ink);border-radius:5px;'
            f'padding:6px 12px;font:13px var(--sans);cursor:pointer;text-decoration:none}}'
            f'.tb .go:hover{{border-color:var(--t1)}}@media (max-width:640px){{.tb{{padding:10px 16px;position:static}}'
            f'.tb input{{width:72px}}}}</style>')
