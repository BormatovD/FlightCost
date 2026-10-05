
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from ..store import Fact

AERO = {"ВЗЛЕТ-ПОСАДКА", "ТРАНСПБЕЗОП", "СТОЯНКА", "АЭРОВОКЗАЛ",
        "АЭРОВОКЗАЛ(М)", "АНО АД"}
INVEST = re.compile(r"ИНВЕСТИЦИОНН\w*\s+СОСТАВЛЯЮЩ\w*\s+([\d.,]+)")
MOW = ["UUEE", "UUDD", "UUWW"]


def _codes(ctx: dict) -> dict:
    import yaml
    p = Path(ctx.get("codes_path", "data/codes/tkp_codes.yaml"))
    if not p.exists():
        # Без таблицы соответствия ни один аэропорт выгрузки не опознаётся.
        # Прежде здесь был голый FileNotFoundError, и `fca refresh` писал
        # «не разобралось» без причины: в чистой копии проекта таблицу
        # отсёк `.gitignore`, и это выглядело как сломанная выгрузка.
        raise ValueError(f"нет таблицы соответствия кодов сообщества → ИКАО ({p}): без неё "
                         f"ни один аэропорт выгрузки не опознаётся")
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not d.get("codes"):
        raise ValueError(f"в {p} нет раздела codes — таблица соответствия пуста")
    return {k.strip(): v for k, v in (d.get("codes") or {}).items()}


def _manual(ctx: dict) -> set[str]:
    d = Path(ctx.get("charges_path", "data/charges"))
    return {p.name[:4] for p in d.glob("*.json") if not p.name.startswith("_")}


def _day(v) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    return str(v)[:10]


def _conditions(service: str, terminal: str, note: str) -> dict:
    when: dict = {"operator": "national"}
    n = (note or "").upper()
    if service == "АЭРОВОКЗАЛ(М)" or "МЕЖДУНАРОДН" in n:
        when["flight"] = ["EEA", "INTL"]
    elif service == "АЭРОВОКЗАЛ" or "ВНУТРЕНН" in n:
        when["flight"] = "domestic"
    if "ЗА ИСКЛЮЧЕНИЕМ НАПРАВЛЕНИЯ САНКТ-ПЕТЕРБ" in n:
        when["other"] = {"not": MOW}
    t = (terminal or "").strip()
    if t:
        when["terminal"] = t.upper()
    return when


NEED = ("АП", "Услуга", "Ставка", "Ед.изм.", "Терминал", "Дата с",
        "Дата по", "Наименование Орг", "Индекс", "Примечание")


def read_export(blob: bytes, codes: dict) -> tuple[list[dict], set[str]]:
    """Сырая выгрузка xlsx -> записи аэронавигационных услуг с кодом ИКАО."""
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True)
    ws = wb["Перечень услуг"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip() for h in rows[0]]
    col = {h: i for i, h in enumerate(hdr)}
    for c in NEED:
        if c not in col:
            raise ValueError(f"в выгрузке нет столбца {c!r}")
    recs, unmapped = [], set()
    for r in rows[1:]:
        ap = str(r[col["АП"]] or "").strip()
        svc = str(r[col["Услуга"]] or "").strip()
        if svc not in AERO:
            continue
        if ap not in codes:
            unmapped.add(ap)
            continue
        recs.append({"ap": ap, "icao": codes[ap]["icao"], "svc": svc,
                     "rate": float(str(r[col["Ставка"]]).replace(",", ".")),
                     "unit": str(r[col["Ед.изм."]] or "").strip(),
                     "terminal": str(r[col["Терминал"]] or "").strip(),
                     "from": _day(r[col["Дата с"]]), "to": _day(r[col["Дата по"]]),
                     "org": str(r[col["Наименование Орг"]] or "").strip(),
                     "idx": str(r[col["Индекс"]] or "").strip(),
                     "note": str(r[col["Примечание"]] or "").strip()})
    return recs, unmapped


