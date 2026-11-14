#!/usr/bin/env python3
"""Статья «Какие маршруты привлекательны для авиакомпании: Европа и Индия» + рейтинг пар (обновляемый).

Данные — out/r1.json (как оценивают маршрут), out/r2.json (открытые данные, слоты, UDAN, доли), out/rating.json
(рейтинг, собирает rating.py из out/pairs_eu.json и out/pairs_in.json); журналы — trace/r1, r2; проверка — verify/.
Поправки проверяющего r1: R² гравитационной модели 0,70–0,76 (r1-120); без «PSO ~4 года» (r1-097); r1-217 не берём.

Статья собирается на трёх языках (report.html, report.en.html, report.de.html); строки из данных исследования
переводятся через i18n.yaml.

    python3 research/routes-2026-11/rating.py && python3 research/routes-2026-11/build_report.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from _report import (ARTICLE_CSS, Sources, T, Tr, article_title, calc_badge, e, mark, money, n, page,  # noqa: E402
                     write_all)
import _report  # noqa: E402

TR = Tr(HERE)

S = Sources(HERE)
_PAR = {o["id"]: o.get("parents") or [] for f in sorted(HERE.glob("trace/r*.jsonl"))
        for o in map(json.loads, f.read_text(encoding="utf-8").splitlines())}


def _roots(i, seen=None):
    seen = seen or set()
    if i in S.step or i in seen:
        return [i] if i in S.step else []
    seen.add(i)
    return [r for p in _PAR.get(i, []) for r in _roots(p, seen)]


def cite(*ids):
    return S.cite(*[r for i in ids for r in _roots(i)])


J = lambda f: json.loads((HERE / f).read_text(encoding="utf-8"))  # noqa: E731
R1, R2, RT = J("out/r1.json"), J("out/r2.json"), J("out/rating.json")
VER = {f: J(f"verify/{f}.json") for f in ("r1", "r2") if (HERE / f"verify/{f}.json").exists()}
EU, EUL, IN = RT["europe"]["pairs"], RT["europe"]["long_haul"], RT["india"]["pairs"]
A = J("out/airports.json")
sys.path.insert(0, str(HERE))
from rating import IN_ICAO as IN_CITY  # noqa: E402


def short(name):
    s = re.sub(r"\b(International|Intl\.?|Airport|Aeropuerto|Aéroport|Aeroporto|Flughafen|Airfield)\b", "", name)
    s = re.sub(r"\s+", " ", s).strip(" –-")
    return s[:34]


# Аэропорты в пригородах: OurAirports пишет муниципалитет (Zaventem, Otopeni), а читателю нужен город.
CITYFIX = {"EBBR": "Brussels", "EBCI": "Brussels-Charleroi", "LROP": "Bucharest", "LIME": "Bergamo", "LIMC": "Milan",
           "LIML": "Milan", "EGLL": "London", "EGKK": "London", "EGSS": "London", "EGGW": "London", "EGLC": "London",
           "LFPG": "Paris", "LFPO": "Paris", "LFPB": "Paris", "ESSA": "Stockholm", "ENGM": "Oslo", "EKCH": "Copenhagen",
           "EDDM": "Munich", "LIRF": "Rome", "LIRA": "Rome", "LTFM": "Istanbul", "LTFJ": "Istanbul",
           "UUEE": "Moscow", "UUDD": "Moscow", "UUWW": "Moscow", "LKPR": "Prague", "EPWA": "Warsaw", "EPMO": "Warsaw",
           "LHBP": "Budapest", "LOWW": "Vienna", "EHAM": "Amsterdam", "LSZH": "Zurich", "EIDW": "Dublin",
           "LPPT": "Lisbon", "LGAV": "Athens", "EFHK": "Helsinki", "EVRA": "Riga", "EYVI": "Vilnius",
           "LBSF": "Sofia", "EDDF": "Frankfurt", "EDDB": "Berlin", "LEMD": "Madrid", "LEBL": "Barcelona"}


def city(icao):
    v = A.get(icao) or []
    c = CITYFIX.get(icao) or (v[4] if len(v) > 4 and v[4] else (v[3] if len(v) > 3 else icao))
    c = c.split(" (")[0].split(",")[-1].strip()
    return f"{c} {v[5]}" if len(v) > 5 and v[5] else c


def label(r):
    if "names" in r:
        return f"{city(r['a'])} — {city(r['b'])}"
    return f"{r['a']} — {r['b']}"


AC = J("out/aircraft.json")["pairs"] if (HERE / "out/aircraft.json").exists() else {}
TYPE = {"A20N": "A320neo", "A21N": "A321neo", "B38M": "737 MAX 8", "B39M": "737 MAX 9", "BCS3": "A220-300",
        "A359": "A350-900", "B789": "787-9", "T204": "Ту-214", "SU95": "SJ-100", "MS21": "МС-21",
        "E295": "E195-E2"}
_TYPE_LAT = {"T204": "Tu-214", "MS21": "MC-21"}


def tname(code):
    """Название типа на языке статьи (Ту-214 / Tu-214)."""
    if _report.LANG != "ru" and code in _TYPE_LAT:
        return _TYPE_LAT[code]
    return TYPE.get(code, code)
CP = J("out/competitors.json")["pairs"] if (HERE / "out/competitors.json").exists() else {}


def comp(r):
    """Наблюдения ADS-B по паре: None — пара не забиралась, иначе сводка."""
    k = "-".join(sorted(r["icao"] if "icao" in r else (r["a"], r["b"])))
    v = CP.get(k)
    return v if v and v["days"] else None


def comp_cell(r):
    v = comp(r)
    if not v:
        return T("не забиралась", "not collected", "nicht erfasst")
    if not v["carriers"]:
        return T("рейсов не видно", "no flights seen", "keine Flüge sichtbar")
    lat = {"Аэрофлот": "Aeroflot"} if _report.LANG != "ru" else {}
    return " · ".join(f"<b>{e(lat.get(c['name'], c['name']))}</b> {n(c['per_day'], 1)}"
                      + (f" <span class=s>({e(', '.join(c['types'][:2]))})</span>" if c["types"] else "")
                      for c in v["carriers"][:4])


def comp_table(rows):
    head = (f"<tr><th class=r>#</th><th>{T('Пара', 'Pair', 'Paar')}</th>"
            f"<th class=r>{T('Рейсов в день', 'Flights per day', 'Flüge pro Tag')}</th>"
            f"<th class=r>{T('Доля лидера', 'Leader share', 'Anteil des Marktführers')}</th>"
            f"<th>{T('Кто летает: рейсов в день (типы)', 'Who flies: flights per day (types)', 'Wer fliegt: Flüge pro Tag (Typen)')}</th></tr>")
    body = "".join(
        f"<tr><td class=r>{r['rank']}</td><td class=nm>{e(label(r))}</td>"
        f"<td class=r>{n(comp(r)['per_day'], 1) if comp(r) and comp(r)['carriers'] else '—'}</td>"
        f"<td class=r>{n(comp(r)['leader_share'] * 100, 0) + ' %' if comp(r) and comp(r)['carriers'] else '—'}</td>"
        f"<td>{comp_cell(r)}</td></tr>" for r in rows)
    return f'<div class="tw"><table class="txt">{head}{body}</table></div>'


# Семейства типов: цвет на карте и в диаграмме парка. Оранжевый не берём — он в статьях значит «оценка».
FAM = [  # ключ, подпись, коды ИКАО, цвет
    ("a320ceo", "A320ceo / A321ceo", {"A318", "A319", "A320", "A321"}, "#7fa7d9"),
    ("a320neo", "A320neo / A321neo", {"A20N", "A21N"}, "#2f6fe0"),
    ("b737ng", "737-700/800/900", {"B737", "B738", "B739"}, "#b8a3e6"),
    ("b737max", "737 MAX", {"B38M", "B39M"}, "#7c4ddb"),
    ("reg", "A220 / E-Jet", {"BCS1", "BCS3", "E170", "E190", "E195", "E290", "E295"}, "#14a89a"),
    ("ru", "Ту-214 / SJ-100", {"T204", "SU95", "MS21"}, "#c0504d"),   # подпись — flab(): Tu-214 на en/de
    ("a330", "A330", {"A332", "A333", "A339"}, "#8bbf3f"),
    ("a350", "A350", {"A359", "A35K"}, "#1f9d55"),
    ("b787", "787", {"B788", "B789"}, "#d9488f"),
    ("b777", "777", {"B77W"}, "#d4a514"),
]
FCOL = {k: c for k, _, _, c in FAM}
FLAB = {k: t for k, t, _, _ in FAM}


def flab(k):
    return FLAB[k].replace("Ту-214", "Tu-214") if _report.LANG != "ru" else FLAB[k]


def fam_of(code):
    return next((k for k, _, s, _ in FAM if code in s), None)


def fam_mix(r):
    """Рейсов по семействам на паре (известный тип), по убыванию."""
    v = comp(r)
    m = Counter()
    for t, f in ((v or {}).get("mix") or {}).items():
        if fam_of(t):
            m[fam_of(t)] += f
    return m.most_common()


IMG = HERE / "img"


def thumb(key):
    """Фото типа для легенды, если владелец положил img/<ключ>.jpg (+ строка в img/credits.yaml);
    иначе — силуэт цветом семейства."""
    import base64
    f = IMG / f"{key}.jpg"
    if f.exists():
        b = base64.b64encode(f.read_bytes()).decode()
        return f'<img src="data:image/jpeg;base64,{b}" alt="" class="ph">'
    # Вид сверху, нос вправо: законцовки крыла и стабилизатора — позади корня (стреловидность назад).
    return (f'<svg class="ph" viewBox="0 0 64 28"><path fill="{FCOL[key]}" d="'
            'M4 13 Q4 12 7 12 L52 12 Q60 12 63 14 Q60 16 52 16 L7 16 Q4 16 4 15 Z'   # фюзеляж
            'M38 12 L25 1.5 L21.5 1.5 L28 12 Z M38 16 L25 26.5 L21.5 26.5 L28 16 Z'   # крыло
            'M11 12 L4.5 5 L2.5 5 L5.5 12 Z M11 16 L4.5 23 L2.5 23 L5.5 16 Z'         # стабилизатор
            '"/></svg>')


def credits():
    f = IMG / "credits.yaml"
    if not f.exists():
        return ""
    import yaml
    c = yaml.safe_load(f.read_text("utf-8")) or {}
    return T("Фото: ", "Photos: ", "Fotos: ") + "; ".join(f"{flab(k) if k in FLAB else k} — {e(v.get('author', ''))}, {e(v.get('license', ''))}"
                                for k, v in c.items()) + "."


def fam_legend(keys):
    return ('<div class="flg">' + "".join(
        f'<span class="fl"><span class="sw" style="background:{FCOL[k]}"></span>{thumb(k)}<span>{e(flab(k))}</span></span>'
        for k in keys) + "</div>")


def fleet_chart(rows):
    """Парк на паре: полоса = рейсов в день в одну сторону, сегменты — семейства типов. HTML, чтобы на телефоне
    подпись вставала над полосой, а не сжималась."""
    rows = [r for r in rows if comp(r) and comp(r)["carriers"]]
    if not rows:
        return ""
    mx = max(comp(r)["per_day"] for r in rows)
    out, used = [], set()
    for r in rows:
        v = comp(r)
        idx = [k for k, *_ in FAM]
        mix = sorted(fam_mix(r), key=lambda x: idx.index(x[0]))
        tot = sum(f for _, f in mix) or 1
        segs = ""
        for k, f in mix:
            used.add(k)
            segs += (f'<i style="width:{f / tot * 100:.1f}%;background:{FCOL[k]}" '
                     f'title="{e(flab(k))} — {n(f / tot * 100, 0)} %"></i>')
        out.append(f'<div class="fr"><span class="fn">{r["rank"]}. {e(label(r))}</span><span class="fb">'
                   f'<span class="fs" style="width:{v["per_day"] / mx * 88:.1f}%">{segs}</span>'
                   f'<span class="fv">{n(v["per_day"], 1)}</span></span></div>')
    order = [k for k, *_ in FAM if k in used]
    cap = T("Длина полосы — рейсов в день в одну сторону, сегменты — доли рейсов по семействам типов (рейсы с "
            "известным типом).",
            "Bar length — flights per day in each direction; segments — share of flights by aircraft family (flights "
            "with a known type).",
            "Balkenlänge — Flüge pro Tag je Richtung; Segmente — Anteil der Flüge nach Flugzeugfamilie (Flüge mit "
            "bekanntem Typ).")
    return (f'<figure class="fig fc">{"".join(out)}<figcaption class="leg">{fam_legend(order)}{cap}</figcaption>'
            f'</figure>')


RU_T = {"T204", "SU95", "MS21"}
TCOL = {"E295": "#a8763e", "SU95": "#e08a8a", "A21N": "#1d4fb8"}  # отличить внутри семейства в сводке


def share_calc():
    """Калькулятор на странице: доля рынка → какой тип даёт не меньше N рейсов в день и самый дешёвый на пассажира.
    Данные — безубыточный тариф и пассажиров на рейс (80 %) по типам из out/aircraft.json; на парах с Россией —
    только типы, доступные российским перевозчикам."""
    data = {}
    for reg, rows, india in (("eu", EU[:20], False), ("eul", EUL[:10], False), ("in", IN[:20], True)):
        out = []
        for r in rows:
            a = AC.get(r["pair"])
            if not a:
                continue
            ru = bool(a.get("russia"))
            ts = [[tname(x["type"]), round(x["fare"], 1), round(x["pax"]),
                   TCOL.get(x["type"]) or FCOL.get(fam_of(x["type"]) or "", "#888")]
                  for x in a["all"] if x["ok"] and x.get("fare") and x.get("pax") and (x["type"] in RU_T) == ru]
            if not ts:
                continue
            c = comp(r)
            out.append({"r": r["rank"], "l": label(r), "p": r["pax"], "t": ts,
                        "n": len(c["carriers"]) if c and c["carriers"] else None})
        data[reg] = out
    js = r"""
