"""Схемы статьи о сети: сутки борта с экипажами, воронка налёта, ротации, год ТО, сеть запчастей.

Все схемы — inline SVG на переменных темы (`var(--sky)` и т. д.), подписи — через T(ru, en, de). Схема — иллюстрация к тексту, а не данные: цифры в ней либо считаются той же
формулой, что в тексте, либо помечены «схема».
"""
from __future__ import annotations

from _report import T, e, n

FONT = 'font-family="var(--sans)"'


def _svg(w, h, body, label):
    return (f'<figure class="fig"><svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{e(label)}" '
            f'{FONT} font-size="12">{body}</svg></figure>')


def hh(t):
    t %= 24
    return f"{int(t):02d}:{round((t - int(t)) * 60):02d}"


# ── сутки борта ────────────────────────────────────────────────────────────
def day(cases, start=6.0, report=1.0, w=760):
    """cases: [(заголовок, блок ч, оборот мин, рейсов, [(экипаж, первый, последний)])].
    Явка экипажа — за `report` ч до вылета (допущение схемы)."""
    L, R, t0, t1 = 118, 16, 5.0, 25.0
    X = lambda t: L + (t - t0) / (t1 - t0) * (w - L - R)   # noqa: E731
    g, y = [], 8
    for t in range(6, 25, 2):
        g.append(f'<text x="{X(t):.1f}" y="{y + 10}" text-anchor="middle" fill="var(--dim)">{hh(t)}</text>')
    y += 18
    top = y
    for title, blk, tat, legs, crews in cases:
        g.append(f'<text x="0" y="{y + 12}" fill="var(--ink2)" font-weight="600">{e(title)}</text>')
        y += 20
        ts = [start + i * (blk + tat / 60) for i in range(legs)]
        g.append(f'<text x="{L - 8}" y="{y + 13}" text-anchor="end" fill="var(--ink)">{T("борт", "aircraft", "Flugzeug")}</text>')
        g.append(f'<rect x="{X(t0):.1f}" y="{y}" width="{X(start) - X(t0):.1f}" height="18" fill="var(--raise)"/>')
        for i, t in enumerate(ts):
            col = "var(--sky)" if i % 2 == 0 else "var(--t1)"
            g.append(f'<rect x="{X(t):.1f}" y="{y}" width="{X(t + blk) - X(t):.1f}" height="18" rx="3" fill="{col}"/>'
                     f'<text x="{(X(t) + X(t + blk)) / 2:.1f}" y="{y + 13}" text-anchor="middle" fill="#fff" '
                     f'font-size="11">{T("туда", "out", "hin") if i % 2 == 0 else T("обратно", "back", "zurück")}</text>')
        end = ts[-1] + blk
        g.append(f'<rect x="{X(end):.1f}" y="{y}" width="{X(t1) - X(end):.1f}" height="18" fill="var(--raise)"/>')
        y += 24
        for name, a, b in crews:
            s, f = ts[a - 1] - report, ts[b - 1] + blk
            inside = X(f) + 140 > w
            g.append(f'<text x="{L - 8}" y="{y + 11}" text-anchor="end" fill="var(--dim)">{e(name)}</text>'
                     f'<rect x="{X(s):.1f}" y="{y + 1}" width="{X(f) - X(s):.1f}" height="13" rx="2" '
                     f'fill="none" stroke="var(--green)"/>'
                     f'<text x="{X(f) - 6 if inside else X(f) + 6:.1f}" y="{y + 11}" fill="var(--green)" font-size="11" '
                     f'text-anchor="{"end" if inside else "start"}">'
                     + T(f"смена {n(f - s, 1)} ч, {b - a + 1} сект.", f"duty {n(f - s, 1)} h, {b - a + 1} sect.",
                         f"Dienst {n(f - s, 1)} h, {b - a + 1} Sekt.") + '</text>')
            y += 16
        g.append(f'<text x="{L}" y="{y + 12}" fill="var(--ink)">'
                 + T(f"{legs} рейсов × {n(blk, 1)} ч = ", f"{legs} flights × {n(blk, 1)} h = ",
                     f"{legs} Flüge × {n(blk, 1)} h = ")
                 + f'<tspan font-weight="600" fill="var(--ink2)">'
                 + T(f"{n(legs * blk, 1)} блок-часа", f"{n(legs * blk, 1)} block hours", f"{n(legs * blk, 1)} Blockstunden")
                 + '</tspan> · ' + T("последний прилёт", "last arrival", "letzte Landung") + f' {hh(end)}</text>')
        y += 30
    g.insert(0, f'<line x1="{X(24):.1f}" x2="{X(24):.1f}" y1="{top - 4}" y2="{y - 20}" stroke="var(--line)" '
                f'stroke-dasharray="3 3"/>')
    return _svg(w, y, "".join(g), T("Сутки борта и смены экипажей", "An aircraft's day and crew duties",
                                     "Ein Flugzeugtag und die Crew-Dienste"))