def pack(blob: bytes, codes: dict, artifact_sha: str = "") -> dict:
    """Сырая выгрузка -> упаковка для репозитория (`fca tkp-pack`)."""
    recs, unmapped = read_export(blob, codes)
    recs.sort(key=lambda x: (x["icao"], x["svc"], x["terminal"], x["from"] or ""))
    return {"source": "реестр сообщества",
            "source_url": "личные данные",
            "license": "ставки — публичные тарифы аэропортов; упаковка — CC BY 4.0 (DATA-LICENSE)",
            "packed_from_sha": artifact_sha[:16],
            "services": sorted(AERO),
            "airports": len({r["icao"] for r in recs}),
            "unmapped_codes": len(unmapped),
            "records": recs}


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    # xlsx — это zip, и начинается с «PK»; всё прочее читается как упаковка.
    if blob[:2] == b"PK":
        recs, unmapped = read_export(blob, _codes(ctx))
        form = "сырая выгрузка"
    else:
        d = json.loads(blob.decode("utf-8"))
        recs, unmapped = d["records"], set()
        form = f"упаковка, {d.get('airports', '?')} аэропортов"
    manual = _manual(ctx)
    base = dict(source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by=ctx.get("extracted_by", "parser:tkp_charges@2"),
                confidence="exact")
    doc = "реестр сообщества"

    # Группировка: аэропорт → (услуга, терминал, примечание) → редакции
    groups: dict[tuple, list[dict]] = {}
    for rec in recs:
        rec = dict(rec)
        key = (rec["icao"], rec["svc"], rec["terminal"],
               re.sub(r"\d[\d.,]*", "#", rec["note"]))
        groups.setdefault(key, []).append(rec)

    facts: list[Fact] = []
    checks: list[str] = []
    seen_ap: set[str] = set()
    for key, recs in groups.items():
        icao, svc, term, _ = key
        # редакции: поздняя «Дата с» закрывает прежнюю
        recs.sort(key=lambda x: x["from"] or "")
        for i, rec in enumerate(recs):
            if i + 1 < len(recs) and recs[i + 1]["from"]:
                nxt = dt.date.fromisoformat(recs[i + 1]["from"])
                cut = (nxt - dt.timedelta(days=1)).isoformat()
                if rec["to"] is None or rec["to"] > cut:
                    rec["to"] = cut
        if icao in manual:
            # только сверка: последняя редакция против разбора первоисточника
            cur = recs[-1]
            checks.append(f"{icao} {svc}{(' T' + term) if term else ''}: реестр "
                          f"{cur['rate']:g} {cur['unit']} с {cur['from']}"
                          + (f" — {cur['note'][:50]}" if cur["note"] else ""))
            continue
        seen_ap.add(icao)
        for rec in recs:
            facts.extend(_facts_for(icao, rec, base, doc))
    n_checked = len(manual & {k[0] for k in groups})
    ctx.setdefault("summary", []).append(
        f"реестр сообщества ({form}): заведено {len(seen_ap)} аэропортов, {len(facts)} фактов; "
        f"{n_checked} сверено с первоисточниками"
        + (f"; без кода сообщества→ИКАО: {len(unmapped)} аэропортов" if unmapped else ""))
    ctx.setdefault("checks", []).extend(checks)
    # Сверка — для человека: в ней по строке на услугу у каждого аэропорта с
    # первоисточником, в отчёт `refresh` столько не влезает. Пишется ВСЕГДА:
    # прежде она писалась, только если папка уже существовала, и в чистой
    # копии проекта пропадала молча. Где лежит — сказано в сводке.
    if checks:
        out_dir = Path(ctx.get("raw_dir", "data/raw/tkp"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "_сверка.txt"
        out.write_text("Реестр сообщества против разборов первоисточников (data/charges), "
                       "действующие редакции:\n\n" + "\n".join(checks) + "\n",
                       encoding="utf-8")
        ctx["summary"].append(f"сверка с первоисточниками, {len(checks)} строк: {out}")
    if not facts:
        raise ValueError("ни одного аэропорта с кодом и без ручного разбора — "
                         "заводить нечего")
    return facts


def _rule_fact(icao, code, rec, rule: dict, base, doc, note_extra="") -> Fact:
    payload = {k: v for k, v in rule.items() if k != "rate"}
    h = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False)
                     .encode("utf-8")).hexdigest()[:8]
    return Fact(domain="airport_charge", key=f"{icao}/{code}/{h}",
                valid_from=rec["from"], valid_to=rec["to"],
                value=float(rule["rate"]), unit=rule["base"], currency="RUB",
                value_text=json.dumps(payload, ensure_ascii=False),
                certainty="exact", source_note=rec["org"][:80],
                node="src_airport_tariff",
                note=(f"{rec['svc']} {rec['rate']:g} {rec['unit']}, редакция "
                      f"{rec['idx']}, {rec['from']} → {rec['to'] or '…'}"
                      f"{('; ' + rec['note'][:90]) if rec['note'] else ''}"
                      f"{note_extra} | {doc} | https://www.tch.ru/"),
                **base)


