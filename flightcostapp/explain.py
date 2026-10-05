"""Разбор расчёта в HTML.

Генерируется из трассировки самой модели, а не пишется отдельно. Это
принципиально: схема, набранная руками, разъезжается с кодом на первой
же правке, и через месяц ты изучаешь документ, описывающий не то, что
считается. Здесь любая правка в econ.py немедленно видна в разборе.

Цвет несёт смысл, а не украшает: каждый шаг помечен происхождением
входных данных, и по вертикальной шкале слева сразу видно, какая часть
результата стоит на реальных данных, а какая на выдуманных константах.
"""

from __future__ import annotations

import html
from datetime import date

from .ui import PROV_VAR, style_tag

# Подписи здесь, цвета — в ui.css. Второго списка цветов быть не должно.
PROV = {
    "input":    ("задано тобой",       PROV_VAR["input"]),
    "store":    ("из справочника",     PROV_VAR["store"]),
    "derived":  ("выведено формулой",  PROV_VAR["derived"]),
    "fleet":    ("константа флота",    PROV_VAR["fleet"]),
    "default":  ("ВЫДУМАНО",           PROV_VAR["default"]),
    "override": ("ЗАДАНО ВРУЧНУЮ",     PROV_VAR["override"]),
}

CSS = """
body{font-size:15px}
.wrap{max-width:1080px;margin:0 auto;padding:48px 28px 96px}
h1{font-size:15px;letter-spacing:.22em;text-transform:uppercase;
 font-weight:600;color:var(--dim);margin:0 0 6px}
.route{font:600 44px/1.05 var(--sans);
 letter-spacing:-.02em;color:var(--ink2);margin:0 0 4px}
.sub{color:var(--dim);font-size:14px;margin:0 0 34px}
.sub b{color:var(--ink);font-weight:600}

.meter{display:flex;height:8px;border-radius:4px;overflow:hidden;margin:0 0 10px}
.meter i{display:block}
.meterlab{display:flex;gap:20px;flex-wrap:wrap;font-size:12.5px;
 color:var(--dim);margin:0 0 40px}
.meterlab span{display:flex;align-items:center;gap:7px}
.palette{color:var(--dim);font-size:12.5px;margin:-26px 0 34px;max-width:70ch}
.dot{width:9px;height:9px;border-radius:2px;flex:none}

h2{font-size:12px;letter-spacing:.18em;text-transform:uppercase;
 color:var(--dim);font-weight:600;margin:38px 0 12px;
 padding-bottom:8px;border-bottom:1px solid var(--line)}

.step{display:grid;grid-template-columns:34px 1fr 176px;gap:0 18px;
 padding:13px 0 13px 0;border-bottom:1px solid var(--line2);position:relative}
.step:hover{background:var(--select)}
.step::before{content:"";position:absolute;left:14px;top:0;bottom:0;
 width:3px;background:var(--c);opacity:.85}
.n{font:400 11px/1 var(--sans);color:var(--faint);padding-top:5px;
 text-align:right;padding-right:2px}
.lab{font-weight:600;color:var(--ink2);font-size:14.5px}
.f{font:12.5px/1.6 var(--mono);color:var(--dim);
 margin-top:4px;word-break:break-word}
.f em{color:var(--faint);font-style:normal}
.note{border:0;background:none;padding:0;border-radius:0;font-size:12.5px;color:var(--dim);margin:5px 0 0}
.val{font:600 17px/1.2 var(--sans);color:var(--ink2);text-align:right;font-variant-numeric:tabular-nums;
 padding-top:2px;white-space:nowrap}
.val small{display:block;font:400 11.5px/1.5 var(--sans);
 color:var(--dim);margin-top:3px}
.tag{display:inline-block;font-size:10px;letter-spacing:.1em;
 text-transform:uppercase;font-weight:700;padding:2px 6px;border-radius:3px;
 margin-left:8px;vertical-align:1px}

.total{display:grid;grid-template-columns:34px 1fr 176px;gap:0 18px;
 padding:18px 0;border-top:2px solid var(--line);border-bottom:2px solid var(--line);
 margin-top:4px}
.total .lab{font-size:16px}
.total .val{font-size:24px}

.verdict{margin:30px 0 0;padding:22px 26px;border-radius:8px;
 background:var(--panel);border:1px solid var(--line)}
.verdict .row{display:flex;justify-content:space-between;gap:24px;
 padding:7px 0;font-size:14.5px}
.verdict .row span:last-child{font:600 15px var(--sans);color:var(--ink2);font-variant-numeric:tabular-nums}
.verdict hr{border:0;border-top:1px solid var(--line);margin:13px 0}
.big{font:600 19px var(--sans)}
.loss{color:var(--warn)}.gain{color:var(--calc)}

.warn{margin-top:34px;padding:20px 24px;border-radius:8px;
 background:var(--guess-f);border:1px solid var(--guess)}
.warn h3{margin:0 0 12px;font-size:12px;letter-spacing:.16em;
 text-transform:uppercase;color:var(--warn)}
.warn ul{margin:0;padding-left:19px;color:var(--ink);font-size:13.5px;line-height:1.75}
.ovr{margin-top:34px;padding:20px 24px;border-radius:8px;
 background:var(--override-f);border:1px solid var(--override)}
.ovr h3{margin:0 0 12px;font-size:12px;letter-spacing:.16em;
 text-transform:uppercase;color:var(--override)}
.ovr table{width:100%;border-collapse:collapse;font-size:13.5px}
.ovr td{padding:6px 0;border-bottom:1px solid var(--line);color:var(--ink)}
.ovr td.p{font:12.5px var(--mono);color:var(--override)}
.ovr td.n{text-align:right;font:600 13.5px var(--sans);color:var(--ink2);font-variant-numeric:tabular-nums;
 white-space:nowrap}
.trade{margin-top:34px;padding:20px 24px;border-radius:8px;
 background:var(--guess-f);border:1px solid var(--guess)}
.trade h3{margin:0 0 4px;font-size:12px;letter-spacing:.16em;
 text-transform:uppercase;color:var(--warn)}
.trade .lead{color:var(--ink);font-size:13.5px;margin:0 0 14px;max-width:70ch}
.trade table{width:100%;border-collapse:collapse;font-size:13.5px}
.trade td{padding:7px 0;border-bottom:1px solid var(--line);color:var(--ink)}
.trade td:last-child{text-align:right;font:600 14px var(--sans);
 color:var(--ink2);white-space:nowrap;font-variant-numeric:tabular-nums}
.head{margin-top:34px;padding:16px 24px;border-radius:8px;background:var(--calc-f);
 border:1px solid var(--calc);color:var(--ink);font-size:13.5px}
.ovr .foot2{color:var(--dim);font-size:12.5px;margin-top:12px;line-height:1.6}
.marg{margin-top:34px}
.marg h3{margin:0 0 4px;font-size:12px;letter-spacing:.16em;
 text-transform:uppercase;color:var(--dim)}
.marg .sub2{color:var(--dim);font-size:12.5px;margin:0 0 14px;max-width:72ch}
.marg table{width:100%;border-collapse:collapse;font-size:13.5px}
.marg th{text-align:right;font-size:10.5px;letter-spacing:.1em;
 text-transform:uppercase;color:var(--dim);font-weight:600;padding:0 0 8px}
.marg th:first-child{text-align:left}
.marg td{padding:9px 0;border-bottom:1px solid var(--line2);text-align:right;
 font:13.5px var(--sans);color:var(--ink);white-space:nowrap;font-variant-numeric:tabular-nums}
.marg td:first-child{text-align:left;font:600 13.5px var(--sans);
 color:var(--ink2)}
.marg td.m{font-weight:700}
.bar{display:block;height:4px;border-radius:2px;margin-top:5px;
 background:var(--line);overflow:hidden}
.bar i{display:block;height:100%}
/* Подсказка — блок с ограниченной шириной. Без margin-left:auto он
   прижимается к левому краю ячейки, а текст внутри выравнивается по
   правому краю блока, а не ячейки: получается лишний отступ, которого
   у числа нет. */
.split{display:block;font:11.5px/1.5 var(--sans);color:var(--dim);
 margin:4px 0 0 auto;white-space:normal;max-width:34ch}
.split.dim{color:var(--faint);margin-top:2px}
.about{display:block;font:400 12px/1.5 var(--sans);color:var(--dim);
 margin:3px auto 0 0;white-space:normal;max-width:40ch}
.marg td{vertical-align:top}
.marg td .num{display:block;white-space:nowrap}
.marg .assume{color:var(--faint);font-size:12px;margin-top:14px;line-height:1.6}
.wall{display:block;font:400 12px/1.5 var(--sans);color:var(--dim);
 margin:4px auto 0 0;white-space:normal;max-width:46ch}
.foot{margin-top:44px;color:var(--faint);font-size:12.5px;line-height:1.7}
@media(max-width:720px){
 .step,.total{grid-template-columns:26px 1fr;gap:0 12px}
 .val{grid-column:2;text-align:left;padding-top:8px}
 .route{font-size:32px}}
"""


