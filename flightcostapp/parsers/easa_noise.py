"""Сертифицированный шум типов ВС: база EASA для реактивных самолётов.

ЗАЧЕМ. Аэропорты, считающие шумовой сбор по сертификату (Гатвик, Хитроу,
Нюрнберг, Нарита), раскладывают типы по запасу к пределам главы 3
Приложения 16. Запас — свойство типа, одно на весь мир, и заводить его в
каждый тариф значило бы повторить одно число сорок раз. Здесь он заводится
один раз, в домен `aircraft`, из публикации с издателем и редакцией.

ЧЕГО ЭТО НЕ ЗАМЕНЯЕТ. Франкфурт, Мюнхен, Гамбург, Ганновер раскладывают по
СОБСТВЕННЫМ измерениям на своих станциях (DIN 45643), а сертификат берут
только для нового типа, пока измерений нет. Для них эти числа — не вход,
а сверка: выделенная строка, если категория по сертификату далеко от
названной документом.

ИСТОЧНИК. EASA, «Jet aeroplanes noise database», xlsx. Одна строка — одна
сертифицированная конфигурация: модель, двигатель, масса, уровни в трёх
точках, глава. У типа их десятки, и выбирается ОДНА: с двигателем из
домена `aircraft` и массой, ближайшей к MTOW типа. Выбор называется в
примечании факта — иначе нельзя проверить, та ли это строка.

ЗАГОЛОВКИ ИЩУТСЯ ПО НАЗНАЧЕНИЮ. Точной раскладки столбцов в этой редакции
мы не видели; файл переиздаётся два раза в год. Разбор находит столбцы по
словам в заголовке и, если чего-то не нашёл, отказывает со списком того,
что в файле есть, — как выгрузка цен без колонки валюты.
"""

from __future__ import annotations

import io
import re

from ..store import Fact

# Тип ИКАО -> образец модели в строке EASA. Список, а не вывод: «737-8» и
# «737-800» — разные самолёты, и отличает их только граница после цифры.
# Для каждого образца проверено, что соседний не проходит (тест).
MODEL_RX = {
    "A318": r"\bA318-1\d\d(?![0-9A-Z])",
    "A319": r"\bA319-1\d\d(?![0-9A-Z])",
    "A19N": r"\bA319-1\d\dN\b",
    "A320": r"\bA320-2\d\d(?![0-9A-Z])",
    "A20N": r"\bA320-2\d\dN\b",
    "A321": r"\bA321-[12]\d\d(?![0-9A-Z])",
    "A21N": r"\bA321-2\d\dN[A-Z]?\b",
    "A332": r"\bA330-2\d\d(?![0-9A-Z])",
    "A333": r"\bA330-3\d\d(?![0-9A-Z])",
    "A343": r"\bA340-3\d\d(?![0-9A-Z])",
    "A359": r"\bA350-941\b",
    "A388": r"\bA380-8\d\d\b",
    "B37M": r"\b737-7\b",
    "B38M": r"\b737-8(200)?\b",
    "B39M": r"\b737-9\b",
    "B3XM": r"\b737-10\b",
    "B734": r"\b737-4\d\d\b",
    "B737": r"\b737-7\d\d\b",
    "B738": r"\b737-8\d\d\b",
    "B739": r"\b737-9\d\d(ER)?\b",
    "B744": r"\b747-4\d\d\b",
    "B748": r"\b747-8[IF]?\b",
    "B752": r"\b757-2\d\d\b",
    "B763": r"\b767-3\d\d(ER)?\b",
    "B772": r"\b777-2\d\d(ER|LR)?\b",
    "B773": r"\b777-3\d\d\b",
    "B77W": r"\b777-3\d\dER\b",
    "B788": r"\b787-8\b",
    "B789": r"\b787-9\b",
    "CRJ9": r"\bCL-600-2D24\b",
    "E145": r"\bEMB-145",
    "E170": r"\b(ERJ ?170-100|EMB-170)",
    "E75L": r"\bERJ ?170-200",
    "E190": r"\b(ERJ ?190-100|EMB-190)",
    "E195": r"\b(ERJ ?190-200|EMB-195)",
}