def _facts_for(icao: str, rec: dict, base: dict, doc: str) -> list[Fact]:
    svc, rate = rec["svc"], rec["rate"]
    when = _conditions(svc, rec["terminal"], rec["note"])
    out: list[Fact] = []
    if svc == "АНО АД":
        out.append(Fact(
            domain="terminal_rate", key=f"{icao}/national",
            valid_from=rec["from"], valid_to=rec["to"], value=rate,
            unit="per_tonne_mtow", currency="RUB",
            value_text=json.dumps({"m_div": 1.0, "m_exp": 1.0, "per": "turnaround"}),
            certainty="exact", source_note=rec["org"][:80], node="d_terminal",
            note=f"АНО АД {rate:g} РУБ-Т, {rec['from']} → {rec['to'] or '…'} | {doc} | https://www.tch.ru/",
            **base))
        return out
    if svc == "ВЗЛЕТ-ПОСАДКА":
        m = INVEST.search(rec["note"].upper())
        if m:
            inv = float(m.group(1).replace(",", "."))
            out.append(_rule_fact(icao, "landing", rec, dict(
                code="landing", base="per_tonne_mtow", events="landing",
                rate=round(rate - inv, 2), currency="RUB", when=when), base, doc,
                note_extra=f"; РАЗДЕЛЕНО: {rate:g} − инвестиционная {inv:g}, стоянка считается от части без неё"))
            out.append(_rule_fact(icao, "landing_invest", rec, dict(
                code="landing_invest", base="per_tonne_mtow", events="landing",
                rate=inv, currency="RUB", when=when), base, doc))
        else:
            out.append(_rule_fact(icao, "landing", rec, dict(
                code="landing", base="per_tonne_mtow", events="landing",
                rate=rate, currency="RUB", when=when), base, doc))
    elif svc == "ТРАНСПБЕЗОП":
        out.append(_rule_fact(icao, "security", rec, dict(
            code="security", base="per_tonne_mtow", events="landing",
            rate=rate, currency="RUB", when=when), base, doc))
    elif svc == "СТОЯНКА":
        # % от посадочного за час; льготные 3 часа — методика Минтранса № 149,
        # в реестре не отражены
        out.append(_rule_fact(icao, "parking", rec, dict(
            code="parking", base="per_hour_above", threshold=3.0, events="landing",
            rate=rate / 100.0, pct_of="landing", currency="RUB", when=when), base, doc,
            note_extra="; льготные 3 часа приняты по приказу Минтранса № 149 — в реестре не отражены"))
    elif svc in ("АЭРОВОКЗАЛ", "АЭРОВОКЗАЛ(М)"):
        out.append(_rule_fact(icao, "passenger", rec, dict(
            code="passenger", base="per_pax_per_movement", events="movement",
            rate=rate, currency="RUB", when=when), base, doc,
            note_extra="; с прибывающих, убывающих и транзитных по приказу № 149"))
    return out
