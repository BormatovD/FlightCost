"""Отчёт по парку в Excel с живыми формулами: объём → рейсы → борты → итог.

Тот же план, что в отчёте (решение 204), но формулами: ядро даёт только
коэффициенты плеча (блок-время, кресла, потолок пассажиров по дальности,
топливо на рейс и на пассажира, сборы на рейс и на пассажира, рыночная
цена), всё остальное считается от листа «Допущения»: доля потока, цена,
эластичность, плановая загрузка, нижняя граница частоты, резерв парка,
топливо, лизинг, ТОиР, экипаж. Поток пары можно вписать или поправить
прямо на листе типа — пара без потока не летается.

Цвета — как принято в финансовых моделях: синий — ввод, чёрный —
формула, зелёный — ссылка на другой лист, серый — коэффициенты ядра.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

from .network import CONV_BASE, CONV_THICK, DIST_RATE, THICK_PAX_MONTH

FONT = "Arial"
F_IN = Font(name=FONT, color="0000FF")
F_CALC = Font(name=FONT, color="000000")
F_LINK = Font(name=FONT, color="008000")
F_COEF = Font(name=FONT, color="808080")
F_B = Font(name=FONT, bold=True)
F_H = Font(name=FONT, bold=True, size=13)
F_NOTE = Font(name=FONT, italic=True, color="595959", size=9)
F_RNG = Font(name=FONT, bold=True, color="C55A11")      # предел по дальности — оранжевым
FILL_KEY = PatternFill("solid", fgColor="FFFF00")
FILL_HEAD = PatternFill("solid", fgColor="DDEBF7")
FILL_COEF = PatternFill("solid", fgColor="F2F2F2")
THIN = Border(bottom=Side(style="thin", color="999999"))
WRAP = Alignment(wrap_text=True, vertical="top")

EUR = '#,##0;(#,##0);"-"'
EUR2 = '#,##0.00;(#,##0.00);"-"'
PCT = '0.0%;(0.0%);"-"'
NUM1 = '#,##0.0;(#,##0.0);"-"'
NUM0 = '#,##0;(#,##0);"-"'
NUM3 = '0.000'
MULT = '0.00"×"'

PROV_RU = {"input": "задано", "store": "справочник", "override": "своё", "default": "заготовка",
           None: "—"}

# Колонки листа типа: (заголовок, ширина). Порядок — порядок расчёта.
COLS = [
    ("Пара", 11), ("Откуда", 8), ("Куда", 8), ("Поток пары, пасс./мес", 12),
    ("Наш объём пары, пасс./мес", 12), ("Плеч в паре", 7), ("Спрос на плечо, пасс./мес", 12),
    ("Блок, ч", 7), ("Кресел", 7), ("Поднимет пасс.", 8), ("Пасс. на рейс при плановой загрузке", 11),
    ("Нужно рейсов в неделю", 10), ("Рейсов туда-обратно в неделю", 11), ("Рейсов в месяц", 9),
    ("Пассажиров на рейс", 10), ("Загрузка", 8), ("Рыночная цена, EUR", 10), ("Чек, EUR", 9),
    ("Выручка", 12), ("Дистрибуция", 11), ("Топливо, кг на рейс", 10), ("Цена топлива, EUR/кг", 9),
    ("Топливо", 11), ("ТОиР", 11), ("Экипаж", 11), ("Аэронавигация", 11), ("Аэропорт", 11),
    ("Обслуживание", 11), ("Прочее", 10), ("Итог плеча", 12), ("Км по прямой", 8),
    ("Предел загрузки по дальности", 10),
    # коэффициенты ядра
    ("кг на рейс при 0 пасс.", 10), ("кг на пассажира", 9), ("цена топлива ядра", 9),
    ("аэронавигация на рейс", 10), ("аэронавигация на пасс.", 10), ("аэропорт на рейс", 10),
    ("аэропорт на пасс.", 10), ("обслуживание на рейс", 10), ("обслуживание на пасс.", 10),
    ("прочее на рейс", 10), ("прочее на пасс.", 10),
]
C = {h: L(i) for i, (h, _) in enumerate(COLS, start=1)}
COEF0 = 33                      # первая колонка коэффициентов


def _sheet_name(icao: str, used: set) -> str:
    base = "Тип " + "".join(c for c in icao.replace("USER:", "") if c not in "[]:*?/\\")[:20]
    name, i = base, 2
    while name in used:
        name, i = f"{base[:27]} {i}", i + 1
    used.add(name)
    return name


def _q(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def build_xlsx(rep: dict, results: dict) -> bytes:
    """Книга по отчёту `fleetreport.build` и ответам сети по типам."""
    from .fleetreport import TypePlan
    wb = Workbook()
    a = rep["assume"]
    ok = sorted([t for t in rep["types"] if t.get("status") == "ok"], key=lambda t: t["rank"])
    ctx = rep.get("context") or {}

    # ── Допущения ───────────────────────────────────────────────────────
    A = wb.active
    A.title = "Допущения"
    A["A1"] = "Отчёт по парку — допущения"
    A["A1"].font = F_H
    A["A2"] = (f"Сеть: база {ctx.get('base', '—')}, аэропорты {', '.join(ctx.get('airports') or [])}"
               f"{', месяц ' + str(ctx['month']) if ctx.get('month') else ''}; расчёт "
               f"{rep.get('as_of')}. Деньги — EUR в месяц, если не сказано иначе.")
    A["A2"].font = F_NOTE
    A["A3"] = ("Синий — ввод; чёрный — формула; зелёный — ссылка на другой лист; серый — "
               "коэффициенты плеча из расчётного ядра. Жёлтым — главные рычаги.")
    A["A3"].font = F_NOTE
    rows = [
        ("Наша доля потока при рыночной цене", a["share"], PCT, True,
         "доля нынешнего потока каждой пары"),
        ("Наша цена к рыночной", a["price"], MULT, True, "множитель к рыночной цене плеча"),
        ("Эластичность доли по цене", a["elasticity"], "0.0", True,
         "ДОПУЩЕНИЕ: доля × цена^(−эластичность); данных об отклике нет"),
        ("Потолок доли", a["share_cap"], PCT, False, "больше — уже не «отжать», а занять рынок"),
        ("Доля после отклика на цену", "=MIN(B5*B6^(-B7),B8)", PCT, False, "формула"),
        ("Плановая загрузка", a["lf_target"], PCT, True, "под неё подбираются частоты"),
        ("Рейсов туда-обратно в неделю, не меньше", a["min_freq"], "0", True,
         "реже — не регулярная линия"),
        ("Резерв парка", a["reserve"], PCT, False, "доля от эксплуатационного парка, не меньше борта"),
        ("Средний чек к минимальному", a.get("fare_conv"), MULT, True,
         "пусто — по потоку пары (две строки ниже); число — всем парам одно (решение 210)"),
        ("Дистрибуция, доля выручки", DIST_RATE, PCT, False, "та же величина, что в ядре"),
        ("Цена топлива, EUR/кг", None, EUR2, False,
         "пусто — у каждого плеча своя цена из ядра (по аэропорту вылета)"),
        ("Недель в месяце", "=365.25/12/7", NUM3, False, "календарная величина"),
        ("Чек к минимуму на обычной паре", CONV_BASE, MULT, False,
         "ДОПУЩЕНИЕ: медиана минимумов → средний чек, когда B13 пусто"),
        ("Чек к минимуму на загруженной паре", CONV_THICK, MULT, False,
         "ДОПУЩЕНИЕ: на загруженных парах разрыв больше — акционные минимумы, поздние и деловые покупки"),
        ("Загруженная пара — поток от, пасс./мес", THICK_PAX_MONTH, NUM0, False,
         "в обе стороны; ≈ 1 млн пассажиров в год"),
    ]
    for i, (lab, v, fmt, key, note) in enumerate(rows, start=5):
        A.cell(i, 1, lab).font = F_CALC
        c = A.cell(i, 2, v)
        c.number_format = fmt
        c.font = F_CALC if isinstance(v, str) and v.startswith("=") else F_IN
        if key:
            c.fill = FILL_KEY
        A.cell(i, 3, note).font = F_NOTE
    SHARE, LFT, MINF, RES, CONV, DIST, FUEL, WPM = (
        f"Допущения!$B${i}" for i in (9, 10, 11, 12, 13, 14, 15, 16))
    PRICE = "Допущения!$B$6"
    CBASE, CTHICK, CTHR = (f"Допущения!$B${i}" for i in (17, 18, 19))

    A["A21"] = "Ставки типов"
    A["A21"].font = F_B
    head = ["Тип", "Кресел", "Лизинг, EUR/мес на борт", "ТОиР, EUR/ч", "ТОиР, EUR/цикл",
            "Экипаж, EUR/ч", "Экипаж, EUR/цикл", "Налёт борта, ч/мес", "Происхождение ставок"]
    for j, h in enumerate(head, start=1):
        c = A.cell(22, j, h)
        c.font, c.fill, c.alignment = F_B, FILL_HEAD, WRAP
    type_row = {}
    for i, t in enumerate(ok, start=23):
        type_row[t["icao"]] = i
        rt, pv = t.get("rates") or {}, t.get("prov") or {}
        vals = [t["name"], t.get("seats"), t.get("lease_eur_month"), rt.get("maint_fh"),
                rt.get("maint_fc"), rt.get("crew_fh"), rt.get("crew_fc"), t.get("util_h_month"),
                ", ".join(f"{k} — {PROV_RU.get(pv.get(x), pv.get(x))}" for k, x in
                          (("лизинг", "lease"), ("налёт", "util"), ("ТОиР", "maint"), ("экипаж", "crew")))]
        fmts = [None, "0", EUR, EUR, EUR, EUR, EUR, "0", None]
        for j, (v, f) in enumerate(zip(vals, fmts), start=1):
            c = A.cell(i, j, v)
            if f:
                c.number_format = f
            c.font = F_COEF if j == 2 else (F_NOTE if j == 9 else F_IN)
    A.column_dimensions["A"].width = 40
    A.column_dimensions["B"].width = 13
    A.column_dimensions["C"].width = 16
    for col in "DEFGH":
        A.column_dimensions[col].width = 14
    A.column_dimensions["I"].width = 60

    # ── лист каждого типа ───────────────────────────────────────────────
    used = {"Допущения", "Сводка", "Доступность", "Пояснения"}
    tot = {}
    for t in ok:
        tp = TypePlan(t["icao"], results[t["icao"]])
        S = wb.create_sheet(_sheet_name(t["icao"], used))
        r0 = type_row[t["icao"]]
        LEASE, MFH, MFC, CFH, CFC, UTIL = (f"Допущения!${c}${r0}" for c in "CDEFGH")
        S["A1"] = f"{t['name']} — объём, рейсы, борты"
        S["A1"].font = F_H
        S["A2"] = ("Строка — плечо (направление). Поток пары можно вписать или поправить: пустой "
                   "поток — пара не летается. Серым справа — коэффициенты ядра.")
        S["A2"].font = F_NOTE
        H = 4
        for j, (h, w) in enumerate(COLS, start=1):
            c = S.cell(H, j, h)
            c.font, c.alignment = F_B, WRAP
            c.fill = FILL_COEF if j >= COEF0 else FILL_HEAD
            S.column_dimensions[L(j)].width = w
        S.row_dimensions[H].height = 58
        r = H + 1
        first = r
        for p in tp.pairs:
            legs = p["legs"]
            pr0, pr1 = r, r + len(legs) - 1
            for lg in legs:
                prt = lg.get("parts") or {}
                has = bool(prt)
                nav = prt.get("enroute", [0, 0])
                apt = [prt.get("airport_charges", [0, 0])[0] + prt.get("terminal", [0, 0])[0],
                       prt.get("airport_charges", [0, 0])[1] + prt.get("terminal", [0, 0])[1]]
                hnd = prt.get("ground_handling", [0, 0])
                oth = prt.get("other", [0, 0]) if has else [lg["fixed_eur"], lg["per_pax_eur"]]
                coef = [lg.get("fuel_kg0") or 0, lg.get("fuel_kg_per_pax") or 0,
                        lg.get("fuel_price") or 0, nav[0], nav[1], apt[0], apt[1],
                        hnd[0], hnd[1], oth[0], oth[1]]
                for j, v in enumerate(coef, start=COEF0):
                    c = S.cell(r, j, v)
                    c.font, c.fill = F_COEF, FILL_COEF
                    c.number_format = NUM3 if j in (COEF0 + 1, COEF0 + 2) else EUR2
                AF, AG, AH, AI, AJ, AK, AL, AM, AN, AO, AP = (f"{L(COEF0 + k)}{r}" for k in range(11))
                mk = p["market"] if r == pr0 else f"=D{pr0}"
                row = {
                    1: p["key"], 2: lg["origin"], 3: lg["destination"], 4: mk,
                    5: f'=IF(D{r}="",0,D{r}*{SHARE})', 6: len(legs), 7: f"=E{r}/F{r}",
                    8: lg.get("block_h"), 9: lg.get("seats"), 10: lg.get("max_pax"),
                    11: f"=MIN({LFT}*I{r},J{r})", 12: f"=IF(K{r}>0,G{r}/({WPM}*K{r}),0)",
                    # Частота — у пары: столько, сколько нужно самому полному
                    # плечу, вверх до целого, но не меньше нижней границы.
                    13: f'=IF(D{r}="",0,MAX({MINF},ROUNDUP(MAX(L{pr0}:L{pr1}),0)))',
                    14: f"=M{r}*{WPM}", 15: f"=IF(N{r}>0,MIN(G{r}/N{r},J{r}),0)",
                    16: f"=IF(I{r}>0,O{r}/I{r},0)", 17: lg.get("fare_eur"),
                    # Чек к минимуму: заданный — всем; пусто — по потоку пары.
                    18: (f'=Q{r}*{PRICE}*IF(ISBLANK({CONV}),'
                         f'IF(N(D{r})>={CTHR},{CTHICK},{CBASE}),{CONV})'), 19: f"=O{r}*R{r}*N{r}", 20: f"=S{r}*{DIST}",
                    21: f"={AF}+{AG}*O{r}", 22: f"=IF(ISBLANK({FUEL}),{AH},{FUEL})",
                    # Без статей (старый кэш) топливо, ТОиР и экипаж сидят в
                    # «прочем»: показать их отдельно, не задвоив, нельзя.
                    23: f"=U{r}*V{r}*N{r}" if has else 0,
                    24: f"=({MFH}*H{r}+{MFC})*N{r}" if has else 0,
                    25: f"=({CFH}*H{r}+{CFC})*N{r}" if has else 0,
                    26: f"=({AI}+{AJ}*O{r})*N{r}", 27: f"=({AK}+{AL}*O{r})*N{r}",
                    28: f"=({AM}+{AN}*O{r})*N{r}", 29: f"=({AO}+{AP}*O{r})*N{r}",
                    30: f"=S{r}-T{r}-SUM(W{r}:AC{r})", 31: p["dist"],
                    # Борт по дальности поднимает меньше плановой загрузки —
                    # рейсы подобраны по этому пределу (колонка K).
                    32: f'=IF(J{r}<{LFT}*I{r},J{r}/I{r},"")',
                }
                fm = {4: NUM0, 5: NUM0, 6: "0", 7: NUM0, 8: "0.00", 9: "0", 10: "0", 11: NUM1,
                      12: "0.00", 13: "0", 14: NUM1, 15: NUM1, 16: PCT, 17: EUR2, 18: EUR2,
                      21: NUM0, 22: NUM3, 31: NUM0, 32: PCT}
                for j, v in row.items():
                    c = S.cell(r, j, v)
                    c.number_format = fm.get(j, EUR)
                    if j == 4 and r == pr0 or j == 17:
                        c.font = F_IN
                    elif j in (6, 8, 9, 10, 31):
                        c.font = F_COEF
                    elif j == 32:
                        c.font = F_RNG
                    else:
                        c.font = F_CALC
                if r == pr0 and p.get("market_src"):
                    S.cell(r, 4).comment = Comment(f"Источник потока: {p['market_src']}"[:900],
                                                   "FlightCostApp")
                r += 1
        last = r - 1
        S.cell(r, 1, "Итого за месяц").font = F_B
        for j in (5, 14, 19, 20) + tuple(range(23, 31)):
            col = L(j)
            # Объём пары стоит на каждом плече — сумма по парам, не по плечам.
            f = (f"=SUMPRODUCT(E{first}:E{last}/F{first}:F{last})" if j == 5
                 else f"=SUM({col}{first}:{col}{last})")
            c = S.cell(r, j, f)
            c.font, c.border = F_B, THIN
            c.number_format = NUM1 if j == 14 else (NUM0 if j == 5 else EUR)
        tr = r
        rng = lambda col: f"{col}{first}:{col}{last}"            # noqa: E731
        lines = [
            ("Блок-часов в месяц", f"=SUMPRODUCT({rng('N')},{rng('H')})", NUM1),
            ("Бортов в эксплуатации", f"=IF({UTIL}>0,ROUNDUP(B{tr + 1}/{UTIL},0),0)", "0"),
            ("Резерв, бортов", f"=IF(AND({RES}>0,B{tr + 2}>0),MAX(1,ROUNDUP(B{tr + 2}*{RES},0)),0)", "0"),
            ("Бортов всего", f"=B{tr + 2}+B{tr + 3}", "0"),
            ("Лизинг парка", f"=B{tr + 4}*{LEASE}", EUR),
            ("Результат за месяц", f"=AD{tr}-B{tr + 5}", EUR),
            ("Пассажиров в месяц", f"=SUMPRODUCT({rng('N')},{rng('O')})", NUM0),
            ("Кресло-км в месяц", f"=SUMPRODUCT({rng('N')},{rng('I')},{rng('AE')})", NUM0),
            ("Расходы всего", f"=T{tr}+SUM(W{tr}:AC{tr})+B{tr + 5}", EUR),
            ("Себестоимость пассажира, EUR", f"=IF(B{tr + 7}>0,B{tr + 9}/B{tr + 7},0)", EUR2),
            ("CASK, евроцент на кресло-км", f"=IF(B{tr + 8}>0,B{tr + 9}/B{tr + 8}*100,0)", "0.00"),
            ("RASK, евроцент на кресло-км", f"=IF(B{tr + 8}>0,S{tr}/B{tr + 8}*100,0)", "0.00"),
            ("Загрузка средняя",
             f"=IF(SUMPRODUCT({rng('N')},{rng('I')})>0,B{tr + 7}/SUMPRODUCT({rng('N')},{rng('I')}),0)", PCT),
            ("Рейсов туда-обратно в неделю", f"=SUMPRODUCT({rng('M')}/{rng('F')})", "0"),
            ("Налёт борта в эксплуатации, ч/мес", f"=IF(B{tr + 2}>0,B{tr + 1}/B{tr + 2},0)", NUM0),
        ]
        for k, (lab, fml, fmt) in enumerate(lines, start=1):
            S.cell(tr + k, 1, lab).font = F_B if k in (4, 6) else F_CALC
            c = S.cell(tr + k, 2, fml)
            c.number_format, c.font = fmt, (F_B if k in (4, 6) else F_CALC)
        S.freeze_panes = S.cell(H + 1, 4)
        tot[t["icao"]] = {"sheet": S.title, "vol": f"E{tr}", "freq": f"B{tr + 14}",
                          "n_op": f"B{tr + 2}", "spare": f"B{tr + 3}", "fleet": f"B{tr + 4}",
                          "lf": f"B{tr + 13}", "pax": f"B{tr + 7}", "rev": f"S{tr}",
                          "dist": f"T{tr}", "fuel": f"W{tr}", "mnt": f"X{tr}", "crew": f"Y{tr}",
                          "nav": f"Z{tr}", "apt": f"AA{tr}", "hnd": f"AB{tr}", "oth": f"AC{tr}",
                          "lease": f"B{tr + 5}", "res": f"B{tr + 6}", "cpp": f"B{tr + 10}",
                          "cask": f"B{tr + 11}", "rask": f"B{tr + 12}", "util": f"B{tr + 15}"}

    # ── Сводка ──────────────────────────────────────────────────────────
    V = wb.create_sheet("Сводка", 0)
    V["A1"] = "Отчёт по парку — сводка"
    V["A1"].font = F_H
    V["A2"] = ("Один объём перевозок на все типы; рейсы, борты и деньги — у каждого свои. "
               "Все числа — ссылки на листы типов и пересчитываются от «Допущений».")
    V["A2"].font = F_NOTE
    meas = [("Наш объём, пасс./мес", "vol", NUM0), ("Рейсов туда-обратно в неделю", "freq", "0"),
            ("Бортов в эксплуатации", "n_op", "0"), ("Резерв, бортов", "spare", "0"),
            ("Бортов всего", "fleet", "0"), ("Загрузка средняя", "lf", PCT),
            ("Налёт борта, ч/мес", "util", NUM0),
            ("Выручка", "rev", EUR), ("Дистрибуция", "dist", EUR), ("Топливо", "fuel", EUR),
            ("ТОиР", "mnt", EUR), ("Экипаж", "crew", EUR), ("Аэронавигация", "nav", EUR),
            ("Аэропорт", "apt", EUR), ("Обслуживание", "hnd", EUR), ("Прочее", "oth", EUR),
            ("Лизинг парка", "lease", EUR), ("Результат за месяц", "res", EUR),
            ("Себестоимость пассажира, EUR", "cpp", EUR2),
            ("CASK, евроцент", "cask", "0.00"), ("RASK, евроцент", "rask", "0.00")]
    V.cell(4, 1, "Мера").font = F_B
    V.cell(4, 1).fill = FILL_HEAD
    for j, t in enumerate(ok, start=2):
        c = V.cell(4, j, t["name"])
        c.font, c.fill, c.alignment = F_B, FILL_HEAD, WRAP
    res_row = None
    for i, (lab, k, fmt) in enumerate(meas, start=5):
        V.cell(i, 1, lab).font = F_B if k in ("res", "fleet") else F_CALC
        if k == "res":
            res_row = i
        for j, t in enumerate(ok, start=2):
            a_ = tot[t["icao"]]
            c = V.cell(i, j, f"={_q(a_['sheet'])}!{a_[k]}")
            c.number_format = fmt
            c.font = Font(name=FONT, color="008000", bold=(k in ("res", "fleet")))
    rk = 5 + len(meas)
    V.cell(rk, 1, "Место по результату").font = F_B
    last_col = L(1 + len(ok))
    for j, _ in enumerate(ok, start=2):
        c = V.cell(rk, j, f"=RANK({L(j)}{res_row},$B${res_row}:${last_col}${res_row})")
        c.font, c.number_format = F_B, "0"
    V.cell(rk + 2, 1, "Модель при выгрузке (для сверки)").font = F_NOTE
    for j, t in enumerate(ok, start=2):
        c = V.cell(rk + 2, j, t["plan"]["result"])
        c.number_format, c.font = EUR, F_COEF
    V.cell(rk + 3, 1, ("Пока «Допущения» не менялись, результат совпадает с моделью; расхождение "
                       "после правок — это ваши правки.")).font = F_NOTE
    V.column_dimensions["A"].width = 36
    for j in range(2, 2 + len(ok)):
        V.column_dimensions[L(j)].width = 18

    # ── Доступность ─────────────────────────────────────────────────────
    D = wb.create_sheet("Доступность")
    D["A1"] = "Что реально можно получить"
    D["A1"].font = F_H
    D["A2"] = ("Сведения о поставках, сертификации и ценах — не расчёт; данные на "
               f"{rep.get('availability_as_of') or '—'} из обзоров со списками источников.")
    D["A2"].font = F_NOTE
    r = 4
    for t in ok:
        av = t.get("availability")
        D.cell(r, 1, t["name"]).font = F_B
        if not av:
            D.cell(r, 2, "сведений о поставках этого типа нет").font = F_NOTE
            r += 2
            continue
        D.cell(r, 2, av.get("status")).font = F_B
        r += 1
        for pt in av.get("points") or []:
            c = D.cell(r, 2, pt)
            c.alignment, c.font = WRAP, F_CALC
            r += 1
        D.cell(r, 2, f"Цена: {av.get('price')} — {av.get('price_note')}").font = F_CALC
        r += 1
        D.cell(r, 2, f"Обзор: {av.get('review_title')}").font = F_NOTE
        r += 2
    D.column_dimensions["A"].width = 22
    D.column_dimensions["B"].width = 120

    # ── Пояснения ───────────────────────────────────────────────────────
    P = wb.create_sheet("Пояснения")
    P["A1"] = "Как устроена книга"
    P["A1"].font = F_H
    text = [
        "Расчёт — FlightCostApp (flightcost.app). Вопрос: мы перевозим такую долю нынешнего "
        "потока на этих парах — сколько рейсов, бортов и денег это стоит на каждом типе.",
        "Объём пары = поток × доля после отклика на цену. Доля после отклика = доля × "
        "цена^(−эластичность), не больше потолка. Эластичность — допущение: открытых данных "
        "об отклике доли на цену по парам нет.",
        "Рейсов туда-обратно в неделю — сколько нужно самому полному плечу пары при плановой "
        "загрузке, вверх до целого, но не меньше нижней границы. Пассажиров на рейс — объём "
        "плеча на рейсы, не больше, чем борт поднимет на этой дальности.",
        "Бортов в эксплуатации — блок-часы расписания на налёт борта, вверх до целого; резерв — "
        "доля от них, не меньше одного борта. Лизинг платится за все борта, включая резерв.",
        "Топливо = (кг при 0 пасс. + кг на пасс. × пассажиров) × цена. ТОиР и экипаж = ставка "
        "за час × блок + ставка за цикл. Сборы и обслуживание — коэффициенты ядра на рейс и на "
        "пассажира при этом типе и этих аэропортах; другой аэропорт — новый расчёт ядром.",
        "Выручка = пассажиры × рыночная цена × наша цена к рыночной × средний чек к "
        "минимальному; дистрибуция — доля выручки.",
        "Ставки с пометкой «заготовка» — параметрическая оценка от массы и кресел, не данные.",
        "Расписание проверено только суммой часов: развороты, ночёвки и окна аэропортов не "
        "проверяются.",
    ]
    for i, s in enumerate(text, start=3):
        c = P.cell(i, 1, s)
        c.alignment, c.font = WRAP, F_CALC
    P.column_dimensions["A"].width = 120

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