(function(){var D=__DATA__,L=__L__,el=document.getElementById('shc');if(!el)return;
var q=function(s){return el.querySelector(s)};
function fmt(v,d){return v.toLocaleString(L.loc,{minimumFractionDigits:d||0,maximumFractionDigits:d||0})}
function run(){var reg=q('#shc-reg').value,thr=+q('#shc-thr').value,auto=q('#shc-auto').checked,sh=+q('#shc-sh').value/100;
q('#shc-shv').textContent=fmt(sh*100)+' %';q('#shc-auto').parentNode.style.display=(reg==='in')?'none':'';
var rows=D[reg],cnt={},col={},html='';
rows.forEach(function(p){var s=(auto&&p.n&&reg!=='in')?1/(p.n+1):sh;
 var ts=p.t.map(function(t){return{n:t[0],f:t[1],x:t[2],c:t[3],pd:p.p*s/365/2/t[2]}});
 var cheap=Math.min.apply(null,ts.map(function(t){return t.f}));
 var ok=ts.filter(function(t){return t.pd>=thr}),b,low=false;
 if(ok.length){b=ok.reduce(function(a,c){return c.f<a.f?c:a})}else{var mx=Math.max.apply(null,ts.map(function(t){return t.pd}));
 b=ts.filter(function(t){return t.pd>=0.9*mx}).reduce(function(a,c){return c.f<a.f?c:a});low=true}
 cnt[b.n]=(cnt[b.n]||0)+1;col[b.n]=b.c;
 html+='<tr><td class=nm data-l="'+L.pair+'">'+p.r+'. '+p.l+'</td>'+
  '<td data-l="'+L.share+'" class="r shr">'+fmt(s*100)+' %</td>'+
  '<td data-l="'+L.type+'"><span><span class=sw style="background:'+b.c+'"></span> <b>'+b.n+'</b>'+(low?' <span class=s>'+L.low.replace('{n}',thr)+'</span>':'')+'</span></td>'+
  '<td class=r data-l="'+L.pd+'">'+fmt(Math.floor(b.pd*10)/10,1)+'</td><td class=r data-l="'+L.fare+'"><span class="mny" data-v="'+b.f+'" data-c="EUR" data-d="0" data-s="0" data-u="">'+fmt(b.f)+' EUR</span></td>'+
  '<td class=r data-l="'+L.cheap+'">'+(b.f>cheap?'+'+fmt((b.f/cheap-1)*100)+' %':'—')+'</td></tr>'});
q('#shc-sum').innerHTML=Object.keys(cnt).sort(function(a,b){return cnt[b]-cnt[a]}).map(function(k){
 return '<span class=chip><span class=sw style="background:'+col[k]+'"></span>'+k+' — '+cnt[k]+'</span>'}).join(' ');
q('#shc-body').innerHTML=html;if(window.fcaCurShow)window.fcaCurShow()}
el.addEventListener('input',run);el.addEventListener('change',run);run()})();
""".replace("__DATA__", json.dumps(data, ensure_ascii=False))
    lab = {"loc": T("ru-RU", "en-GB", "de-DE"), "pair": T("Пара", "Pair", "Paar"), "share": T("Доля", "Share", "Anteil"),
           "type": T("Тип", "Type", "Typ"), "pd": T("Рейсов в день", "Flights per day", "Flüge pro Tag"),
           "fare": T("Тариф", "Fare", "Tarif"),
           "cheap": T("К самому дешёвому", "vs cheapest", "ggü. günstigstem"),
           "low": T("меньше {n} рейс.", "fewer than {n} flights", "weniger als {n} Flüge")}
    js = js.replace("__L__", json.dumps(lab, ensure_ascii=False))
    return f"""<div id="shc" class="shc">