# ШАПКА В НЕСКОЛЬКО СТРОК. У EASA она такая:
#     NOISE LEVELS (EPNdB)                     ← группа, объединённая ячейка
#        LATERAL   |  FLYOVER  |  APPROACH       ← точка, объединённая ячейка
#     LEVEL LIMIT MARGIN | LEVEL LIMIT MARGIN …
# и `NUMBER` / `OF ENGINES` разбито на две строки. Первая версия искала
# столбцы в ОДНОЙ строке и, встретив такую шапку на настоящем файле,
# нашла уровни и массу, но не нашла ни числа двигателей, ни двигателя, ни
# пределов: четырёхдвигательные типы получили предел пролёта для двух
# двигателей, а строка выбиралась только по массе. Тест на выдуманных
# заголовках этого не поймал бы никогда.
#
# Поэтому имя столбца — СОСТАВНОЕ: строки шапки склеиваются через « | »,
# объединённые ячейки протягиваются вправо до следующей непустой.
COLS = {
    "mtom":     lambda h: "mtom" in h or ("take" in h and "off" in h and "mass" in h),
    "lateral":  lambda h: "lateral" in h and "level" in h,
    "flyover":  lambda h: "flyover" in h and "level" in h,
    "approach": lambda h: "approach" in h and "level" in h,
    "lim_lat":  lambda h: "lateral" in h and "limit" in h,
    "lim_fly":  lambda h: "flyover" in h and "limit" in h,
    "lim_app":  lambda h: "approach" in h and "limit" in h,
    "mg_lat":   lambda h: "lateral" in h and "margin" in h,
    "mg_fly":   lambda h: "flyover" in h and "margin" in h,
    "mg_app":   lambda h: "approach" in h and "margin" in h,
    "mg_cum":   lambda h: "cumulative" in h and "margin" in h,
    "chapter":  lambda h: "chapter" in h and "cumulative" not in h,
    # «NUMBER / OF ENGINES» — а не «ENGINE | MODIFICATION | Number»,
    # номер модификации двигателя, который первая версия приняла за число.
    "engines":  lambda h: "of engines" in h or "number of engines" in h,
    "engine":   lambda h: ("engine" in h and ("designation" in h or "model" in h)
                           and "holder" not in h and "number" not in h),
    "tcdsn":    lambda h: "tcdsn" in h,
}
REQUIRED = ("mtom", "lateral", "approach", "flyover")
# Описание модели — только из столбцов планера: тип и вариант. Столбцы
# двигателя в описание не идут — у них свои поля.
MODEL_COL = lambda h: ("airframe" in h and ("type" in h or "variant" in h)
                       and "holder" not in h)


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ".").strip())
    except ValueError:
        return None


def _chapter(v) -> int | None:
    m = re.search(r"(\d{1,2})", str(v or ""))
    if not m:
        return None
    n = int(m.group(1))
    return n if n in (2, 3, 4, 5, 14) else None


def _composite(rows: list[tuple], start: int, depth: int) -> list[str]:
    """Составные имена столбцов из `depth` строк шапки, начиная со `start`."""
    block = rows[start:start + depth]
    width = max(len(r) for r in block)
    out = [[] for _ in range(width)]
    for k, r in enumerate(block):
        cells = [_norm(c) for c in r] + [""] * (width - len(r))
        # Протяжка вправо — во всех строках, кроме нижней: верхние строки
        # шапки — группы и точки замера («LATERAL» над тремя столбцами
        # LEVEL / LIMIT / MARGIN), их ячейки объединены, и значение стоит
        # только в левой. Нижняя строка — листья, у каждого столбца своё.
        leaf = k == len(block) - 1
        last = ""
        for j, c in enumerate(cells):
            if c:
                last = c
            elif not leaf and last:
                c = last
            if c:
                out[j].append(c)
    return [" | ".join(parts) for parts in out]