# ── воронка: от 24 часов к среднему за год ─────────────────────────────────
def funnel(steps, w=760):
    """steps: [(подпись, часов, пояснение)] — по убыванию; рисует, сколько остаётся."""
    L, R, H = 210, 60, 30
    X = lambda v: L + v / 24 * (w - L - R)   # noqa: E731
    g = []
    for i, (lab, v, why) in enumerate(steps):
        y = 6 + i * H
        g.append(f'<text x="{L - 10}" y="{y + 14}" text-anchor="end" fill="var(--ink)">{e(lab)}</text>'
                 f'<rect x="{L}" y="{y}" width="{X(24) - L:.1f}" height="20" rx="3" fill="var(--raise)"/>'
                 f'<rect x="{L}" y="{y}" width="{X(v) - L:.1f}" height="20" rx="3" '
                 f'fill="{"var(--sky)" if i < len(steps) - 1 else "var(--green)"}"/>'
                 f'<text x="{X(v) + 6:.1f}" y="{y + 14}" fill="var(--ink2)" font-weight="600">{n(v, 1)} {T("ч", "h", "h")}</text>'
                 f'<text x="{L + 6}" y="{y + 14}" fill="#fff" font-size="11">{e(why)}</text>')
    return _svg(w, 12 + H * len(steps), "".join(g), T("Как сутки превращаются в средний налёт",
                                                       "How a day turns into average utilisation",
                                                       "Wie aus einem Tag die durchschnittliche Auslastung wird"))