<div class="shc-ctl"><label>{T('Рынок', 'Market', 'Markt')} <select id="shc-reg"><option value="eu">{T('Европа', 'Europe', 'Europa')}</option>
<option value="in">{T('Индия', 'India', 'Indien')}</option>
<option value="eul">{T('Европа, дальние', 'Europe, long-haul', 'Europa, Langstrecke')}</option></select></label>
<label>{T('Наша доля рынка пары', 'Our share of the pair market', 'Unser Marktanteil am Paar')} <input id="shc-sh" type="range" min="5" max="100" step="5" value="25"> <b id="shc-shv"></b></label>
<label>{T('Минимум рейсов в день', 'Minimum flights per day', 'Mindestens Flüge pro Tag')} <select id="shc-thr"><option value="1">1</option><option value="2" selected>2</option>
<option value="3">3</option></select></label>
<label class="chk"><input id="shc-auto" type="checkbox"> {T('доля по числу перевозчиков на паре: 1 ÷ (n + 1)', 'share by number of carriers on the pair: 1 ÷ (n + 1)', 'Anteil nach Zahl der Airlines auf dem Paar: 1 ÷ (n + 1)')}</label></div>
<div id="shc-sum" class="shc-sum"></div>
<div class="tw"><table class="txt nocards shc-t"><thead><tr><th>{lab['pair']}</th><th class=r>{lab['share']}</th><th>{lab['type']}</th>
<th class=r>{lab['pd']}</th><th class=r>{lab['fare']}</th><th class=r>{lab['cheap']}</th></tr></thead>
<tbody id="shc-body"></tbody></table></div></div><script>{js}</script>"""


COL = {"dom": "var(--sky)", "int": "var(--orange)", "long": "var(--green)"}


def kind(r, india=False):
    if india:
        return "dom"
    if (r.get("km") or 0) > 4500:
        return "long"
    c = r.get("countries") or ["", ""]
    return "dom" if c[0] == c[1] else "int"


def rmap(reg, rows, india=False, w=760, mode="tk"):
    """Карта топ-пар: суша Natural Earth (упрощённая вырезка), дуги пар цветом типа перевозок."""
    import math
    land = J(f"out/land_{reg}.json")
    x0, y0, x1, y1 = land["box"]
    k = math.cos(math.radians((y0 + y1) / 2))
    sc = w / ((x1 - x0) * k)
    h = (y1 - y0) * sc
    P = lambda lon, lat: ((lon - x0) * k * sc, (y1 - lat) * sc)  # noqa: E731
    g = [f'<rect width="{w}" height="{h:.0f}" fill="var(--ocean)"/>']
    for poly in land["polys"]:
        d = "M" + "L".join(f"{P(x, y)[0]:.1f},{P(x, y)[1]:.1f}" for x, y in poly) + "Z"
        g.append(f'<path d="{d}" fill="var(--land)" stroke="var(--line)" stroke-width=".5"/>')
    pts, fams = {}, set()
    for i, r in enumerate(rows, 1):
        ia, ib = (r["icao"] if india else (r["a"], r["b"]))
        if ia not in A or ib not in A:
            continue
        (xa, ya), (xb, yb) = P(A[ia][1], A[ia][0]), P(A[ib][1], A[ib][0])
        mx, my = (xa + xb) / 2, (ya + yb) / 2
        dx, dy = xb - xa, yb - ya
        cx, cy = mx - dy * 0.18, my + dx * 0.18
        col = COL[kind(r, india)]
        mix = fam_mix(r)
        fcol = FCOL[mix[0][0]] if mix else "var(--dim)"
        if mix:
            fams.add(mix[0][0])
        arc_t = (f'<path class="ac" d="M{xa:.1f},{ya:.1f} Q{cx:.1f},{cy:.1f} {xb:.1f},{yb:.1f}" fill="none" '
                 f'stroke="{fcol}" stroke-width="3.2" {"" if mix else 'stroke-dasharray="4 4" '}opacity=".95">'
                 f'<title>{e(label(r))}: ' + (", ".join(f"{flab(k)} {n(f / sum(x for _, x in mix) * 100, 0)} %"
                                                   for k, f in mix[:3]) if mix else
                                         T("нет наблюдений", "no observations", "keine Beobachtungen")) + '</title></path>')
        g.append(arc_t)
        g.append(f'<path class="tk" d="M{xa:.1f},{ya:.1f} Q{cx:.1f},{cy:.1f} {xb:.1f},{yb:.1f}" fill="none" stroke="{col}" '
                 f'stroke-width="2.4" opacity=".9"><title>{e(label(r))}: {n(r["pax"])} {T("пасс.", "pax", "Pax")}</title></path>'
                 f'<circle class="tk" cx="{(mx + cx) / 2:.1f}" cy="{(my + cy) / 2:.1f}" r="9" fill="var(--bg)" stroke="{col}"/>'
                 f'<circle class="ac" cx="{(mx + cx) / 2:.1f}" cy="{(my + cy) / 2:.1f}" r="9" fill="var(--bg)" stroke="{fcol}"/>'
                 f'<text x="{(mx + cx) / 2:.1f}" y="{(my + cy) / 2 + 4:.1f}" text-anchor="middle" font-size="11" '
                 f'fill="var(--ink2)" font-weight="600">{i}</text>')
        for ic, (x, y) in ((ia, (xa, ya)), (ib, (xb, yb))):
            pts[ic] = (x, y)
    for ic, (x, y) in pts.items():
        nm = (r["a"] if False else None)
        lab = city(ic) if not india else next((c for c, v in IN_CITY.items() if v == ic), ic)
        right = x > w - 120
        g.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="var(--ink2)"/>'
                 f'<text x="{x - 6 if right else x + 6:.1f}" y="{y - 5:.1f}" font-size="11.5" fill="var(--ink)" '
                 f'text-anchor="{"end" if right else "start"}" '
                 f'style="paint-order:stroke;stroke:var(--bg);stroke-width:3px">{e(lab)}</text>')
    leg = "".join(f'<span style="color:{COL[k_]}">━ {t}</span> ' for k_, t in
                  (("dom", T("внутренний", "domestic", "Inland")), ("int", T("международный", "international", "international")),
                   ("long", T("дальний", "long-haul", "Langstrecke")))
                  if any(kind(r, india) == k_ for r in rows))
    if not fams:
        return (f'<figure class="fig"><svg viewBox="0 0 {w} {h:.0f}" width="100%" font-family="var(--sans)" '
                f'role="img" aria-label="{T("Карта пар", "Map of pairs", "Karte der Paare")}">{"".join(g).replace('<path class="ac"', '<path style="display:none"')}'
                f'</svg><figcaption class="leg">{leg}</figcaption></figure>')
    fl = fam_legend([k for k, *_ in FAM if k in fams])
    on = lambda m: ' class="on"' if m == mode else ""  # noqa: E731
    return (f'<figure class="fig rmap{" m-ac" if mode == "ac" else ""}"><div class="tg"><button{on("tk")} data-m="tk">'
            f'{T("По типу перевозок", "By traffic type", "Nach Verkehrsart")}</button><button{on("ac")} data-m="ac">'
            f'{T("По типу самолёта", "By aircraft type", "Nach Flugzeugtyp")}</button></div>'
            f'<svg viewBox="0 0 {w} {h:.0f}" width="100%" font-family="var(--sans)" '
            f'role="img" aria-label="{T("Карта пар", "Map of pairs", "Karte der Paare")}">{"".join(g)}</svg>'
            f'<figcaption class="leg"><span class="l-tk">{leg}</span>'
            f'<span class="l-ac">{fl}' + T("Цвет — тип, который выполняет больше всего рейсов на паре (наблюдения ADS-B, "
                                          "осень 2026); пунктир — наблюдений нет.",
                                          "Colour — the type that operates the most flights on the pair (ADS-B "
                                          "observations, autumn 2026); dashed — no observations.",
                                          "Farbe — der Typ mit den meisten Flügen auf dem Paar (ADS-B-Beobachtungen, "
                                          "Herbst 2026); gestrichelt — keine Beobachtungen.") + '</span></figcaption></figure>')


def ac_table(rows, india=False):
    head = (f"<tr><th class=r>#</th><th>{T('Пара', 'Pair', 'Paar')}</th><th>{T('Лучший тип', 'Best type', 'Bester Typ')}</th>"
            f"<th class=r>{T('Безубыточный тариф', 'Breakeven fare', 'Break-even-Tarif')}</th>"
            f"<th class=r>A320neo</th><th class=r>737 MAX 8</th>"
            f"<th class=r>{T('Рейсов в день нужно', 'Flights per day needed', 'Nötige Flüge pro Tag')}</th>"
            f"<th class=r>{T('Летают сейчас', 'Flown now', 'Heute geflogen')}</th></tr>")
    body = []
    for r in rows:
        a = AC.get(r["pair"])
        if not a:
            continue
        al = {x["type"]: x for x in a["all"]}
        b = a.get("best")
        f = lambda t: (money(al[t]["fare"], "EUR") if t in al and al[t]["ok"] and al[t].get("fare") else "—")  # noqa: E731
        if b:
            seats = (al[b["type"]].get("pax") or 0) / 0.8
            per_day = r["pax"] / 365 / 2 / (seats * 0.8) if seats else None
            best = f"<b>{tname(b['type'])}</b>"
            if a.get("russia") and "A21N" in al and al["A21N"]["ok"]:
                best += f' <span class=s>(A321neo — {money(al["A21N"]["fare"], "EUR")})</span>'
            fare = money(b["fare"], "EUR")
            pd = n(per_day, 1) if per_day else "—"
        else:
            best = (T("SJ-100 / МС-21 — калькулятор пока не считает", "SJ-100 / MC-21 — not yet computed by the calculator",
                      "SJ-100 / MC-21 — vom Rechner noch nicht berechnet") if a.get("russia")
                    else T("нет расчёта", "no calculation", "keine Berechnung"))
            fare, pd = "—", "—"
        c = comp(r)
        now = n(c["per_day"], 1) if c and c["carriers"] else "—"
        body.append(f"<tr><td class=r>{r['rank']}</td><td class=nm>{e(label(r))}</td><td>{best}</td>"
                    f"<td class=r>{fare}</td><td class=r>{f('A20N')}</td><td class=r>{f('B38M')}</td>"
                    f"<td class=r>{pd}</td><td class=r>{now}</td></tr>")
    return f'<div class="tw"><table class="txt">{head}{"".join(body)}</table></div>' 


def is_ru(r):
    return any(x[:1] == "U" and x[:2] not in ("UK",) for x in (r.get("a", ""), r.get("b", "")) if len(x) == 4)


def flags(r):
    f = []
    if r.get("slot3"):
        f.append(T("слоты: ", "slots: ", "Slots: ") + ", ".join(r["slot3"]))
    if is_ru(r):
        f.append(T("Россия: только перевозчики вне ЕС", "Russia: non-EU carriers only", "Russland: nur Nicht-EU-Airlines"))
    return "; ".join(f)


def pc(v):
    return "—" if v is None else f"{n(v * 100, 0, sign=True)} %"


def table(rows, india=False, start=0):
    g12 = T("Рост за 12 мес.", "Growth, 12 months", "Wachstum, 12 Monate")
    g23 = T("Рост 2024/23", "Growth 2024/23", "Wachstum 2024/23")
    g25 = T("Рост 2025/24", "Growth 2025/24", "Wachstum 2025/24")
    head = (f"<tr><th class=r>#</th><th>{T('Пара', 'Pair', 'Paar')}</th><th class=r>{T('км', 'km', 'km')}</th>"
            f"<th class=r>{T('Пассажиров', 'Passengers', 'Passagiere')}</th>"
            f"<th class=r>{g12 if india else g23}</th>"
            f"<th class=r>{g25 if india else T('Загрузка', 'Load factor', 'Auslastung')}</th>"
            f"<th class=r>{T('Индекс', 'Index', 'Index')}</th><th>{T('Ограничения', 'Constraints', 'Einschränkungen')}</th></tr>")
    body = "".join(
        f"<tr><td class=r>{r['rank']}</td><td class=nm><b>{e(label(r))}</b></td>"
        f"<td class=r>{n(r['km']) if r.get('km') else '—'}</td><td class=r>{n(r['pax'])}</td>"
        f"<td class=r>{pc(r.get('growth'))}</td>"
        f"<td class=r>{pc(r.get('growth25')) if india else ('—' if r.get('lf') is None else n(r['lf'] * 100, 0) + ' %')}</td>"
        f"<td class=r><b>{n(r['index'])}</b></td><td class=s>{e(flags(r))}</td></tr>" for r in rows[start:])
    return f'<div class="tw"><table class="txt">{head}{body}</table></div>'


def build() -> str:
    e1, i1 = EU[0], IN[0]
    tr_ru = [r for r in EU[:30] if is_ru(r)]

    hook = f"""<h1>{T("Какие маршруты привлекательны для авиакомпании: Европа и Индия",
                  "Which routes are attractive for an airline: Europe and India",
                  "Welche Strecken für eine Airline attraktiv sind: Europa und Indien")}</h1>
<p class="meta">{T(f"Исследование FlightCostApp, ноябрь 2026 · как авиакомпании и аэропорты оценивают маршрут, какие данные "
                   f"для этого открыты, и наш рейтинг {n(len(EU))} пар Европы и {n(len(IN))} пар Индии (будет обновляться)",
                   f"FlightCostApp research, November 2026 · how airlines and airports evaluate a route, which data are "
                   f"openly available, and our rating of {n(len(EU))} European and {n(len(IN))} Indian pairs (to be updated)",
                   f"FlightCostApp-Studie, November 2026 · wie Airlines und Flughäfen eine Strecke bewerten, welche Daten "
                   f"dafür offen sind, und unser Rating von {n(len(EU))} Paaren in Europa und {n(len(IN))} in Indien "
                   f"(wird aktualisiert)")}</p>
{calc_badge("routes-2026-11")}
<div class="verdict">
<div><b>{T("Рынок — это пара городов", "The market is a city pair", "Der Markt ist ein Städtepaar")}</b><span>{T(
    "сколько людей хотят попасть из одного города в другой, включая тех, кто сейчас летит со стыковкой или едет в "
    "соседний аэропорт",
    "how many people want to get from one city to another, including those who now fly via a connection or drive "
    "to a neighbouring airport",
    "wie viele Menschen von einer Stadt in die andere wollen, auch jene, die heute mit Umstieg fliegen oder zu einem "
    "Nachbarflughafen fahren")}{cite('r1-215', 'r1-145')}</span></div>
<div><b>{T("Лоукостер: рынок +10…44 %, тариф −11…21 %", "Low-cost entry: market +10…44 %, fare −11…21 %",
           "Billigflieger: Markt +10…44 %, Tarif −11…21 %")}</b><span>{T(
    "вход дешёвого перевозчика растит пару, но сбивает доходность всем",
    "a low-cost entrant grows the pair but pushes down yield for everyone",
    "der Eintritt eines Billigfliegers lässt das Paar wachsen, drückt aber den Ertrag aller")}{cite('r1-034', 'r1-038', 'r1-009', 'r1-010')}</span></div>
<div><b>{T("Тарифов по паре в открытом доступе нет", "No open fares by pair", "Keine offenen Tarife je Paar")}</b><span>{T(
    "ни в Европе, ни в Индии — поэтому рейтинг стоит на размере рынка, росте и загрузке",
    "neither in Europe nor in India — so the rating rests on market size, growth and load factor",
    "weder in Europa noch in Indien — das Rating beruht daher auf Marktgröße, Wachstum und Auslastung")}{cite('r1-175', 'r2-001')}</span></div>
<div><b>{T("7–8 % маршрутов закрывается за год", "7–8 % of routes close each year",
           "7–8 % der Strecken werden jährlich eingestellt")}</b><span>{T(
    f"в ЕС в 2025 году закрыли {n(1127)} маршрутов из примерно {n(14.8, 1)} тыс.; из маршрутов UDAN после субсидии "
    f"выжили 7 %",
    f"in the EU in 2025, {n(1127)} routes out of about {n(14800)} were closed; of the UDAN routes, 7 % survived the end "
    f"of the subsidy",
    f"in der EU wurden 2025 {n(1127)} von rund {n(14800)} Strecken eingestellt; von den UDAN-Strecken überlebten 7 % das "
    f"Ende der Subvention")}{cite('r1-107', 'r1-073')}</span></div></div>