def _fmt(v: float, unit: str) -> str:
    if unit == "доля":
        return f"{v*100:.1f}%"
    if unit == "EUR":
        return f"{v:,.0f}".replace(",", " ")
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    if abs(v) >= 10:
        return f"{v:,.1f}"
    return f"{v:,.3f}".rstrip("0").rstrip(".")


# Ось состояний величины, общая для запаса прочности, полноты начисления
# и будущих полей формы. Ключи английские (решение 27), подписи здесь.
# `failed` НИКОГДА не рисуется строкой ответа: это сообщение о поломке,
# а не утверждение о мире, и уходит в предупреждения.
STATE_RU = {
    "ok":             "",
    "not_applicable": "нет по правилу",
    "unknown":        "не знаем",
    "unset":          "не задан вход",
    "failed":         "не считалось",
}
# Кому адресовано отсутствие: решение 78. «Не знаем» — вопрос к нам,
# «не задан вход» — к пользователю. Слить их значит обвинить данные в
# том, чего не ввёл человек.
STATE_WHO = {"unknown": "уточняется в справочнике",
             "unset": "задаётся при расчёте"}


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение после числа: 1 пассажир, 2 пассажира, 5 пассажиров."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def to_html(res, margins=None) -> str:
    e = html.escape
    inp = res.inputs
    lf, fare, seats = inp["load_factor"], inp.get("fare_eur"), inp["seats"]

    # шкала происхождения по долям итоговой суммы
    buckets: dict[str, float] = {}
    for name, val in res.cost.items():
        buckets[res.cost_prov.get(name, "derived")] = \
            buckets.get(res.cost_prov.get(name, "derived"), 0) + val
    total = res.cost_total or 1
    order = ["store", "derived", "fleet", "override", "default"]
    meter = "".join(
        f'<i style="width:{buckets[k]/total*100:.2f}%;background:{PROV[k][1]}"></i>'
        for k in order if buckets.get(k))
    labels = "".join(
        f'<span><i class="dot" style="background:{PROV[k][1]}"></i>'
        f'{PROV[k][0]} — {buckets[k]/total*100:.0f}%</span>'
        for k in order if buckets.get(k))

    # шаги, сгруппированные по разделам
    body, cur = [], None
    for s in res.trace:
        if s.group != cur:
            cur = s.group
            body.append(f"<h2>{e(cur)}</h2>")
        col = PROV[s.prov][1]
        tag = ""
        if s.prov in ("default", "override"):
            tag = (f'<span class="tag" style="background:{col}22;color:{col}">'
                   f'{PROV[s.prov][0]}</span>')
        subst = f'<div class="f"><em>=</em> {e(s.subst)}</div>' if s.subst else ""
        note = f'<div class="note">{e(s.src)}</div>' if s.src else ""
        body.append(
            f'<div class="step" style="--c:{col}">'
            f'<div class="n">{s.n}</div>'
            f'<div><div class="lab">{e(s.label)}{tag}</div>'
            f'<div class="f">{e(s.formula)}</div>{subst}{note}</div>'
            f'<div class="val">{_fmt(s.value, s.unit)}<small>{e(s.unit)}</small></div>'
            f'</div>')

    body.append(
        f'<div class="total"><div class="n"></div>'
        f'<div class="lab">Полная себестоимость рейса</div>'
        f'<div class="val">{_fmt(res.cost_total,"EUR")}<small>EUR</small></div></div>')

    # вердикт
    v = [f'<div class="row"><span>Задана загрузка</span>'
         f'<span>{lf*100:.0f}% — {seats*lf:.0f} из {seats} кресел</span></div>']
    if fare:
        v.append(f'<div class="row"><span>Задан тариф</span>'
                 f'<span>{fare:,.0f} EUR за пассажира</span></div>')
    v.append("<hr>")
    v.append(f'<div class="row"><span>Чтобы выйти в ноль при загрузке '
             f'{lf*100:.0f}%, тариф должен быть</span>'
             f'<span class="big">{res.breakeven_fare_eur:,.0f} EUR</span></div>')
    if res.breakeven_lf is not None:
        v.append(f'<div class="row"><span>Чтобы выйти в ноль при тарифе '
                 f'{fare:,.0f} EUR, загрузка должна быть</span>'
                 f'<span class="big">{res.breakeven_lf*100:.1f}%</span></div>')
        gap = (fare - res.breakeven_fare_eur) * seats * lf
        cls = "gain" if gap >= 0 else "loss"
        word = "Прибыль" if gap >= 0 else "Убыток"
        v.append("<hr>")
        v.append(f'<div class="row"><span>При твоих {lf*100:.0f}% и '
                 f'{fare:,.0f} EUR</span>'
                 f'<span class="big {cls}">{word} {abs(gap):,.0f} EUR за рейс</span>'
                 f'</div>')

    marg = ""
    # ── Полнота начисления ───────────────────────────────────────────
    # Не помещается в шкалу происхождения: у неначисленной статьи доля
    # суммы ноль по построению, а полоса нулевой ширины невидима — то
    # есть попытка втиснуть её туда даёт ровно тихий отказ, против
    # которого механизм и написан.
    gaps = ""
    gr = getattr(res, "charge_gaps", None)
    if gr is None:
        # `failed`: отчёт не считался. Не строка ответа, а поломка.
        res.warnings = list(res.warnings) + [
            "полнота начисления не считалась — отчёт не заполнен"]
    else:
        rows = []
        for icao, rep in sorted(gr.items()):
            lost = rep.get("lost_codes") or []
            if not lost:
                continue
            # Разделение по адресату приезжает из charges.py готовым:
            # оно выводится из KEY_ORIGIN, и там же стоит проверка, что
            # список условий не разошёлся с ним. Собирать его здесь
            # заново значило бы завести второй список допустимого.
            parts = []
            for key, state in (("missing_data", "unknown"),
                               ("missing_input", "unset")):
                ks = rep.get(key) or []
                if not ks:
                    continue
                tail = (f', ключ --set charge_context.{e(icao)}.&lt;условие&gt;'
                        if state == "unset" else "")
                parts.append(f'<span class="wall">{STATE_RU[state]}: '
                             f'{e(", ".join(ks))} — {STATE_WHO[state]}'
                             f'{tail}</span>')
            # Третий случай: выводимая величина не посчиталась. Это не
            # «не знаем» и не «не задан вход», а дефект расчёта — то есть
            # `failed`, и место ему в предупреждениях, а не в строке.
            broke = rep.get("missing_derived") or []
            if broke:
                res.warnings = list(res.warnings) + [
                    f"{icao}: не вычислены условия {', '.join(broke)} — "
                    f"дефект расчёта, статьи остались без цены"]
                parts.append(f'<span class="wall" style="color:var(--warn)">'
                             f'{STATE_RU["failed"]}: {e(", ".join(broke))}'
                             f'</span>')
            rows.append(
                f'<tr><td>{e(icao)}{"".join(parts)}</td>'
                f'<td><span class="num">{len(lost)}</span>'
                f'<span class="split">из {rep.get("total_codes", "?")} статей '
                f'тарифа</span></td>'
                f'<td><span class="split">{e(", ".join(lost))}</span></td></tr>')
        if rows:
            gaps = (f'<div class="marg"><h3>Не начислено</h3>'
                    f'<p class="sub2">Статьи, у которых в тарифе есть правило, '
                    f'но нет значения условия. Величина здесь не показана и '
                    f'показана быть не может: если бы она была известна, статья '
                    f'не осталась бы без цены. Считать эти статьи нулём нельзя '
                    f'— «нет» и «не знаем» разные утверждения.</p>'
                    f'<table><tr><th>аэропорт</th><th>без цены</th>'
                    f'<th>какие статьи</th></tr>{"".join(rows)}</table></div>')

    marg = ""
    if margins:
        # Режим блока определяется знаком прибыли, а не свойствами
        # параметра: порог — это безубыточность, поэтому в прибыли все
        # пороги лежат на стороне ухудшения (запас), а в убытке — на
        # стороне улучшения (дефицит). Одно и то же число значит в них
        # противоположное.
        profit = None
        if fare is not None:
            profit = (fare - res.breakeven_fare_eur) * seats * lf
        deficit = profit is not None and profit < 0

        # Своя шкала, не общая. Общая означает происхождение, эта —
        # тесноту. Оттенки взяты у вердикта (.loss/.gain), а не у
        # происхождения, чтобы янтарный остался за «выдумано».
        BAD, MUTE, GOOD, DEF = "var(--warn)", "var(--dim)", "var(--calc)", "var(--guess)"

        pcts = [abs(m["margin_pct"]) for m in margins
                if m.get("status", "ok") == "ok" and not m.get("inert")
                and m.get("margin_pct") is not None]
        worst = max(pcts) if pcts else 1

        rows = []
        # Переезд со словаря margins() на общую ось: `unreachable` был
        # частным случаем `not_applicable`, `inert` — тоже. Одно понятие
        # не должно выражаться и ключом словаря, и флагом рядом.
        legacy = any("status" in m or "inert" in m for m in margins)
        def _state(m):
            if "state" in m:
                return m["state"], m.get("reason")
            if m.get("inert"):
                return "not_applicable", "not_in_model"
            st = m.get("status", "ok")
            return ({"unreachable": "not_applicable"}.get(st, st),
                    "limit" if st == "unreachable" else None)

        for m in margins:
            st, reason = _state(m)
            head = (f'{e(m["label"])}'
                    + (f'<span class="about">{e(m["about"])}</span>'
                       if m.get("about") else ""))
            now = (f'<td><span class="num">{_fmt(m["now"],"")} {e(m["unit"])}</span>'
                   + (f'<span class="split">{e(m["hint_now"])}</span>'
                      if m.get("hint_now") else "")
                   + (f'<span class="split dim">{e(m["split"])}</span>'
                      if m.get("split") else "")
                   + "</td>") if m.get("now") is not None else "<td></td>"

            # Параметр не участвует в расчёте: порога нет и быть не может.
            if st == "not_applicable" and reason == "not_in_model":
                rows.append(
                    f'<tr><td>{head}<span class="wall">не входит в расчёт'
                    + (f': {e(m["note"])}' if m.get("note") else "")
                    + f'</span></td>{now}<td></td>'
                    f'<td class="m" style="color:{MUTE}">—</td></tr>')
                continue

            if st == "ok":
                pct = m["margin_pct"]
                a = abs(pct)
                # В убытке ни одна строка не запас, поэтому шкала тесноты
                # там не применяется.
                col = BAD if deficit else (
                    BAD if a < 15 else MUTE if a < 40 else GOOD)
                arrow = "↑" if pct > 0 else "↓"   # всегда в сторону порога
                rows.append(
                    f'<tr><td>{head}'
                    f'<span class="bar"><i style="width:{a/worst*100:.0f}%;'
                    f'background:{col}"></i></span></td>{now}'
                    f'<td><span class="num">{_fmt(m["edge"],"")} {e(m["unit"])}</span>'
                    + (f'<span class="split">{e(m["hint_edge"])}</span>'
                       if m.get("hint_edge") else "")
                    + "</td>"
                    f'<td class="m" style="color:{col}">{arrow}{a:.0f}%</td></tr>')
                continue

            if st == "not_applicable":
                search = m.get("limit_reason") == "search_range"
                gap_l = m.get("gap_at_limit")
                if search:
                    # Утверждение о нашем поиске, а не о мире.
                    said = "порог не найден в пределах поиска"
                elif gap_l is not None and gap_l < 0:
                    said = ("на границе не хватает "
                            + f"{abs(gap_l):,.0f}".replace(",", " ") + " EUR")
                elif gap_l is not None:
                    said = "на границе рейс всё ещё окупается"
                else:
                    said = "порога в допустимой области нет"
                why = m.get("limit_about") or m.get("note") or ""
                rows.append(
                    f'<tr><td>{head}<span class="wall">{e(said)}'
                    + (f" — {e(why)}" if why else "")
                    + f'</span></td>{now}'
                    f'<td><span class="num">{_fmt(m["limit"],"")} {e(m["unit"])}'
                    f'</span><span class="split">'
                    + (e(m["hint_limit"]) if m.get("hint_limit") else "граница")
                    + "</span></td>"
                    f'<td class="m" style="color:{MUTE}">'
                    + ("—" if search else "упор")
                    + "</td></tr>")
                continue

            # failed — дефект расчёта, а не вывод о маршруте.
            rows.append(
                f'<tr><td>{head}<span class="wall" style="color:{DEF}">'
                f"расчёт не сошёлся"
                + (f': {e(m["note"])}' if m.get("note") else "")
                + f'</span></td>{now}<td></td>'
                f'<td class="m" style="color:{DEF}">сбой</td></tr>')

        if deficit:
            title = "Чего не хватает"
            sub = ("Насколько каждое допущение должно улучшиться, чтобы рейс "
                   "вышел в ноль. Строки идут по возрастанию недобора: верхняя "
                   "— самый дешёвый путь к нулю. «Упор» значит, что параметр не "
                   "дотягивается до порога даже на своей границе, то есть им "
                   "рейс не спасти.")
            col4, col3 = "дефицит", "граница"
        else:
            title = "Запас прочности"
            sub = ("Насколько каждое допущение может уйти, прежде чем рейс "
                   "перестанет окупаться. Смысл не в самих порогах, а в их "
                   "сравнении: параметр с запасом в несколько процентов решает "
                   "судьбу маршрута, параметр с запасом в разы можно не "
                   "уточнять.")
            col4, col3 = "запас", "порог"
        marg = (f'<div class="marg"><h3>{title}</h3>'
                f'<p class="sub2">{sub}</p>'
                f"<table><tr><th>параметр</th><th>сейчас</th>"
                f"<th>{col3}</th><th>{col4}</th></tr>"
                f'{"".join(rows)}</table>'
                f'<p class="assume">Цвет в этой таблице означает тесноту, а не '
                f"происхождение: это единственное место в разборе, где он "
                f"оценивает. Стрелка направлена в сторону порога. Стоимость "
                f"борта — прикидка по договору на 12 лет при ставке 7,5% и "
                f"остаточном платеже 40%. Порядок величины, а не оценка "
                f"сделки.</p></div>")


    trade = ""
    if not getattr(res, "feasible", True):
        t = getattr(res, "trade", None) or {}
        if t:
            rows = [
                ("Снять пассажиров", f"{t['pax_drop']}"),
                ("Останется на борту", f"{t['pax_ok']} из "
                                       f"{inp['seats']} ({t['lf_ok']*100:.0f}%)"),
                ("Выручка рейса падает на", f"{t['revenue_loss']:,.0f} EUR"),
                ("Безубыточный тариф",
                 f"{t['breakeven_before']:,.0f} → {t['breakeven_after']:,.0f} EUR"),
            ]
            body_t = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td></tr>"
                             for a, b in rows)
            lead = ("Рейс не выполним с заданной загрузкой: не хватает "
                    "предельной взлётной массы или ёмкости баков. Отказ без "
                    "цены — половина ответа, поэтому вот чем платить за то, "
                    "чтобы он состоялся.")
        else:
            body_t = ("<tr><td>Компромисса нет</td><td>тип не долетит "
                      "и пустым</td></tr>")
            lead = ("Рейс не выполним на этом типе ни при какой загрузке: "
                    "плечо превышает перегоночную дальность.")
        trade = (f'<div class="trade"><h3>Рейс невыполним</h3>'
                 f'<p class="lead">{lead}</p><table>{body_t}</table></div>')
    elif getattr(res, "max_pax", 0):
        seats_n = int(inp.get("seats") or 0)
        head = min(res.max_pax, seats_n) - int(round(inp.get("pax", 0)))
        if head > 0:
            limit = "кресла" if res.max_pax >= seats_n else "масса"
            extra = ""
            if res.max_pax > seats_n:
                extra = (f" По массе борт поднял бы ещё "
                         f"{res.max_pax - seats_n} человек: около "
                         f"{(res.max_pax - seats_n) * 0.1:.1f} т свободной "
                         f"нагрузки, которую мог бы занять груз.")
            trade = (f'<div class="head">Запас: ещё {head} '
                     f'{_plural(head,"пассажир","пассажира","пассажиров")} до '
                     f'полной загрузки, ограничивает {limit}.{e(extra)}</div>')
        elif head == 0:
            trade = ('<div class="head">Загрузка предельная: свободных '
                     'кресел нет.</div>')

    ovr = ""
    if getattr(res, "overrides", None):
        rows = "".join(
            f'<tr><td class="p">{e(x["path"])}</td>'
            f'<td class="n">{_fmt(x["was"], "") if x["was"] is not None else "—"}'
            f' &rarr; {_fmt(x["now"], "")}</td></tr>'
            for x in res.overrides)
        ovr = (f'<div class="ovr"><h3>Задано вручную для этого расчёта</h3>'
               f'<table>{rows}</table>'
               f'<div class="foot2">Значения слоя сценария. В справочник не '
               f'записываются и другим пользователям не видны. За них отвечает '
               f'тот, кто их задал — поэтому они выделены отдельно от '
               f'выдуманных заготовок.</div></div>')

    warn = ""
    skip = ("задано вручную",)
    shown = [w for w in res.warnings if not w.startswith(skip)]
    if shown:
        items = "".join(f"<li>{e(w)}</li>" for w in shown)
        warn = (f'<div class="warn"><h3>Чему здесь нельзя верить</h3>'
                f'<ul>{items}</ul></div>')

    UI = style_tag(inline_fonts=True)      # страница открывается без сети
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(res.origin)}–{e(res.destination)} · разбор расчёта</title>
{UI}<style>{CSS}</style></head><body><div class="wrap">
<h1>Разбор расчёта</h1>
<div class="route">{e(res.origin)} → {e(res.destination)}</div>
<p class="sub"><b>{e(inp['origin_name'])}</b> → <b>{e(inp['dest_name'])}</b> ·
{e(res.aircraft)} · {res.distance_nm:.0f} nm · блок {res.block_h:.2f} ч ·
справочники на дату <b>{e(str(inp['as_of']))}</b></p>

<div class="meter">{meter}</div>
<div class="meterlab">{labels}</div>
<p class="palette">Янтарный — единственный цвет тревоги: им помечено то, что
взято из воздуха. Всё остальное — происхождение, а не оценка качества.</p>

{''.join(body)}

<div class="verdict">{''.join(v)}</div>
{trade}
{gaps}{marg}
{ovr}
{warn}

<p class="foot">Сгенерировано моделью {date.today().isoformat()} командой
<code>fca econ … --explain</code>. Каждая строка — шаг из трассировки
самого расчёта, а не отдельно написанная документация: правка в
<code>econ.py</code> сразу меняет этот разбор.<br>
Оранжевым помечено то, что взято из воздуха — заглушки в коде на месте
данных, которых в справочнике ещё нет. Верхняя шкала показывает их долю
в итоговой сумме.</p>
</div></body></html>"""