# ── три способа построить день ─────────────────────────────────────────────
def patterns(w=760):
    L, R, t0, t1 = 8, 12, 5.5, 24.5
    X = lambda t: L + (t - t0) / (t1 - t0) * (w - L - R)   # noqa: E731
    # пункты: b — база, a/x/y — пункты назначения, h — хаб, c — город сети
    LET = {"b": T("Б", "B", "B"), "a": "A", "x": T("B", "X", "X"), "y": T("C", "Y", "Y"),
           "h": T("Х", "H", "H"), "c": T("Г", "C", "S")}
    C = {"b": "var(--sky)", "a": "var(--t2)", "x": "var(--t3)", "y": "var(--t4)", "h": "var(--t5)", "c": "var(--sky)"}
    rows = [
        (T("Челнок от базы", "Base shuttle", "Pendel ab Basis"),
         T("три пары «туда-обратно», ночёвка дома", "three out-and-back pairs, night at home",
           "drei Hin- und Rückflüge, Nacht zu Hause"),
         [(6.0, 2.0, "ba"), (8.4, 2.0, "ab"), (10.8, 2.0, "ba"), (13.2, 2.0, "ab"), (15.6, 2.0, "ba"),
          (18.0, 2.0, "ab")]),
        (T("W-ротация", "W rotation", "W-Rotation"),
         T("разные пункты, остаток окна добран", "different points, the rest of the window used",
           "verschiedene Ziele, Restfenster genutzt"),
         [(6.0, 2.0, "ba"), (8.4, 2.0, "ab"), (10.8, 1.5, "bx"), (12.7, 1.5, "xy"), (14.6, 2.5, "yb"),
          (17.5, 2.5, "ba"), (20.4, 2.5, "ab")]),
        (T("Через хаб", "Via the hub", "Über den Hub"),
         T("город Г ↔ хаб Х: прилёт к волне, ожидание следующей", "city C ↔ hub H: arrive for a bank, wait for the next",
           "Stadt S ↔ Hub H: Ankunft zur Welle, Warten auf die nächste"),
         [(5.6, 1.5, "ch"), (8.0, 1.5, "hc"), (10.1, 1.5, "ch"), (12.5, 1.5, "hc"), (14.9, 1.5, "ch"),
          (17.3, 1.5, "hc"), (19.7, 1.5, "ch")]),
    ]
    g = [f'<text x="{X(t):.1f}" y="12" text-anchor="middle" fill="var(--dim)">{hh(t)}</text>' for t in range(6, 25, 3)]
    y = 26
    waves = (7.5, 12.0, 16.8, 21.6)
    for k, (title, sub, legs) in enumerate(rows):
        g.append(f'<text x="{L}" y="{y + 10}"><tspan fill="var(--ink2)" font-weight="600">{e(title)}</tspan>'
                 f'<tspan fill="var(--dim)" font-size="11" dx="10">{e(sub)}</tspan></text>')
        y += 18
        if k == 2:
            for wv in waves:
                g.append(f'<rect x="{X(wv - 0.5):.1f}" y="{y - 4}" width="{X(wv + 0.6) - X(wv - 0.5):.1f}" height="28" '
                         f'fill="var(--t5)" opacity=".35"/>')
            g.append(f'<text x="{L}" y="{y + 38}" fill="var(--t5)" font-size="11">'
                     + T("волны хаба: прилёты и вылеты стыкуются в окне",
                         "hub banks: arrivals and departures connect within a window",
                         "Hub-Wellen: Ankünfte und Abflüge treffen sich in einem Fenster") + '</text>')
        for t, b, (fr, to) in legs:
            lab = f"{LET[fr]}→{LET[to]}"
            g.append(f'<rect x="{X(t):.1f}" y="{y}" width="{X(t + b) - X(t):.1f}" height="20" rx="3" fill="{C[to]}"/>'
                     f'<text x="{(X(t) + X(t + b)) / 2:.1f}" y="{y + 14}" text-anchor="middle" fill="#fff" '
                     f'font-size="11">{lab}</text>')
        tot = sum(b for _, b, _ in legs)
        g.append(f'<text x="{w - R}" y="{y + 38}" text-anchor="end" fill="var(--ink)">{n(tot, 1)} '
                 + T("блок-ч", "block h", "Block-h") + '</text>')
        y += 50
    return _svg(w, y - 4, "".join(g), T("Челнок, W-ротация и рейсы через хаб", "Shuttle, W rotation and flights via the hub",
                                    "Pendel, W-Rotation und Flüge über den Hub"))