<p class="lede">{T(
    "Какой маршрут открыть — главный вопрос планирования сети. Его решают не по самолёту, а по рынку: сколько людей "
    "хотят летать между двумя городами, растёт ли спрос, сколько мест на паре уже предложено и кем, пустят ли аэропорты "
    "и сколько это стоит. Ниже — как это оценивают авиакомпании и аэропорты, что из этого можно измерить по открытым "
    "данным, и наш рейтинг пар городов для Европы и Индии. Он не говорит «летите сюда»: он показывает, где рынок "
    "большой, растёт и где кресел уже не хватает, — с чего стоит начать собственный расчёт.",
    "Which route to open is the central question of network planning. It is decided not by the aircraft but by the "
    "market: how many people want to fly between two cities, whether demand is growing, how many seats are already "
    "offered on the pair and by whom, whether the airports will let you in and what it costs. Below: how airlines and "
    "airports assess this, what of it can be measured from open data, and our rating of city pairs for Europe and "
    "India. It does not say 'fly here': it shows where the market is large, growing and already short of seats — "
    "where your own calculation should start.",
    "Welche Strecke man eröffnet, ist die Kernfrage der Netzplanung. Entschieden wird sie nicht über das Flugzeug, "
    "sondern über den Markt: wie viele Menschen zwischen zwei Städten fliegen wollen, ob die Nachfrage wächst, wie "
    "viele Sitze auf dem Paar schon angeboten werden und von wem, ob die Flughäfen einen hineinlassen und was das "
    "kostet. Im Folgenden: wie Airlines und Flughäfen das bewerten, was davon sich mit offenen Daten messen lässt, und "
    "unser Rating der Städtepaare für Europa und Indien. Es sagt nicht „fliegt hierhin“: Es zeigt, wo der Markt groß "
    "ist, wächst und wo Sitze schon knapp sind — womit die eigene Rechnung beginnen sollte.")}</p>"""

    nar = R1["narrative"]

    def para(i, fix=None):
        t = nar[i]
        if fix:
            for a, b in fix:
                t = t.replace(a, b)
        ids = re.findall(r"\[(r\d-\d{3})\]", t)
        t = re.sub(r"\s*\[(r\d-\d{3})\]", "", t)
        return f"<p>{e(TR(t))}{cite(*ids)}</p>"

    theory = f"""<section><h2>{T("Как авиакомпании оценивают маршрут", "How airlines evaluate a route",
                                 "Wie Airlines eine Strecke bewerten")}</h2>
{para(0)}{para(2, [("около трёх четвертей разброса", "от 70 до 76 % разброса")])}
<h3>{T("Стимуляция спроса и падение доходности", "Demand stimulation and falling yield",
       "Nachfragestimulierung und sinkender Ertrag")}</h3>
{para(3)}{para(4)}
<h3>{T("Частота и конкуренция", "Frequency and competition", "Frequenz und Wettbewerb")}</h3>
{para(5)}{para(6)}
<h3>{T("Инфраструктура, стимулы и субсидии", "Infrastructure, incentives and subsidies",
       "Infrastruktur, Anreize und Subventionen")}</h3>
{para(7)}{para(9)}{para(10)}
<h3>{T("Метрики, которые публикуют", "Published metrics", "Veröffentlichte Kennzahlen")}</h3>
{para(8)}{para(11)}</section>"""

    def acc(x):
        # Пометки рабочей сессии исследователя («в этой сессии закрыт прокси») к читателю не относятся.
        return re.sub(r"\s*\((в этой сессии|в сессии)[^)]*\)", "", x or "")

    srcs = "".join(f"<tr><td class=nm><b>{e(TR(s['name']))}</b></td><td>{e(TR(s.get('what') or ''))}</td>"
                   f"<td>{e(TR(s.get('granularity') or ''))}</td><td>{e(TR(acc(s.get('access'))))}{cite(*s.get('ids', [])[:4])}</td></tr>"
                   for s in R2["sources"][:10])
    lm = RT['india']['last_month']
    data = f"""<section><h2>{T("Что можно измерить по открытым данным", "What can be measured from open data",
                               "Was sich mit offenen Daten messen lässt")}</h2>
{para(1)}
<p>{T("В Индии картина похожая. Регулятор DGCA ежемесячно публикует доли авиакомпаний и пассажиров по парам городов — "
      "внутренние помесячно, международные поквартально, — но без перевозчика на паре и без тарифов: за ценами на части "
      "маршрутов DGCA следит, но ряд не публикует",
      "The picture in India is similar. The regulator DGCA publishes airline shares and passengers by city pair — "
      "domestic monthly, international quarterly — but without the carrier on a pair and without fares: DGCA monitors "
      "prices on some routes but does not publish the series",
      "In Indien ist das Bild ähnlich. Die Behörde DGCA veröffentlicht Airline-Anteile und Passagiere je Städtepaar — "
      "Inland monatlich, international quartalsweise —, aber ohne Airline je Paar und ohne Tarife: Preise auf einem Teil "
      "der Strecken beobachtet DGCA, die Reihe veröffentlicht sie nicht")}{cite('r2-150', 'r2-001')}. {T(
      "Рынок почти дуополия: IndiGo перевёз в 2025 году около 64 % внутренних пассажиров",
      "The market is almost a duopoly: in 2025 IndiGo carried about 64 % of domestic passengers",
      "Der Markt ist fast ein Duopol: IndiGo beförderte 2025 rund 64 % der Inlandspassagiere")}{cite('r1-064')}.</p>
<details><summary>{T("Открытые источники данных о маршрутах — таблица", "Open data sources on routes — table", "Offene Datenquellen zu Strecken — Tabelle")}</summary>
<div class="tw"><table class="txt"><tr><th>{T("Источник", "Source", "Quelle")}</th><th>{T("Что даёт", "What it provides", "Was sie liefert")}</th>
<th>{T("Детализация", "Granularity", "Detailgrad")}</th><th>{T("Доступ", "Access", "Zugang")}</th></tr>
{srcs}</table></div></details>
<p>{T("Итог для рейтинга: размер рынка и рост открыты в обоих регионах, загрузка кресел на паре — только в Европе "
      "(Eurostat публикует кресла), конкуренция на паре и тарифы — нет. Координируемые аэропорты известны частично: "
      "Испания, Великобритания, Дублин, Варшава, часть Франции, четыре аэропорта Индии; Германия не делит свои 17 "
      "аэропортов на уровни",
      "Bottom line for the rating: market size and growth are open in both regions, the seat load factor on a pair only "
      "in Europe (Eurostat publishes seats), competition on a pair and fares are not. Slot-coordinated airports are "
      "known only in part: Spain, the UK, Dublin, Warsaw, part of France, four airports in India; Germany does not split "
      "its 17 airports by level",
      "Fazit für das Rating: Marktgröße und Wachstum sind in beiden Regionen offen, die Sitzauslastung je Paar nur in "
      "Europa (Eurostat veröffentlicht Sitze), Wettbewerb je Paar und Tarife nicht. Koordinierte Flughäfen sind nur "
      "teilweise bekannt: Spanien, Großbritannien, Dublin, Warschau, ein Teil Frankreichs, vier Flughäfen in Indien; "
      "Deutschland teilt seine 17 Flughäfen nicht nach Stufen")}
{cite('r2-100', 'r2-137', 'r2-157', 'r2-109')}. {T("Поэтому слоты в рейтинге — флажок, а не штраф.",
                                                   "So slots are a flag in the rating, not a penalty.",
                                                   "Slots sind im Rating daher ein Hinweis, keine Strafe.")}</p>
<p>{T(f"Ещё одна оговорка: в открытой статистике Европы последний полный год — 2024-й. Мы скачали таблицы Eurostat в "
      f"конце октября 2026 года, и у всех 32 стран ряды кончаются декабрём 2024-го; для Индии данные есть по {lm}.",
      f"One more caveat: the latest full year in Europe's open statistics is 2024. We downloaded the Eurostat tables at "
      f"the end of October 2026, and for all 32 countries the series end in December 2024; for India, data run to {lm}.",
      f"Noch ein Vorbehalt: Das letzte vollständige Jahr in Europas offener Statistik ist 2024. Wir haben die "
      f"Eurostat-Tabellen Ende Oktober 2026 geladen, und für alle 32 Länder enden die Reihen im Dezember 2024; für "
      f"Indien reichen die Daten bis {lm}.")}</p></section>"""

    method = f"""<section><h2>{T("Как мы считаем рейтинг", "How we calculate the rating", "Wie wir das Rating berechnen")}</h2>
<p>{T("Рейтинг отвечает на один вопрос: где рынок уже большой, растёт и где кресел на нём не хватает. По каждой паре "
      "считаются три опоры, каждая — процентиль внутри своего рынка (100 — лучший), индекс — их среднее.",
      "The rating answers one question: where is the market already large, growing and short of seats. For each pair "
      "three pillars are calculated, each a percentile within its own market (100 is best); the index is their average.",
      "Das Rating beantwortet eine Frage: Wo ist der Markt schon groß, wächst und hat zu wenige Sitze? Für jedes Paar "
      "werden drei Säulen berechnet, jede als Perzentil innerhalb des eigenen Marktes (100 ist am besten); der Index ist "
      "ihr Mittelwert.")}</p>
<ul><li>{T("<b>Размер рынка</b> — пассажиры за год в обе стороны (логарифм: разница между 200 тысячами и миллионом "
           "важнее, чем между пятью и шестью миллионами).",
           "<b>Market size</b> — passengers per year in both directions (logarithm: the difference between 200,000 and "
           "a million matters more than between five and six million).",
           "<b>Marktgröße</b> — Passagiere pro Jahr in beide Richtungen (Logarithmus: Der Unterschied zwischen 200.000 "
           "und einer Million zählt mehr als zwischen fünf und sechs Millionen).")}</li>
<li>{T("<b>Рост</b> — в Европе 2024 год к 2023-му; в Индии последние 12 месяцев к предыдущим 12 и 2025 год к 2024-му.",
       "<b>Growth</b> — in Europe 2024 over 2023; in India the last 12 months over the previous 12, and 2025 over 2024.",
       "<b>Wachstum</b> — in Europa 2024 ggü. 2023; in Indien die letzten 12 Monate ggü. den 12 davor sowie 2025 ggü. "
       "2024.")}</li>
<li>{T("<b>Недопредложение</b> — только в Европе: загрузка кресел на паре за год, пассажиры ÷ кресла. Высокая загрузка "
       "значит, что существующие перевозчики не успевают за спросом.",
       "<b>Undersupply</b> — Europe only: the seat load factor on the pair over the year, passengers ÷ seats. A high load "
       "factor means the existing carriers are not keeping up with demand.",
       "<b>Unterangebot</b> — nur Europa: Sitzauslastung auf dem Paar über das Jahr, Passagiere ÷ Sitze. Hohe Auslastung "
       "heißt, dass die bestehenden Airlines mit der Nachfrage nicht Schritt halten.")}</li></ul>
<p class="formula">{T(
    "Индекс<sub>Европа</sub> = ⅓ · ( P[ln пассажиров] + P[рост 2024/23] + P[пассажиры ÷ кресла] )<br>"
    "Индекс<sub>Индия</sub> = ⅓ · ( P[ln пассажиров] + P[рост за 12 мес.] + P[рост 2025/24] )<br>"
    "P[x] = доля пар своего рынка с худшим значением x, 0–100",
    "Index<sub>Europe</sub> = ⅓ · ( P[ln passengers] + P[growth 2024/23] + P[passengers ÷ seats] )<br>"
    "Index<sub>India</sub> = ⅓ · ( P[ln passengers] + P[growth, 12 months] + P[growth 2025/24] )<br>"
    "P[x] = share of pairs in the same market with a worse value of x, 0–100",
    "Index<sub>Europa</sub> = ⅓ · ( P[ln Passagiere] + P[Wachstum 2024/23] + P[Passagiere ÷ Sitze] )<br>"
    "Index<sub>Indien</sub> = ⅓ · ( P[ln Passagiere] + P[Wachstum 12 Monate] + P[Wachstum 2025/24] )<br>"
    "P[x] = Anteil der Paare desselben Marktes mit schlechterem Wert von x, 0–100")}</p>
<div class="tw"><table class="txt"><tr><th>{T("Слагаемое", "Term", "Term")}</th><th>{T("Что это", "What it is", "Was es ist")}</th>
<th>{T("Источник", "Source", "Quelle")}</th></tr>
<tr><td>{T("ln пассажиров", "ln passengers", "ln Passagiere")}</td><td>{T(
    "пассажиров за год в обе стороны; логарифм — чтобы миллионные пары не затмили остальные",
    "passengers per year in both directions; the logarithm keeps million-passenger pairs from eclipsing the rest",
    "Passagiere pro Jahr in beide Richtungen; der Logarithmus verhindert, dass Millionenpaare die übrigen verdrängen")}</td>
<td>{T("Eurostat PAS_CRD (2024), DGCA (12 мес.)", "Eurostat PAS_CRD (2024), DGCA (12 months)",
      "Eurostat PAS_CRD (2024), DGCA (12 Monate)")}</td></tr>
<tr><td>{T("рост", "growth", "Wachstum")}</td><td>{T(
    "пассажиры к прошлому году; в Индии 2025/24 — по месяцам, которые есть в обоих годах (в ряду DGCA нет мая 2024)",
    "passengers versus the previous year; in India 2025/24 uses the months present in both years (the DGCA series has "
    "no May 2024)",
    "Passagiere ggü. Vorjahr; in Indien 2025/24 nur über Monate, die in beiden Jahren vorliegen (in der DGCA-Reihe "
    "fehlt Mai 2024)")}</td><td>{T("те же ряды", "same series", "dieselben Reihen")}</td></tr>
