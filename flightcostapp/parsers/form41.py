"""Отчётность перевозчиков США по типам ВС (Form 41, BTS) -> факты бенчмарка.

ЗАЧЕМ. Три статьи — владение, ТОиР, экипаж — треть себестоимости рейса, и
стоят они на параметрической заготовке. M7 записал «канал ТОиР закрыт»:
ставки не публикует никто. Это неверно для одной страны. Перевозчики США
по закону (14 CFR 241) сдают в Минтранс расходы ПО ТИПУ ВС поквартально,
и BTS выкладывает их открыто: ТОиР с разбивкой на планер и двигатели,
оплату пилотов, аренду и амортизацию бортов. Это не ставка конкретного
договора, а бухгалтерия двух десятков перевозчиков — то есть полоса, в
которую заготовка должна попадать или объяснимо не попадать.

ТРИ ФАЙЛА, ОДИН ПАРСЕР. Скачиваются с TranStats руками (форма выгрузки —
ASP.NET, адреса для прямой загрузки нет) и кладутся в data/raw/form41/:

  * Schedule P-5.2 — расходы по типу (база Air Carrier Financial Reports);
  * Schedule T-2   — блок-часы, вылеты, дни в парке, кресло-мили по типу
                     (база Air Carrier Summary Data);
  * L_AIRCRAFT_TYPE — расшифровка числового кода типа.

Файл узнаётся по заголовку, а не по имени: имя у выгрузки BTS — номер
сеанса. Связываются файлы не здесь, а в `bench.py` при чтении: здесь
хранится опубликованное, как опубликовано (решение 22), — сумма по
регионам перевозчика внутри квартала, и только.

ЗАГОЛОВКИ. BTS отдаёт одни и те же поля в двух видах: в новой форме
выгрузки — `PilotFlyOps`, в предзаготовленных архивах — `PILOT_FLY_OPS`
или с кодом статьи на конце (`ACRFT_HRS_RAMPTORAMP_630`). Поле ищется по
имени без регистра и подчёркиваний ИЛИ по коду статьи — код у статьи
постоянен с 1990-х, имя менялось. Не нашлось обязательное — отказ со
списком заголовков файла: пропущенная колонка дала бы нули, неотличимые
от «расходов нет».

ЕДИНИЦЫ. В описании полей P-5.2 у ВСЕХ величин стоит «(000)», включая
часы и дни, — то есть пометка шаблонная, и верить ей вслепую нельзя.
Парсер хранит как в файле и пишет это в единицу (`as_published`);
масштаб определяет `bench.py` сверкой часов P-5.2 с часами T-2 того же
перевозчика и типа и печатает, что решил.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import defaultdict

from ..store import Fact

WHO = "parser:form41@1"

# Поле: (имена без регистра и подчёркиваний, коды статьи). Коды — номера
# счетов USofA для P-5.2 и номера строк Z для T-2.
P52_FIELDS = {
    "pilots":       ({"PILOTFLYOPS"}, {"51230"}),
    "oth_flight":   ({"OTHFLTFLYOPS"}, {"51240"}),
    "trainees":     ({"TRAINFLYOPS"}, {"51281"}),
    "pers_exp":     ({"PERSEXPFLYOPS"}, {"51360"}),
    "benefits":     ({"BENEFITSFLYOPS"}, {"51570"}),
    "payroll_tax":  ({"PAYTAXFLYOPS"}, {"51680"}),
    "fuel":         ({"FUELFLYOPS"}, {"51451"}),
    "rentals":      ({"RENTALFLYOPS"}, {"51470"}),
    "insurance":    ({"INSFLYOPS"}, {"51551"}),
    "tot_fly_ops":  ({"TOTFLYOPS"}, {"51990"}),
    "maint_direct": ({"TOTDIRMAINT"}, {"52780"}),
    "maint_burden": ({"APMTBURDEN"}, {"52796"}),
    "maint_total":  ({"TOTFLTMAINTMEMO"}, {"52990"}),
    # Итог амортизации (70756) в настоящих выгрузках 2025 года пуст почти
    # везде — в 1 523 строках из 1 547. Слагаемые заполнены, и где итог
    # есть, он совпадает с их суммой до цента. Поэтому хранятся и итог, и
    # слагаемые, а `bench.py` берёт итог, только если он подан.
    "depreciation": ({"OTHFLTEQUIPDEPGRPI"}, {"70756"}),
    "dep_airframe": ({"AIRFRAMEDEP"}, {"70751"}),
    "dep_engine":   ({"ENGINEDEP"}, {"70752"}),
    "dep_af_parts": ({"PARTSDEP"}, {"70753"}),
    "dep_eng_parts": ({"ENGPARTSDEP"}, {"70754"}),
    "dep_other":    ({"OTHFLTEQUIPDEP"}, {"70755"}),
    "amort_leases": ({"FLTEQUIPAEXP"}, {"70761"}),
    "doc_total":    ({"TOTAIROPEXPENSES"}, {"70989"}),
    "air_hours":    ({"TOTALAIRHOURS"}, {"6500", "Z6500"}),
    "days_assigned": ({"AIRDAYSASSIGN"}, {"8100", "Z8100"}),
}
P52_REQUIRED = ("pilots", "maint_total", "rentals", "air_hours")

T2_FIELDS = {
    "departures":  ({"REVDEPPERFORMED", "REVACRFTDEPPERF", "DEPARTURESPERFORMED",
                     "REVAIRCRAFTDEPARTURESPERFORMED"}, {"510"}),
    "ramp_hours":  ({"AIRHOURSRAMP", "ACRFTHRSRAMPTORAMP", "AIRCRAFTHOURSRAMPTORAMP"}, {"630"}),
    "air_hours":   ({"AIRHOURS", "HOURSAIRBORNE", "TOTALAIRHOURS"}, {"650"}),
    "days_assigned": ({"AIRDAYSEQUIP", "ACRFTDAYSASSIGNED", "AIRCRAFTDAYSASSIGNED",
                       "AIRCRAFTDAYS"}, {"810"}),
    "asm":         ({"AVAILSEATMILES", "AVLSEATMILES"}, {"320"}),
    "air_miles":   ({"REVAIRMILES", "REVACRFTMILESFLOWN", "REVAIRCRAFTMILESFLOWN"}, {"410"}),
    "fuel_gal":    ({"AIRCRAFTFUEL", "AIRCRAFTFUELS"}, {"921"}),
}
T2_REQUIRED = ("departures", "ramp_hours", "days_assigned")

ID_FIELDS = {
    "year":    {"YEAR"},
    "quarter": {"QUARTER"},
    "month":   {"MONTH"},
    "carrier": {"UNIQUECARRIER"},
    "carrier_alt": {"CARRIER"},
    "name":    {"UNIQUECARRIERNAME", "CARRIERNAME"},
    "type":    {"AIRCRAFTTYPE"},
    "config":  {"AIRCRAFTCONFIG"},
    "svc":     {"SVCCLASS", "SERVICECLASS"},
    "group":   {"CARRIERGROUPNEW", "CARRIERGROUP"},
}

_SPLIT = re.compile(r"^(.*?)(?:_(Z?\d{3,5}))?$")


def _norm(h: str) -> tuple[str, str]:
    """Заголовок -> (имя без регистра и разделителей, код статьи или '')."""
    h = (h or "").strip().strip('"').lstrip("﻿")
    m = _SPLIT.match(h.upper())
    name, code = (m.group(1), m.group(2) or "") if m else (h.upper(), "")
    return re.sub(r"[^A-Z0-9]", "", name), code.lstrip("Z")


def _columns(header, spec):
    """Сопоставление полей спецификации колонкам файла."""
    normed = [_norm(h) for h in header]
    out = {}
    for field, (names, codes) in spec.items():
        codes = {c.lstrip("Z") for c in codes}
        for i, (nm, code) in enumerate(normed):
            if nm in names or (code and code in codes):
                out[field] = i
                break
    return out


def _num(v) -> float:
    v = (v or "").strip().replace(",", "")
    if not v:
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def _rows(blob: bytes):
    """CSV или zip с одним CSV внутри (так BTS отдаёт выгрузку)."""
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("в архиве нет CSV")
            blob = z.read(names[0])
    text = blob.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def _kind(header) -> str:
    names = {_norm(h)[0] for h in header}
    codes = {_norm(h)[1] for h in header}
    if {"CODE", "DESCRIPTION"} <= names and len(header) <= 3:
        return "types"
    if _columns(header, {k: P52_FIELDS[k] for k in ("pilots", "maint_total")}).keys() >= {"pilots", "maint_total"}:
        return "p52"
    if _columns(header, {k: T2_FIELDS[k] for k in ("ramp_hours",)}) and ("AIRCRAFTTYPE" in names):
        return "t2"
    raise ValueError(
        "файл не узнан ни как Schedule P-5.2, ни как T-2, ни как L_AIRCRAFT_TYPE. "
        f"Заголовки: {', '.join(h for h in header[:20])}"
        + (f" …ещё {len(header) - 20}" if len(header) > 20 else ""))


def _quarter_end(year: int, q: int) -> str:
    return f"{year}-{('03-31', '06-30', '09-30', '12-31')[q - 1]}"


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    rows = _rows(blob)
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("файл пуст")
    header, body = rows[0], rows[1:]
    kind = _kind(header)
    if kind == "types":
        return _types(header, body, ctx)
    return _schedule(kind, header, body, ctx)


def _types(header, body, ctx) -> list[Fact]:
    cols = {_norm(h)[0]: i for i, h in enumerate(header)}
    ci, di = cols["CODE"], cols["DESCRIPTION"]
    facts = []
    for r in body:
        if len(r) <= max(ci, di):
            continue
        code, desc = r[ci].strip().strip('"'), r[di].strip().strip('"')
        if not code or not desc:
            continue
        facts.append(Fact(
            domain="fleet_benchmark", key=f"F41/TYPES/{code.lstrip('0') or '0'}",
            valid_from=ctx.get("today") or "", value=None, unit="text",
            value_text=desc, source_id=ctx["source_id"],
            artifact_sha=ctx.get("sha"), extracted_by=WHO, confidence="exact",
            note="L_AIRCRAFT_TYPE, BTS"))
    ctx.setdefault("summary", []).append(f"L_AIRCRAFT_TYPE: кодов {len(facts)}")
    ctx.setdefault("parsed_prefixes", []).append("F41/TYPES")
    return facts


def _schedule(kind, header, body, ctx) -> list[Fact]:
    spec, required = (P52_FIELDS, P52_REQUIRED) if kind == "p52" else (T2_FIELDS, T2_REQUIRED)
    cols = _columns(header, spec)
    ids = _columns(header, {k: (v, set()) for k, v in ID_FIELDS.items()})
    missing = [f for f in required if f not in cols]
    if kind == "p52" and "depreciation" not in cols and "dep_airframe" not in cols:
        missing.append("depreciation (итог 70756 или слагаемые 70751–70755)")
    if "carrier" not in ids and "carrier_alt" in ids:
        ids["carrier"] = ids["carrier_alt"]
    missing += [f for f in ("year", "carrier", "type") if f not in ids]
    if "quarter" not in ids and "month" not in ids:
        missing.append("quarter")
    if missing:
        raise ValueError(
            f"{kind.upper()}: нет колонок {', '.join(missing)}. Заголовки файла: "
            f"{', '.join(header[:40])}")

    # Класс обслуживания у T-2: Z = K + V, K = F + G, V = L+N+P+R. Сложить
    # всё подряд — удвоить. Берётся Z, если перевозчик его подал; иначе
    # K и V; иначе базовые классы.
    svc_i = ids.get("svc")
    rank = {"Z": 0, "K": 1, "V": 1}

    acc = defaultdict(lambda: defaultdict(float))
    svc_of: dict[tuple, int] = {}
    names: dict[str, str] = {}
    skipped_cfg = 0
    for r in body:
        def g(i):
            return r[i] if i is not None and i < len(r) else ""
        if "config" in ids and g(ids["config"]).strip() not in ("1", "01", ""):
            skipped_cfg += 1          # 1 — пассажирская компоновка; грузовики и комби мимо
            continue
        try:
            year = int(float(g(ids["year"])))
        except ValueError:
            continue
        if "quarter" in ids and g(ids["quarter"]).strip():
            q = int(float(g(ids["quarter"])))
        else:
            q = (int(float(g(ids["month"]))) - 1) // 3 + 1
        car = g(ids["carrier"]).strip().upper()
        typ = g(ids["type"]).strip().lstrip("0") or "0"
        if not car:
            continue
        if "name" in ids:
            names[car] = g(ids["name"]).strip()
        key = (year, q, car, typ)
        if svc_i is not None and kind == "t2":
            s = g(svc_i).strip().upper()
            level = rank.get(s, 2)
            best = svc_of.get(key)
            if best is not None and level > best:
                continue                     # есть сводный класс — базовые не нужны
            if best is not None and level < best:
                acc[key] = defaultdict(float)  # пришёл сводный — базовые выбросить
            svc_of[key] = level
            if level == 1 and best == 1:
                pass                         # K и V складываются между собой
        for f, i in cols.items():
            acc[key][f] += _num(g(i))

    tag = "P52" if kind == "p52" else "T2"
    facts = []
    years = set()
    for (year, q, car, typ), vals in sorted(acc.items()):
        years.add(year)
        for f, v in vals.items():
            unit = ("as_published" if kind == "p52" else
                    {"departures": "flights", "ramp_hours": "h", "air_hours": "h",
                     "days_assigned": "aircraft_days", "asm": "seat_miles",
                     "air_miles": "miles", "fuel_gal": "gal_us"}[f])
            facts.append(Fact(
                domain="fleet_benchmark",
                key=f"F41/{tag}/{year}Q{q}/{car}/{typ}/{f}",
                valid_from=_quarter_end(year, q), value=float(v), unit=unit,
                currency="USD" if kind == "p52" and f not in ("air_hours", "days_assigned") else None,
                value_text=json.dumps({"carrier_name": names.get(car, "")}, ensure_ascii=False),
                source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by=WHO, confidence="exact", node="src_form41",
                note=f"BTS Form 41 Schedule {'P-5.2' if kind == 'p52' else 'T-2'}, "
                     f"сумма по регионам перевозчика"))
    ctx.setdefault("parsed_prefixes", []).extend(f"F41/{tag}/{y}Q{q}" for y in sorted(years)
                                                  for q in (1, 2, 3, 4))
    ctx.setdefault("summary", []).append(
        f"{'P-5.2' if kind == 'p52' else 'T-2'}: годы {', '.join(map(str, sorted(years)))}, "
        f"перевозчиков {len({k[2] for k in acc})}, типов {len({k[3] for k in acc})}, "
        f"строк перевозчик×тип×квартал {len(acc)}"
        + (f"; не пассажирских строк пропущено {skipped_cfg}" if skipped_cfg else ""))
    return facts