def _find_header(rows: list[tuple]) -> tuple[int, dict, list[int]]:
    for start in range(min(20, len(rows))):
        for depth in (4, 3, 2, 1):
            heads = _composite(rows, start, depth)
            found = {}
            for key, test in COLS.items():
                for j, h in enumerate(heads):
                    if h and j not in found.values() and test(h):
                        found[key] = j
                        break
            if all(k in found for k in REQUIRED):
                model = [j for j, h in enumerate(heads) if h and MODEL_COL(h)]
                return start + depth - 1, found, model
    shown = [" | ".join(_norm(c) for c in r if c)[:300] for r in rows[:6]]
    raise ValueError("в файле не найдены столбцы " + ", ".join(REQUIRED)
                     + ". Первые строки:\n  " + "\n  ".join(shown))


def _target(icao: str) -> tuple[float | None, str]:
    """MTOW и двигатель типа — для выбора строки. Из openap, как и сама
    запись типа: парсер хранилища не видит, а ключ выбора должен
    совпадать с тем, что лежит в домене."""
    try:
        from openap import prop
        a = prop.aircraft(icao.lower())
        return a["mtow"] / 1000.0, str(a.get("engine", {}).get("default") or "")
    except Exception:                                   # noqa: BLE001
        return None, ""


def _eng_key(s: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(s).upper())


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    import openpyxl

    from ..categories import chapter3_limits, noise_margins

    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    ws = max(wb.worksheets, key=lambda w: w.max_row or 0)
    rows = list(ws.iter_rows(values_only=True))
    hi, col, model_cols = _find_header(rows)
    data = rows[hi + 1:]

    day = ctx.get("today") or ""
    facts: list[Fact] = []
    report: list[str] = []
    for icao, rx in MODEL_RX.items():
        pat = re.compile(rx)
        cands = []
        for r in data:
            text = " ".join(str(r[j]) for j in model_cols if j < len(r) and r[j]).upper()
            if not pat.search(text):
                continue
            lv = {p: _num(r[col[p]]) for p in ("lateral", "approach", "flyover")}
            m = _num(r[col["mtom"]])
            if m is None or any(v is None for v in lv.values()):
                continue
            m_t = m / 1000.0 if m > 1000 else m          # кг или тонны
            cands.append((r, text, lv, m_t))
        if not cands:
            report.append(f"{icao}: строк не найдено")
            continue
        mtow, eng = _target(icao)
        ek = _eng_key(eng)
        same_eng = [c for c in cands if "engine" in col and ek and
                    (_eng_key(c[0][col["engine"]]).startswith(ek[:8]) or
                     ek.startswith(_eng_key(c[0][col["engine"]])[:8] or "#"))]
        pool = same_eng or cands
        best = min(pool, key=lambda c: abs(c[3] - mtow) if mtow else 0.0)
        r, text, lv, m_t = best
        if "engines" not in col:
            raise ValueError("в файле не найден столбец числа двигателей — без него "
                             "предел пролёта главы 3 для четырёхдвигательных неверен")
        n_eng = int(_num(r[col["engines"]]) or 0)
        if n_eng < 1:
            continue
        chap = _chapter(r[col["chapter"]]) if "chapter" in col else None
        mg = noise_margins(lv, m_t, n_eng)

        # Пределы публикует издатель. Наша формула главы 3 — вторая
        # реализация той же величины и допустима только как перекрёстная
        # проверка (решение 102). Пределы в файле — по главе, к которой
        # отнесён тип: для главы 3 они должны совпасть с нашими, для глав
        # 4 и 14 файл даёт те же пределы главы 3 как базу запаса.
        if all(k in col for k in ("lim_lat", "lim_app", "lim_fly")):
            ours = chapter3_limits(m_t, n_eng)
            theirs = {"lateral": _num(r[col["lim_lat"]]), "approach": _num(r[col["lim_app"]]),
                      "flyover": _num(r[col["lim_fly"]])}
            off = {p: round(ours[p] - v, 2) for p, v in theirs.items()
                   if v is not None and abs(ours[p] - v) > 0.15}
            if off:
                report.append(f"{icao}: предел главы 3 по нашей формуле расходится "
                              f"с пределом в файле {off}")
        published_cum = _num(r[col["mg_cum"]]) if "mg_cum" in col else None
        if published_cum is not None and abs(published_cum - mg["noise_margin_cum"]) > 0.3:
            report.append(f"{icao}: кумулятивный запас по нашей формуле "
                          f"{mg['noise_margin_cum']:.1f}, в файле {published_cum:.1f}")

        why = (f"строка: {text[:80]}; двигатель "
               f"{r[col['engine']] if 'engine' in col else '?'}"
               f"{'' if same_eng else ' (двигатель типа не найден среди строк — взята ближайшая по массе)'}"
               f"; масса {m_t:.1f} т{f' против MTOW {mtow:.1f} т' if mtow else ''}"
               f"; кандидатов {len(cands)}"
               f"{'; TCDSN ' + str(r[col['tcdsn']]) if 'tcdsn' in col else ''}")
        base = dict(domain="aircraft", valid_from=day, source_id=ctx["source_id"],
                    artifact_sha=ctx.get("sha"), extracted_by="parser:easa_noise@1",
                    node=ctx.get("node") or "src_easa_noise", note=why)
        for key, v, unit in (
                ("noise_lateral_epndb", lv["lateral"], "EPNdB"),
                ("noise_approach_epndb", lv["approach"], "EPNdB"),
                ("noise_flyover_epndb", lv["flyover"], "EPNdB"),
                ("noise_mtom_t", m_t, "т")):
            facts.append(Fact(key=f"{icao}/{key}", value=float(v), unit=unit,
                              confidence="exact", **base))
        if chap:
            facts.append(Fact(key=f"{icao}/noise_chapter", value=float(chap),
                              unit="глава", confidence="exact", **base))
        # Запас — выведенная величина; хранится ради витрины и сверки, а
        # категории считают его заново из уровней (categories.aircraft_props).
        facts.append(Fact(key=f"{icao}/engine_count_cert", value=float(n_eng),
                          unit="шт", confidence="exact", **base))
        # Кумулятивный запас: опубликованный, если файл его даёт, иначе
        # наш. Храним ради витрины и сверки; категории считают запас из
        # уровней сами (categories.aircraft_props), и расхождение двух
        # путей видно в отчёте разбора.
        cum = published_cum if published_cum is not None else mg["noise_margin_cum"]
        facts.append(Fact(key=f"{icao}/noise_margin_cum_epndb",
                          value=round(cum, 2), unit="EPNdB",
                          confidence="exact" if published_cum is not None else "derived",
                          **base))
        report.append(f"{icao}: {len(cands)} строк, взята {m_t:.1f} т, "
                      f"запас {mg['noise_margin_cum']:.1f}"
                      f"{', глава ' + str(chap) if chap else ''}")
    ctx.setdefault("summary", []).extend(report)
    # Порог «найдено слишком мало» — защита от файла, к которому образцы
    # моделей не подходят. Выдержка для тестов законно меньше, поэтому
    # порог задаётся контекстом; в реестре он по умолчанию двадцать.
    if len({f.key.split('/')[0] for f in facts}) < int(ctx.get("min_types", 20)):
        raise ValueError("найдено меньше двадцати типов — образцы моделей не "
                         "подходят к этой редакции файла:\n  " + "\n  ".join(report))
    return facts