<tr><td>{T("пассажиры ÷ кресла", "passengers ÷ seats", "Passagiere ÷ Sitze")}</td><td>{T(
    "загрузка кресел на паре за год — мера недопредложения",
    "seat load factor on the pair over the year — a measure of undersupply",
    "Sitzauslastung auf dem Paar über das Jahr — Maß für Unterangebot")}</td><td>Eurostat ST_PAS</td></tr>
</table></div>
<p>{T(f"В рейтинг попадают пары от {n(200000)} пассажиров в год в Европе и от {n(150000)} в Индии — меньше этого рынок "
      f"не заполнит ежедневный рейс узкофюзеляжного самолёта. Европейские пары дальше {n(4500)} км — отдельной таблицей: "
      f"это уже не A320 и не 737. Пара в Европе — пара аэропортов (так публикует Eurostat; лондонские аэропорты не "
      f"объединены), в Индии — пара городов (у Мумбаи и Гоа по два аэропорта, они сложены).",
      f"The rating includes pairs with at least {n(200000)} passengers a year in Europe and {n(150000)} in India — "
      f"below that a market will not fill a daily narrowbody flight. European pairs beyond {n(4500)} km are in a separate "
      f"table: that is no longer A320 or 737 territory. A pair in Europe is an airport pair (that is how Eurostat "
      f"publishes; London airports are not merged), in India a city pair (Mumbai and Goa have two airports each, "
      f"which are added together).",
      f"In das Rating kommen Paare ab {n(200000)} Passagieren pro Jahr in Europa und ab {n(150000)} in Indien — "
      f"darunter füllt der Markt keinen täglichen Schmalrumpfflug. Europäische Paare über {n(4500)} km stehen in einer "
      f"eigenen Tabelle: Das ist kein A320- oder 737-Terrain mehr. Ein Paar ist in Europa ein Flughafenpaar (so "
      f"veröffentlicht Eurostat; Londoner Flughäfen sind nicht zusammengefasst), in Indien ein Städtepaar (Mumbai und "
      f"Goa haben je zwei Flughäfen, sie werden addiert).")}</p>
<p class="small">{T(
    "Чего рейтинг не учитывает: тарифы и доходность, транзит через хабы (Eurostat считает людей на борту), сезонность, "
    "права на полёты и санкции. Пары с российскими аэропортами — это рейсы турецких и других неевропейских "
    "перевозчиков; европейским они закрыты.",
    "What the rating does not account for: fares and yield, transfer traffic via hubs (Eurostat counts people on "
    "board), seasonality, traffic rights and sanctions. Pairs with Russian airports are flights by Turkish and other "
    "non-European carriers; they are closed to European carriers.",
    "Was das Rating nicht berücksichtigt: Tarife und Ertrag, Umsteigeverkehr über Drehkreuze (Eurostat zählt Menschen "
    "an Bord), Saisonalität, Verkehrsrechte und Sanktionen. Paare mit russischen Flughäfen sind Flüge türkischer und "
    "anderer nichteuropäischer Airlines; europäischen Airlines sind sie verschlossen.")}</p></section>"""

    eu = f"""<section><h2>{T("Европа: топ пар ближне- и среднемагистральных", "Europe: top short- and medium-haul pairs",
                             "Europa: Top-Paare auf Kurz- und Mittelstrecke")}</h2>
<p>{T(f"Сверху — пары, где одновременно большой рынок, рост и полные самолёты. {n(len(tr_ru))} из первых 30 — Турция и "
      f"Россия; без них верх занимают курортные и столичные пары Испании, Германии и Бенилюкса: {e(label(EU[3]))}, "
      f"{e(label(EU[4]))}, {e(label(EU[6]))}.",
      f"At the top are pairs that combine a large market, growth and full aircraft. {n(len(tr_ru))} of the first 30 "
      f"involve Turkey and Russia; without them the top is taken by leisure and capital-city pairs in Spain, Germany "
      f"and the Benelux: {e(label(EU[3]))}, {e(label(EU[4]))}, {e(label(EU[6]))}.",
      f"Oben stehen Paare, die großen Markt, Wachstum und volle Flugzeuge vereinen. {n(len(tr_ru))} der ersten 30 "
      f"betreffen die Türkei und Russland; ohne sie führen Ferien- und Hauptstadtpaare in Spanien, Deutschland und den "
      f"Benelux-Ländern: {e(label(EU[3]))}, {e(label(EU[4]))}, {e(label(EU[6]))}.")}</p>
{rmap("europe", EU[:5])}
{table(EU[:10])}
<details><summary>{T("Места 11–50", "Places 11–50", "Plätze 11–50")}</summary>{table(EU[:50], start=10)}</details>
<h3>{T(f"Дальние пары (больше {n(4500)} км)", f"Long-haul pairs (over {n(4500)} km)",
       f"Langstreckenpaare (über {n(4500)} km)")}</h3>
{rmap("world", EUL[:5])}
{table(EUL[:10])}
<p class="small">{T("Источник: Eurostat avia_par, 2024 год, пары с полным годом данных; загрузка — пассажиры ÷ кресла.",
                    "Source: Eurostat avia_par, 2024, pairs with a full year of data; load factor — passengers ÷ seats.",
                    "Quelle: Eurostat avia_par, 2024, Paare mit vollständigem Datenjahr; Auslastung — Passagiere ÷ "
                    "Sitze.")}</p></section>"""

    ind = f"""<section><h2>{T("Индия: топ пар", "India: top pairs", "Indien: Top-Paare")}</h2>
<p>{T(f"В Индии верх рейтинга — не Дели — Мумбаи (самая большая пара, но её рост умеренный и оба аэропорта упираются в "
      f"слоты), а пары, которые растут быстрее рынка: {e(label(IN[0]))}, {e(label(IN[5]))}, {e(label(IN[6]))}. Рост на "
      f"50–70 % за год на паре часто значит новые рейсы или новый аэропорт — его стоит проверять, а не принимать на веру.",
      f"In India the top of the rating is not Delhi — Mumbai (the largest pair, but its growth is moderate and both "
      f"airports are slot-constrained) but pairs growing faster than the market: {e(label(IN[0]))}, {e(label(IN[5]))}, "
      f"{e(label(IN[6]))}. Growth of 50–70 % a year on a pair often means new flights or a new airport — it should be "
      f"checked, not taken on trust.",
      f"In Indien steht oben nicht Delhi — Mumbai (das größte Paar, aber mit moderatem Wachstum, und beide Flughäfen "
      f"stoßen an Slotgrenzen), sondern Paare, die schneller wachsen als der Markt: {e(label(IN[0]))}, "
      f"{e(label(IN[5]))}, {e(label(IN[6]))}. Ein Wachstum von 50–70 % im Jahr auf einem Paar bedeutet oft neue Flüge "
      f"oder einen neuen Flughafen — das sollte man prüfen, nicht einfach übernehmen.")}</p>
{rmap("india", IN[:5], india=True)}
{table(IN[:10], india=True)}
<details><summary>{T("Места 11–50", "Places 11–50", "Plätze 11–50")}</summary>{table(IN[:50], india=True, start=10)}</details>
<p class="small">{T(f"Источник: DGCA, внутренние рейсы по парам городов, последние 12 месяцев по {lm}; сборка "
                    f"github.com/Vonter/india-aviation-traffic (ODbL).",
                    f"Source: DGCA, domestic flights by city pair, last 12 months to {lm}; compiled by "
                    f"github.com/Vonter/india-aviation-traffic (ODbL).",
                    f"Quelle: DGCA, Inlandsflüge nach Städtepaaren, letzte 12 Monate bis {lm}; Aufbereitung "
                    f"github.com/Vonter/india-aviation-traffic (ODbL).")}</p></section>"""

    gaps_ru = [x["best"]["fare"] / next(y["fare"] for y in x["all"] if y["type"] == "A21N") - 1
               for x in AC.values() if x.get("russia") and x.get("best")
               and any(y["type"] == "A21N" and y["ok"] for y in x["all"])]
    ru_gap = (f"{n(min(gaps_ru) * 100, 0)}–{n(max(gaps_ru) * 100, 0)} %" if gaps_ru else "—")
    cite_t214 = (' <a href="https://www.airlines-inform.ru/commercial-aircraft/tu-214.html">[airlines-inform]</a>; '
                 + T("компоновка", "layout", "Bestuhlung")
                 + ' — <a href="https://flyredwings.com/about/park/">Red Wings</a>')
    est = T("оценка", "estimate", "Schätzung")
    acs = f"""<section><h2>{T("Каким самолётом летать", "Which aircraft to fly", "Mit welchem Flugzeug fliegen")}</h2>
<p>{T("Для каждой пары топа калькулятор посчитал безубыточный тариф — сколько должен заплатить пассажир, чтобы рейс "
      "окупился при загрузке 80 %, — на типах, которые сегодня можно получить новыми: A320neo, A321neo, 737 MAX 8 и 9, "
      "A220-300, E195-E2, а для дальних пар — A350-900 и 787-9. На всех узкофюзеляжных парах дешевле всего на пассажира "
      "A321neo: на 4–5 % дешевле A320neo и на 5–6 % — 737 MAX 8. Разница скромнее, чем могла бы показаться: у A321neo "
      "больше кресел, но и рейс дороже — на нём больше топлива, сборы и аэронавигация считаются от массы. В базе A321neo — "
      "с максимальной массой 97 т и баками на 33 т, как у дальних A321LR/XLR, поэтому он «долетает» из Европы до Кюрасао "
      "и Сан-Паулу; обычный A321neo с массой 93,5 т туда без дополнительных баков не дойдёт. Но больший самолёт — это и "
      "меньше частот: столбец «рейсов в день» показывает, сколько рейсов A321neo в каждую сторону заполнит рынок пары при "
      "загрузке 80 %, а «летают сейчас» — сколько рейсов на паре выполняют все перевозчики вместе (по наблюдениям выше). "
      "Где выходит меньше двух, разумнее меньший тип с удобным расписанием — частота сама продаёт билеты (S-кривая выше).",
      "For each top pair the calculator computed the breakeven fare — how much a passenger must pay for the flight to "
      "break even at an 80 % load factor — on the types that can be obtained new today: A320neo, A321neo, 737 MAX 8 "
      "and 9, A220-300, E195-E2, and for long-haul pairs A350-900 and 787-9. On every narrowbody pair the A321neo is "
      "cheapest per passenger: 4–5 % cheaper than the A320neo and 5–6 % cheaper than the 737 MAX 8. The gap is smaller "
      "than it might seem: the A321neo has more seats, but the flight costs more too — it burns more fuel, and charges "
      "and air navigation fees are calculated from weight. In the database the A321neo has a 97 t maximum take-off "
      "weight and 33 t of tankage, like the long-range A321LR/XLR, which is why it 'reaches' Curaçao and São Paulo from "
      "Europe; a standard 93.5 t A321neo would not get there without extra tanks. But a bigger aircraft also means "
      "fewer frequencies: the 'flights per day needed' column shows how many A321neo flights in each direction the "
      "pair's market fills at an 80 % load factor, and 'flown now' how many flights all carriers together operate on "
      "the pair (from the observations above). Where it comes to fewer than two, a smaller type with a convenient "
      "schedule is the wiser choice — frequency sells tickets by itself (the S-curve above).",
      "Für jedes Top-Paar hat der Rechner den Break-even-Tarif ermittelt — wie viel ein Passagier zahlen muss, damit "
      "sich der Flug bei 80 % Auslastung trägt — für die heute neu erhältlichen Typen: A320neo, A321neo, 737 MAX 8 und "
      "9, A220-300, E195-E2, für Langstreckenpaare A350-900 und 787-9. Auf allen Schmalrumpfpaaren ist der A321neo je "
      "Passagier am günstigsten: 4–5 % günstiger als der A320neo und 5–6 % günstiger als die 737 MAX 8. Der Abstand ist "
      "kleiner, als man denken könnte: Der A321neo hat mehr Sitze, aber der Flug kostet auch mehr — mehr Treibstoff, und "
      "Entgelte und Flugsicherungsgebühren richten sich nach der Masse. In der Datenbank hat der A321neo 97 t "
      "Höchstabflugmasse und 33 t Tankinhalt wie die Langstreckenversionen A321LR/XLR, daher „erreicht“ er von Europa "
      "aus Curaçao und São Paulo; ein normaler A321neo mit 93,5 t käme ohne Zusatztanks nicht dorthin. Ein größeres "
      "Flugzeug heißt aber auch weniger Frequenzen: Die Spalte „Nötige Flüge pro Tag“ zeigt, wie viele A321neo-Flüge je "
      "Richtung der Markt des Paares bei 80 % Auslastung füllt, „Heute geflogen“, wie viele Flüge alle Airlines "
      "zusammen auf dem Paar durchführen (aus den Beobachtungen oben). Wo weniger als zwei herauskommen, ist ein "
      "kleinerer Typ mit bequemem Flugplan klüger — Frequenz verkauft Tickets von selbst (S-Kurve oben).")}</p>