# ── год ТО ─────────────────────────────────────────────────────────────────
def year(profile, a_fh=750, sector_h=2.0, taxi_h=1 / 3, c_months=(0,), w=760):
    """profile — блок-часы в сутки по месяцам (схема); форма A — каждые a_fh лётных часов."""
    M = T(("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"),
          ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
          ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"))
    D = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    L, R, TOP, H = 40, 14, 18, 120
    X = lambda d: L + d / 365 * (w - L - R)   # noqa: E731
    Y = lambda v: TOP + H - v / 16 * H   # noqa: E731
    g, d0, fh, marks = [], 0, 0.0, []
    for v in (4, 8, 12, 16):
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="var(--dim)" font-size="11">{v}</text>')
    for i, (m, dd, bh) in enumerate(zip(M, D, profile)):
        if i in c_months:
            g.append(f'<rect x="{X(d0 + 8):.1f}" y="{TOP}" width="{X(d0 + 22) - X(d0 + 8):.1f}" height="{H}" '
                     f'fill="var(--orange)" opacity=".25"/>'
                     f'<text x="{X(d0 + 24):.1f}" y="{TOP + 12}" fill="var(--orange)" font-size="11">'
                     + T("форма C — около двух недель на земле, в низкий сезон",
                         "C-check — about two weeks on the ground, in the low season",
                         "C-Check — etwa zwei Wochen am Boden, in der Nebensaison") + '</text>')
        g.append(f'<rect x="{X(d0) + 2:.1f}" y="{Y(bh):.1f}" width="{X(d0 + dd) - X(d0) - 4:.1f}" '
                 f'height="{TOP + H - Y(bh):.1f}" rx="2" fill="var(--sky)" opacity=".75"/>'
                 f'<text x="{(X(d0) + X(d0 + dd)) / 2:.1f}" y="{TOP + H + 14}" text-anchor="middle" '
                 f'fill="var(--dim)" font-size="11">{m}</text>')
        f_day = bh * (1 - taxi_h / sector_h)
        for k in range(dd):
            fh += f_day
            if fh >= a_fh:
                fh -= a_fh
                marks.append(d0 + k)
        d0 += dd
    for d in marks:
        g.append(f'<path d="M{X(d):.1f} {TOP + H + 20} l-5 9 h10 z" fill="var(--green)"/>')
    g.append(f'<text x="{L}" y="{TOP + H + 44}" fill="var(--green)" font-size="11">'
             + T(f"▲ форма A: каждые {n(a_fh)} лётных часов — {len(marks)} за год, ночью на базе",
                 f"▲ A-check: every {n(a_fh)} flight hours — {len(marks)} a year, overnight at base",
                 f"▲ A-Check: alle {n(a_fh)} Flugstunden — {len(marks)} im Jahr, nachts an der Basis") + '</text>'
             f'<text x="{w - R}" y="{TOP + H + 62}" text-anchor="end" fill="var(--dim)" font-size="11">'
             + T("столбики — блок-часы борта в сутки по месяцам (схема)",
                 "bars — aircraft block hours per day by month (schematic)",
                 "Balken — Blockstunden je Flugzeug und Tag nach Monat (Schema)") + '</text>')
    return _svg(w, TOP + H + 70, "".join(g), T("Год технического обслуживания", "A maintenance year", "Ein Wartungsjahr"))


# ── слои запаса: от поставщика до борта ────────────────────────────────────
def layers(rows, w=760):
    """rows: [(слой, что лежит, как быстро до самолёта, цвет)] — сверху далеко от самолёта, снизу — на борту."""
    H, L = 54, 30
    g = [f'<line x1="14" x2="14" y1="10" y2="{H * len(rows) - 6}" stroke="var(--dim)"/>'
         f'<path d="M14 {H * len(rows)} l-5 -9 h10 z" fill="var(--dim)"/>'
         f'<text x="22" y="{H * len(rows) + 2}" fill="var(--dim)" font-size="11">' + T("ближе к самолёту — быстрее, но дороже держать",
                                     "closer to the aircraft — faster, but more expensive to hold",
                                     "näher am Flugzeug — schneller, aber teurer im Bestand") + '</text>']
    for i, (a, b, c, col) in enumerate(rows):
        y = 4 + i * H
        g.append(f'<rect x="{L}" y="{y}" width="{w - L - 4}" height="{H - 10}" rx="6" fill="var(--panel)" '
                 f'stroke="{col}"/><rect x="{L}" y="{y}" width="6" height="{H - 10}" rx="3" fill="{col}"/>'
                 f'<text x="{L + 16}" y="{y + 18}" fill="var(--ink2)" font-weight="600">{e(a)}</text>'
                 f'<text x="{L + 16}" y="{y + 35}" fill="var(--dim)" font-size="11.5">{e(b)}</text>'
                 f'<text x="{w - 14}" y="{y + 18}" text-anchor="end" fill="{col}" font-size="11.5">{e(c)}</text>')
    return _svg(w, H * len(rows) + 10, "".join(g), T("Где лежат запчасти", "Where spare parts are kept",
                                                     "Wo Ersatzteile liegen"))