<p>{T(f"Для пар с российскими аэропортами выбор другой. Западные типы российским перевозчикам недоступны, а из российских "
      f"в серии сейчас только Ту-214 — сертифицирован, четыре борта в 2026 году; SJ-100 ждёт сертификации к концу 2026 — "
      f"началу 2027 года, МС-21 — к концу 2027-го. Ту-214 калькулятор теперь считает. Производитель расход не публикует, "
      f"поэтому якорь — справочный часовой расход 3,7 т/ч (тот же справочник даёт 19 г на пассажиро-километр — при 210 "
      f"креслах и 850 км/ч это 3,4 т/ч{cite_t214}) через аналог 757-200 на планере Ту-214. Мы сверили его с непубличной "
      f"таблицей рейсового топлива по дальности, полученной от знакомых в отрасли: расчёт с этим якорем расходится с ней "
      f"на 1–2 % от 1 000 до 4 000 км. По расходу на рейс Ту-214 на 7–11 % прожорливее 757-200 — ровно разница "
      f"поколений двигателя ПС-90А и PW2000. Итог на парах Анталии: Ту-214 на 194 кресла (компоновка Red Wings) "
      f"выходит на {ru_gap} дороже на пассажира, чем A321neo, на котором туда же летают турецкие перевозчики, — топливо "
      f"на рейс дороже почти на треть, ТОиР по заготовке вдвое, а кресел меньше. МС-21 калькулятор пока не считает — "
      f"нет сертифицированной версии и опубликованного расхода; SJ-100 ниже — <span class=\"no\">{est}</span>: масса "
      f"пустого и расход версии с ПД-8 не опубликованы.",
      f"For pairs with Russian airports the choice is different. Western types are unavailable to Russian carriers, and "
      f"of the Russian ones only the Tu-214 is currently in series production — certified, four aircraft in 2026; the "
      f"SJ-100 awaits certification by late 2026 – early 2027, the MC-21 by the end of 2027. The calculator now computes "
      f"the Tu-214. The manufacturer does not publish fuel burn, so the anchor is a reference hourly burn of 3.7 t/h "
      f"(the same reference gives 19 g per passenger-kilometre — at 210 seats and 850 km/h that is 3.4 t/h{cite_t214}) "
      f"via the 757-200 as an analogue on the Tu-214 airframe. We checked it against a non-public table of trip fuel by "
      f"distance obtained from industry contacts: the calculation with this anchor differs from it by 1–2 % between "
      f"1,000 and 4,000 km. Per trip the Tu-214 burns 7–11 % more than the 757-200 — exactly the generation gap "
      f"between the PS-90A and PW2000 engines. The result on the Antalya pairs: a 194-seat Tu-214 (Red Wings layout) "
      f"comes out {ru_gap} more expensive per passenger than the A321neo, on which Turkish carriers fly the same "
      f"routes — trip fuel almost a third higher, maintenance by the default rate twice as high, and fewer seats. The "
      f"calculator does not yet compute the MC-21 — there is no certified version and no published burn; the SJ-100 "
      f"below is an <span class=\"no\">{est}</span>: the PD-8 version's empty weight and burn are unpublished.",
      f"Für Paare mit russischen Flughäfen sieht die Wahl anders aus. Westliche Typen sind russischen Airlines nicht "
      f"zugänglich, und von den russischen ist derzeit nur die Tu-214 in Serie — zugelassen, vier Flugzeuge 2026; die "
      f"SJ-100 wartet auf die Zulassung Ende 2026 – Anfang 2027, die MC-21 bis Ende 2027. Die Tu-214 berechnet der "
      f"Rechner jetzt. Der Hersteller veröffentlicht keinen Verbrauch, daher ist der Anker ein Referenz-Stundenverbrauch "
      f"von 3,7 t/h (dieselbe Quelle nennt 19 g je Passagierkilometer — bei 210 Sitzen und 850 km/h sind das 3,4 "
      f"t/h{cite_t214}) über die 757-200 als Analogon auf der Zelle der Tu-214. Wir haben ihn mit einer nicht "
      f"öffentlichen Tabelle des Streckentreibstoffs nach Entfernung aus Branchenkreisen abgeglichen: Die Rechnung mit "
      f"diesem Anker weicht zwischen 1.000 und 4.000 km um 1–2 % davon ab. Je Flug verbraucht die Tu-214 7–11 % mehr "
      f"als die 757-200 — genau der Generationsunterschied der Triebwerke PS-90A und PW2000. Ergebnis auf den "
      f"Antalya-Paaren: Eine Tu-214 mit 194 Sitzen (Bestuhlung Red Wings) ist je Passagier {ru_gap} teurer als der "
      f"A321neo, mit dem türkische Airlines dieselben Strecken fliegen — Treibstoff je Flug fast ein Drittel höher, "
      f"Wartung nach Standardsatz doppelt so hoch, und weniger Sitze. Die MC-21 berechnet der Rechner noch nicht — "
      f"es gibt keine zugelassene Version und keinen veröffentlichten Verbrauch; die SJ-100 unten ist eine "
      f"<span class=\"no\">{est}</span>: Leermasse und Verbrauch der PD-8-Version sind unveröffentlicht.")}</p>
<h3>{T("Европа", "Europe", "Europa")}</h3>{ac_table(EU[:20])}
<h3>{T("Дальние пары", "Long-haul pairs", "Langstreckenpaare")}</h3>{ac_table(EUL[:10])}
<h3>{T("Индия", "India", "Indien")}</h3>{ac_table(IN[:20], india=True)}
<h3>{T("Если мы не одни на паре: доля рынка решает тип", "If we are not alone on the pair: market share decides the type",
       "Wenn wir nicht allein auf dem Paar sind: Der Marktanteil entscheidet den Typ")}</h3>
<p>{T("«Дешевле всего на пассажира» молча предполагает, что мы возим всех пассажиров пары. Новичок на линии, где уже "
      "летают два-три перевозчика, возьмёт долю, и большой самолёт тогда либо летает полупустым, либо редко — раз в день "
      "или реже, а частота сама продаёт билеты. Правило ниже: из типов, которые при нашей доле дают не меньше двух рейсов "
      "в день в каждую сторону, берём самый дешёвый на пассажира; если ни один не дотягивает — самый дешёвый среди самых "
      "малых (в пределах 10 % по креслам), с пометкой. При всём рынке почти везде выходит A321neo; при четверти рынка — "
      "машины на 110–140 кресел на половине европейских пар и на большинстве индийских. Это и есть довод, почему новые "
      "маршруты раскатывают на таких самолётах, а большой ставят, когда линия набрала пассажиров: частота важнее 5–10 % "
      "лишней стоимости кресла.",
      "'Cheapest per passenger' silently assumes we carry all of the pair's passengers. A newcomer on a route where two "
      "or three carriers already fly will win a share, and a big aircraft then either flies half-empty or rarely — once "
      "a day or less — while frequency itself sells tickets. The rule below: of the types that, at our share, give at "
      "least two flights a day in each direction, we take the cheapest per passenger; if none reaches that, the cheapest "
      "among the smallest (within 10 % by seats), flagged. With the whole market the answer is almost always the "
      "A321neo; with a quarter of the market it is 110–140-seat aircraft on half the European pairs and most Indian ones. "
      "This is the argument for why new routes are built up on such aircraft and a big one is brought in once the route "
      "has gained passengers: frequency is worth more than 5–10 % extra cost per seat.",
      "„Am günstigsten je Passagier“ setzt stillschweigend voraus, dass wir alle Passagiere des Paares befördern. Ein "
      "Neuling auf einer Strecke, auf der schon zwei, drei Airlines fliegen, gewinnt einen Anteil, und ein großes "
      "Flugzeug fliegt dann halb leer oder selten — einmal am Tag oder seltener —, während die Frequenz selbst Tickets "
      "verkauft. Die Regel unten: Von den Typen, die bei unserem Anteil mindestens zwei Flüge pro Tag je Richtung "
      "ergeben, nehmen wir den je Passagier günstigsten; schafft das keiner, den günstigsten unter den kleinsten (innerhalb "
      "10 % nach Sitzen), markiert. Beim ganzen Markt ergibt sich fast überall der A321neo; bei einem Viertel des Marktes "
      "sind es Flugzeuge mit 110–140 Sitzen auf der Hälfte der europäischen und den meisten indischen Paaren. Das ist das "
      "Argument, warum neue Strecken mit solchen Flugzeugen aufgebaut werden und das große erst kommt, wenn die Strecke "
      "Passagiere gewonnen hat: Frequenz ist mehr wert als 5–10 % höhere Kosten je Sitz.")}</p>
<p>{T(f"Какая именно машина этого класса лучше, наш расчёт решает с оговоркой. E195-E2 выходит на 8–10 % дешевле A220-300 "
      f"на пассажира — у него легче планер и ниже расход, — но его расход <span class=\"no\">{est}</span>: Embraer рейсовое "
      f"топливо E195-E2 не публикует, и мы перенесли на него поправку, измеренную на E190-E2 с тем же двигателем и крылом "
      f"(Aircraft Commerce №142); сверка с заявленным Embraer снижением расхода на 25 % к E195-E1 сходится до 2 %. На "
      f"парах с Россией в этой роли SJ-100: на 6–8 % дороже Ту-214 на пассажира, но при малой доле рынка выигрывает "
      f"частотой; его расход — по РЛЭ SSJ100 с SaM146 (1,7 т/ч; с презентацией разработчика сходится до 4 %), масса "
      f"пустого — SSJ100 95LR: у версии с ПД-8 ни то, ни другое не опубликовано, так что для неё это "
      f"<span class=\"no\">нижняя граница</span>.",
      f"Which aircraft of this class is better our calculation decides with a caveat. The E195-E2 comes out 8–10 % "
      f"cheaper per passenger than the A220-300 — it has a lighter airframe and lower burn — but its burn is an "
      f"<span class=\"no\">{est}</span>: Embraer does not publish E195-E2 trip fuel, so we transferred to it the "
      f"correction measured on the E190-E2, which has the same engine and wing (Aircraft Commerce No. 142); a check "
      f"against Embraer's stated 25 % fuel reduction versus the E195-E1 agrees to within 2 %. On the pairs with Russia "
      f"this role is played by the SJ-100: 6–8 % dearer per passenger than the Tu-214, but it wins on frequency at a "
      f"small market share; its burn comes from the SSJ100 flight manual with SaM146 engines (1.7 t/h; agrees with the "
      f"developer's presentation to within 4 %), its empty weight from the SSJ100 95LR: neither is published for the "
      f"PD-8 version, so for it this is a <span class=\"no\">lower bound</span>.",
      f"Welches Flugzeug dieser Klasse besser ist, entscheidet unsere Rechnung mit Vorbehalt. Der E195-E2 ist je "
      f"Passagier 8–10 % günstiger als der A220-300 — leichtere Zelle, geringerer Verbrauch —, aber sein Verbrauch ist "
      f"eine <span class=\"no\">{est}</span>: Embraer veröffentlicht den Streckentreibstoff des E195-E2 nicht, also haben "
      f"wir die am E190-E2 mit gleichem Triebwerk und Flügel gemessene Korrektur übertragen (Aircraft Commerce Nr. 142); "
      f"der Abgleich mit Embraers angegebener Verbrauchssenkung von 25 % ggü. dem E195-E1 stimmt auf 2 %. Auf den Paaren "
      f"mit Russland übernimmt die SJ-100 diese Rolle: je Passagier 6–8 % teurer als die Tu-214, gewinnt aber bei "
      f"kleinem Marktanteil über die Frequenz; ihr Verbrauch stammt aus dem Flughandbuch der SSJ100 mit SaM146 (1,7 t/h; "
      f"stimmt auf 4 % mit der Präsentation des Entwicklers), die Leermasse von der SSJ100 95LR: Für die PD-8-Version ist "
      f"beides unveröffentlicht, für sie ist das also eine <span class=\"no\">Untergrenze</span>.")}</p>
<p class="formula">{T(
    "рейсов в день<sub>тип</sub> = пассажиров пары за год × доля ÷ 365 ÷ 2 ÷ (кресла<sub>тип</sub> × 0,8)<br>"
    "тип = argmin<sub>тип: рейсов ≥ N</sub> безубыточный тариф<sub>тип</sub>",
    "flights per day<sub>type</sub> = pair passengers per year × share ÷ 365 ÷ 2 ÷ (seats<sub>type</sub> × 0.8)<br>"
    "type = argmin<sub>type: flights ≥ N</sub> breakeven fare<sub>type</sub>",
    "Flüge pro Tag<sub>Typ</sub> = Passagiere des Paares pro Jahr × Anteil ÷ 365 ÷ 2 ÷ (Sitze<sub>Typ</sub> × 0,8)<br>"
    "Typ = argmin<sub>Typ: Flüge ≥ N</sub> Break-even-Tarif<sub>Typ</sub>")}</p>
{share_calc()}
<p class="small">{T(
    "Безубыточный тариф — расчёт калькулятора FlightCostApp для июля, загрузка 80 %, заготовки по умолчанию (лизинг, "
    "экипаж, ТОиР, сборы аэропортов, аэронавигация, топливо по региону). «—» — тип на паре невыполним по массе, "
    "дальности или полосе.",
    "Breakeven fare — FlightCostApp calculator for July, 80 % load factor, default inputs (lease, crew, maintenance, "
    "airport charges, air navigation, regional fuel). '—' — the type cannot operate the pair because of weight, range "
    "or runway.",
    "Break-even-Tarif — Rechnung des FlightCostApp-Rechners für Juli, 80 % Auslastung, Standardwerte (Leasing, Crew, "
    "Wartung, Flughafenentgelte, Flugsicherung, regionaler Treibstoff). „—“ — der Typ kann das Paar wegen Masse, "
    "Reichweite oder Piste nicht bedienen.")}</p></section>"""

    seen = [r for r in EU[:20] + EUL[:10] if comp(r) and comp(r)["carriers"]]
    dmax = max((comp(r)["days"] for r in seen), default=0)
    d_ayt = n(min((comp(r)["days"] for r in EU[:20] if comp(r) and "LTAI" in (r["a"], r["b"])), default=0))
    who = f"""<section><h2>{T("Кто уже летает на этих парах", "Who already flies these pairs",
                             "Wer diese Paare schon fliegt")}</h2>
<p>{T(f"Рейтинг смотрит на рынок, но не на соперников: Eurostat не публикует перевозчика на паре. Их видно по самим "
      f"самолётам. Каждый лайнер вещает своё положение по ADS-B, а сеть приёмников OpenSky собирает из этого рейсы с "
      f"аэропортом вылета и прилёта. Мы забирали вылеты и прилёты аэропортов топа — {n(dmax)} суток осенью 2026 года — и "
      f"сложили рейсы по парам и перевозчикам; позывной даёт перевозчика, реестр бортов — тип. Это уже не 2024 год из "
      f"Eurostat, а нынешнее расписание, причём осеннее: на курортных парах летом рейсов больше.",
      f"The rating looks at the market but not at rivals: Eurostat does not publish the carrier on a pair. They can be "
      f"seen from the aircraft themselves. Every airliner broadcasts its position via ADS-B, and the OpenSky receiver "
      f"network turns this into flights with departure and arrival airports. We collected departures and arrivals at "
      f"the top airports — {n(dmax)} days in autumn 2026 — and aggregated the flights by pair and carrier; the call sign "
      f"gives the carrier, the aircraft register the type. This is no longer Eurostat's 2024 but the current schedule — "
      f"an autumn one: leisure pairs have more flights in summer.",
      f"Das Rating betrachtet den Markt, nicht die Konkurrenten: Eurostat veröffentlicht die Airline je Paar nicht. Sie "
      f"sind an den Flugzeugen selbst zu erkennen. Jedes Verkehrsflugzeug sendet seine Position per ADS-B, und das "
      f"Empfängernetz OpenSky macht daraus Flüge mit Abflug- und Zielflughafen. Wir haben Abflüge und Ankünfte der "
      f"Top-Flughäfen erfasst — {n(dmax)} Tage im Herbst 2026 — und die Flüge nach Paar und Airline zusammengefasst; das "
      f"Rufzeichen liefert die Airline, das Luftfahrzeugregister den Typ. Das ist nicht mehr Eurostats 2024, sondern der "
      f"aktuelle Flugplan, und zwar ein herbstlicher: Auf Ferienpaaren gibt es im Sommer mehr Flüge.")}</p>
<p>{T("Картина знакомая по теории выше. На больших столичных парах делят рынок два-три перевозчика: Мадрид — Париж "
      "поровну у Iberia и Air France, Барселона — Орли на две трети у Vueling. Пары между вторыми городами — почти чисто "
      "лоукостерские: Берлин — Рим держат Ryanair и easyJet, Барселона — Будапешт — Wizz Air и Ryanair, Бергамо — "
      "Бухарест — Ryanair и Wizz Air; именно туда новый лоукостер заходит дороже всего, а сетевой перевозчик — дешевле. "
      "Парк на этих парах ещё старый: из рейсов с известным типом только около 18 % выполнены самолётами нового "
      "поколения (A320neo, A321neo, 737 MAX, A220), A321neo — около 2 %; то есть преимущество в расходе, которое "
      "калькулятор даёт A321neo, у соперников на паре пока есть не у всех.",
      "The picture is familiar from the theory above. On large capital-city pairs two or three carriers share the "
      "market: Madrid — Paris is split evenly between Iberia and Air France, Barcelona — Orly is two-thirds Vueling. "
      "Pairs between secondary cities are almost purely low-cost: Berlin — Rome is held by Ryanair and easyJet, "
      "Barcelona — Budapest by Wizz Air and Ryanair, Bergamo — Bucharest by Ryanair and Wizz Air; that is exactly where "
      "a new low-cost carrier finds entry most expensive and a network carrier cheapest. The fleet on these pairs is "
      "still old: of flights with a known type only about 18 % are operated by new-generation aircraft (A320neo, "
      "A321neo, 737 MAX, A220), the A321neo about 2 %; so the fuel advantage the calculator gives the A321neo is not yet "
      "shared by every rival on the pair.",
      "Das Bild kennt man aus der Theorie oben. Auf großen Hauptstadtpaaren teilen sich zwei, drei Airlines den Markt: "
      "Madrid — Paris je zur Hälfte Iberia und Air France, Barcelona — Orly zu zwei Dritteln Vueling. Paare zwischen "
      "Sekundärstädten sind fast reine Billigflieger-Märkte: Berlin — Rom halten Ryanair und easyJet, Barcelona — "
      "Budapest Wizz Air und Ryanair, Bergamo — Bukarest Ryanair und Wizz Air; genau dort ist der Eintritt für einen "
      "neuen Billigflieger am teuersten und für eine Netzwerkairline am günstigsten. Die Flotte auf diesen Paaren ist "
      "noch alt: Von den Flügen mit bekanntem Typ werden nur rund 18 % mit Flugzeugen der neuen Generation (A320neo, "
      "A321neo, 737 MAX, A220) geflogen, mit dem A321neo rund 2 %; den Verbrauchsvorteil, den der Rechner dem A321neo "
      "gibt, haben also noch nicht alle Konkurrenten auf dem Paar.")}</p>
<h3>{T("Какими самолётами летают", "Which aircraft fly them", "Mit welchen Flugzeugen geflogen wird")}</h3>
{fleet_chart(EU[:20])}
<p>{T("На средних парах Европы картина одна: A320 и 737-800 прошлого поколения, а neo и MAX — вкраплениями, заметнее "
      "всего у лоукостеров (Wizz Air на Барселона — Будапешт летает на A321neo). На дальних парах парк новее: 787 и A350 "
      "соседствуют с A330 и 777-300ER прошлого поколения (кроме A330-900 у TAP).",
      "On Europe's medium-haul pairs the picture is the same everywhere: previous-generation A320s and 737-800s, with "
      "neo and MAX only scattered, most visibly at low-cost carriers (Wizz Air flies Barcelona — Budapest with the "
      "A321neo). On long-haul pairs the fleet is newer: 787s and A350s sit alongside previous-generation A330s and "
      "777-300ERs (except TAP's A330-900).",
      "Auf Europas Mittelstreckenpaaren ist das Bild überall gleich: A320 und 737-800 der Vorgängergeneration, neo und "
      "MAX nur vereinzelt, am sichtbarsten bei Billigfliegern (Wizz Air fliegt Barcelona — Budapest mit dem A321neo). "
      "Auf Langstreckenpaaren ist die Flotte neuer: 787 und A350 neben A330 und 777-300ER der Vorgängergeneration "
      "(außer dem A330-900 von TAP).")}</p>
{fleet_chart(EUL[:10])}
<details><summary>{T("Перевозчики по парам — таблица", "Carriers by pair — table", "Airlines je Paar — Tabelle")}</summary>
{comp_table(EU[:20])}
<h3>{T("Дальние пары", "Long-haul pairs", "Langstreckenpaare")}</h3>
{comp_table(EUL[:10])}</details>
<p class="small">{T(f"Источник: OpenSky Network, рейсы по аэропортам (ADS-B); свёртка <code>bin/observed_export.py</code> и "
                    f"<code>bin/competitors.py</code>. Рейсов в день — в одну сторону, среднее за сутки наблюдения. "
                    f"Отсечены деловая авиация, грузовые перевозчики и перевозчики с одним-двумя рейсами за период (чаще "
                    f"всего это ошибка оценки аэропорта: борт пролетел рядом, а не сел). Дальние рейсы — нижняя граница: "
                    f"над океаном приёмников нет, и аэропорт назначения определяется не всегда (поэтому, например, на "
                    f"Амстердам — Кюрасао рейсов не видно вовсе, хотя KLM туда летает). Пары Анталии — {d_ayt} суток; "
                    f"внутренние пары Турции и пары с российскими аэропортами, кроме Шереметьева, по данным OpenSky не "
                    f"видны — приёмников там мало. Индию мы ещё не забирали; данные появятся при следующем обновлении.",
                    f"Source: OpenSky Network, flights by airport (ADS-B); aggregated with <code>bin/observed_export.py</code> "
                    f"and <code>bin/competitors.py</code>. Flights per day — one direction, average per observed day. "
                    f"Excluded: business aviation, cargo carriers and carriers with one or two flights in the period (most "
                    f"often an airport estimation error: the aircraft passed nearby rather than landed). Long-haul flights "
                    f"are a lower bound: there are no receivers over the ocean, and the destination airport is not always "
                    f"determined (which is why, for example, no flights at all are seen on Amsterdam — Curaçao, although "
                    f"KLM flies there). Antalya pairs — {d_ayt} days; domestic Turkish pairs and pairs with Russian "
                    f"airports other than Sheremetyevo are not visible in OpenSky data — there are few receivers. We have "
                    f"not yet collected India; the data will come with the next update.",
                    f"Quelle: OpenSky Network, Flüge nach Flughafen (ADS-B); aggregiert mit "
                    f"<code>bin/observed_export.py</code> und <code>bin/competitors.py</code>. Flüge pro Tag — je "
                    f"Richtung, Mittel je Beobachtungstag. Ausgenommen: Geschäftsluftfahrt, Frachtairlines und Airlines "
                    f"mit ein, zwei Flügen im Zeitraum (meist ein Fehler bei der Flughafenschätzung: Das Flugzeug flog "
                    f"vorbei, statt zu landen). Langstreckenflüge sind eine Untergrenze: Über dem Ozean gibt es keine "
                    f"Empfänger, und der Zielflughafen wird nicht immer erkannt (daher sind etwa auf Amsterdam — Curaçao "
                    f"gar keine Flüge zu sehen, obwohl KLM dorthin fliegt). Antalya-Paare — {d_ayt} Tage; türkische "
                    f"Inlandspaare und Paare mit russischen Flughäfen außer Scheremetjewo sind in den OpenSky-Daten nicht "
                    f"sichtbar — dort gibt es wenige Empfänger. Indien haben wir noch nicht erfasst; die Daten kommen mit "
                    f"dem nächsten Update.")} {credits()}</p></section>"""

    concl = f"""<section><h2>{T("Что меняем в калькуляторе", "What we change in the calculator",
                               "Was wir am Rechner ändern")}</h2>
<ol><li>{mark('on_input')}{T(
    "<b>Выбирая пару, смотрите на рынок, а не только на себестоимость</b>: размер, рост и загрузку на паре — в рейтинге "
    "выше; поток по паре калькулятор уже показывает.",
    "<b>When choosing a pair, look at the market, not only at cost</b>: size, growth and load factor on the pair are in "
    "the rating above; the calculator already shows the traffic on a pair.",
    "<b>Bei der Wahl eines Paares auf den Markt schauen, nicht nur auf die Kosten</b>: Größe, Wachstum und Auslastung "
    "stehen im Rating oben; das Aufkommen eines Paares zeigt der Rechner bereits.")}</li>
<li>{mark('in_calc')}{T(
    "<b>Рейтинг пар — в режиме «Сеть»</b>: возле выбранных аэропортов видны рынок, период, место, поток, загрузка при наличии и отметки уровня 3.",
    "<b>Pair ratings in Network mode</b>: selected airports show the market, period, rank, traffic, load factor when available, and Level 3 flags.",
    "<b>Paar-Ratings im Netzmodus</b>: bei den gewählten Flughäfen erscheinen Markt, Zeitraum, Rang, Verkehrsaufkommen, Auslastung falls verfügbar und Level-3-Hinweise.")}</li>
<li>{mark('planned')}{T(
    "<b>Безубыточный тариф против рыночного</b> — как только появятся тарифы по паре (цены агрегатора уже есть для части "
    "рынков), четвёртая опора «запас по цене».",
    "<b>Breakeven fare versus market fare</b> — as soon as fares by pair become available (aggregator prices already "
    "exist for some markets), a fourth pillar, 'price headroom'.",
    "<b>Break-even-Tarif gegen Markttarif</b> — sobald Tarife je Paar vorliegen (Aggregatorpreise gibt es für einen Teil "
    "der Märkte schon), eine vierte Säule „Preisspielraum“.")}</li>
<li>{mark('planned')}{T(
    "<b>Рейтинг обновляется</b> — Индия каждый квартал, Европа — когда Eurostat опубликует 2025 год.",
    "<b>The rating is updated</b> — India every quarter, Europe when Eurostat publishes 2025.",
    "<b>Das Rating wird aktualisiert</b> — Indien jedes Quartal, Europa, sobald Eurostat 2025 veröffentlicht.")}</li></ol>
</section>"""

    cnt = {f: Counter(x.get("status") for k, x in v.items() if not k.startswith("_")) for f, v in VER.items()}
    steps = sum(1 for f in (HERE / "trace").glob("r*.jsonl") for _ in f.open(encoding="utf-8"))

    def gtext(g):
        return g if isinstance(g, str) else (g.get("gap") or g.get("what") or g.get("claim") or "")

    # «Значения Eurostat … не сняты» — пробел снят: ряды пар собраны (bin/eurostat_pairs.py).
    gl = [gtext(g) for g in (R1.get("gaps") or [])[:5] + (R2.get("gaps") or [])[:5]]
    gaps = "".join(f"<li>{e(TR(g))}</li>" for g in gl if g and "не сняты" not in g)
    c1, c2 = cnt.get('r1', {}), cnt.get('r2', {})
    report = f"""<section><h2>{T("Как проверялось", "How it was checked", "Wie geprüft wurde")}</h2>
<p>{T(f"Два исследователя вели журналы — {n(steps)} шагов (<code>trace/r1–r2</code>): как оценивают маршрут и какие "
      f"данные открыты. Отдельные агенты открыли каждый источник и сверили цитаты (<code>verify/</code>): r1 — найдено "
      f"дословно {n(c1.get('found', 0))}, частично {n(c1.get('partial', 0))}; r2 — найдено дословно {n(c2.get('found', 0))}, "
      f"частично {n(c2.get('partial', 0))}. Исправлено по проверке: доля объяснённого разброса гравитационной модели — "
      f"70–76 %, а не три четверти «ровно».",
      f"Two researchers kept logs — {n(steps)} steps (<code>trace/r1–r2</code>): how routes are evaluated and which "
      f"data are open. Separate agents opened every source and checked the quotes (<code>verify/</code>): r1 — found "
      f"verbatim {n(c1.get('found', 0))}, partially {n(c1.get('partial', 0))}; r2 — found verbatim "
      f"{n(c2.get('found', 0))}, partially {n(c2.get('partial', 0))}. Corrected after checking: the share of variation "
      f"explained by the gravity model is 70–76 %, not 'exactly' three quarters.",
      f"Zwei Rechercheure führten Protokolle — {n(steps)} Schritte (<code>trace/r1–r2</code>): wie Strecken bewertet "
      f"werden und welche Daten offen sind. Eigene Agenten öffneten jede Quelle und prüften die Zitate "
      f"(<code>verify/</code>): r1 — wörtlich gefunden {n(c1.get('found', 0))}, teilweise {n(c1.get('partial', 0))}; "
      f"r2 — wörtlich gefunden {n(c2.get('found', 0))}, teilweise {n(c2.get('partial', 0))}. Nach der Prüfung "
      f"korrigiert: Der vom Gravitationsmodell erklärte Anteil der Streuung beträgt 70–76 %, nicht „genau“ drei "
      f"Viertel.")}</p>
<p>{T("Ряды пар собраны скриптами <code>bin/eurostat_pairs.py</code> и <code>bin/india_pairs.py</code>: пару в Европе "
      "публикуют обе страны — берём среднее; в Индии с 2026 года DGCA пишет города с аэропортом в скобках и переименовал "
      "часть городов — имена сведены, иначе рост пары оказался бы артефактом. Ряд 2023 года по Гоа в DGCA задвоен, "
      "поэтому рост к 2023 году не используем.",
      "The pair series were built with <code>bin/eurostat_pairs.py</code> and <code>bin/india_pairs.py</code>: in Europe "
      "both countries report a pair — we take the average; in India since 2026 DGCA writes cities with the airport in "
      "brackets and has renamed some cities — the names were reconciled, otherwise a pair's growth would be an artefact. "
      "DGCA's 2023 series for Goa is double-counted, so we do not use growth versus 2023.",
      "Die Paarreihen wurden mit <code>bin/eurostat_pairs.py</code> und <code>bin/india_pairs.py</code> erstellt: In "
      "Europa melden beide Länder ein Paar — wir nehmen den Mittelwert; in Indien schreibt DGCA seit 2026 Städte mit dem "
      "Flughafen in Klammern und hat einige Städte umbenannt — die Namen wurden abgeglichen, sonst wäre das Wachstum "
      "eines Paares ein Artefakt. Die DGCA-Reihe 2023 für Goa ist doppelt gezählt, daher nutzen wir kein Wachstum "
      "ggü. 2023.")}</p>
<details><summary>{T("Чего не нашлось", "What was not found", "Was nicht gefunden wurde")}</summary><ul>{gaps}</ul></details>
{S.html()}</section>"""

    return page(article_title("routes-2026-11"),
                ARTICLE_CSS + "<style>figure.fig{margin:14px 0 6px}figcaption.leg{font-size:12px;color:var(--dim)}"
                ".rmap .ac,.rmap .l-ac{display:none}.rmap.m-ac .ac{display:inline}.rmap.m-ac .l-ac{display:inline}"
                ".rmap.m-ac .tk,.rmap.m-ac .l-tk{display:none}.tg{display:flex;gap:6px;margin:0 0 6px}"
                ".tg button{font:inherit;font-size:12.5px;padding:4px 10px;border-radius:14px;border:1px solid var(--line);"
                "background:var(--bg);color:var(--ink2);cursor:pointer}.tg button.on{background:var(--ink);color:var(--bg)}"
                ".flg{display:flex;flex-wrap:wrap;gap:6px 14px;margin:4px 0 6px}.fl{display:inline-flex;align-items:center;"
                "gap:6px;color:var(--ink2)}.fl .sw{width:12px;height:12px;border-radius:3px}"
                ".fl .ph{width:64px;height:30px;object-fit:cover;border-radius:4px}"
                ".fc .fr{display:grid;grid-template-columns:250px 1fr;gap:8px;align-items:center;margin:3px 0;font-size:12.5px}"
                ".fc .fn{text-align:right;color:var(--ink)}.fc .fb{display:flex;align-items:center;gap:6px}"
                ".fc .fs{display:flex;height:15px;gap:1px}.fc .fs i{display:block;height:100%;border-radius:2px}"
                ".fc .fv{color:var(--dim);font-size:11.5px}"
                ".shc{border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0}"
                ".shc-ctl{display:flex;flex-wrap:wrap;gap:10px 18px;font-size:13px;align-items:center}"
                ".shc-ctl input[type=range]{vertical-align:middle;width:160px}.shc-ctl select{font:inherit}"
                ".shc-sum{margin:10px 0 4px;display:flex;flex-wrap:wrap;gap:6px}"
                ".chip{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;padding:2px 9px;border:1px solid var(--line);border-radius:12px}"
                ".sw{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:middle}"
                "@media(max-width:640px){.shc-t tr{display:block;border-bottom:1px solid var(--line);padding:6px 0}"
                ".shc-t thead{display:none}.shc-t td{display:flex;justify-content:space-between;border:0;padding:2px 0;text-align:right}"
                ".shc-t td::before{content:attr(data-l);color:var(--dim);text-align:left;margin-right:10px}"
                ".shc-t td.shr{display:none}.shc-t td.nm{display:block;text-align:left;font-weight:600}"
                ".shc-t td.nm::before{content:none}}@media(min-width:641px){.shc-t td.nm{white-space:normal}}#shc-shv{white-space:nowrap}"
                "@media(max-width:640px){.fc .fr{grid-template-columns:1fr;gap:2px;margin:6px 0}.fc .fn{text-align:left}}</style>"
                "<script>document.addEventListener('click',function(ev){var b=ev.target.closest('.tg button');if(!b)return;"
                "var f=b.closest('.rmap');f.classList.toggle('m-ac',b.dataset.m==='ac');"
                "f.querySelectorAll('.tg button').forEach(function(x){x.classList.toggle('on',x===b)})})</script>"
                + hook + theory + data + method + eu + ind + who + acs + concl + report)


if __name__ == "__main__":
    write_all(HERE, "routes-2026-11", build, TR)
    print(f"источников {len(S.num)}")
