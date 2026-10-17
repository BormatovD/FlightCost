"""Свои типы ВС: JSON из каталога -> факты домена `aircraft`.

Зачем отдельный источник, а не правка openap. Библиотека покрывает 37
типов, а сравнивать хочется и то, чего в ней нет: Ту-214, будущий
Boeing NMA, региональные. Паспортные величины таких типов публикуются —
массы, баки, размах, кресла, крейсер — и заводятся сюда как факты со
ссылкой на издателя. Расход НЕ заводится числом: у типа либо есть свой
вычислитель (openap), либо назван аналог с якорем — ярус 4 (решения 94,
105, 106). Без якоря тип отвечает «нельзя».

Файл — один тип, по образцу тарифов: те же `source`, `source_url`,
`publisher`, `checked_at`, та же приёмка через `fca review`. Ключ типа —
обозначатель ИКАО (`T214`); у типа без обозначателя — `USER:<имя>`, чтобы
не выглядеть ИКАО (по аналогии с решением 103). Регистр — верхний, как у
всех кодов; в файле можно писать как угодно.

    {
     "icao": "T214",
     "name": "Tupolev Tu-214",
     "valid_from": "2026-09-19",
     "source": "...", "source_url": "...", "publisher": "...",
     "checked_at": "2026-09-19",
     "fields": {"mtow_t": 110.75, "oew_t": 59.0, "fuel_capacity_t": 35.7,
                "seats_max": 210, "seats_typical": 176, "span_m": 41.8,
                "length_m": 46.1, "cruise_mach": 0.80, "cruise_alt_m": 11000,
                "engine_count": 2, "mlw_t": 93.0},
     "engine": "PS-90A",
     "engine_mount": "wing",          # необязательно: wing | rear, для силуэта
     "fleet": {"lease_eur_month": 250000, "maint_eur_per_fh": 900},  # необязательно
     "fleet_source": "предложение лизингодателя от …, или «моё допущение»",
     "burn": {"analog": "B752",
              "anchor_kg_per_h": 3200, "anchor_mass_t": 95,
              "anchor_source": "...", "note": "..."},
     "certainty": "exact"
    }
"""

from __future__ import annotations

import json

from ..store import CERTAINTY, Fact

# Поля физики — те же имена и единицы, что пишет парсер openap: один
# домен, одни ключи, иначе `load_aircraft` читал бы два словаря.
FIELDS = {
    "mtow_t": "т", "oew_t": "т", "mlw_t": "т", "fuel_capacity_t": "т",
    "seats_max": "шт", "seats_typical": "шт", "span_m": "м", "length_m": "м",
    "cruise_mach": "M", "cruise_alt_m": "м", "engine_count": "шт",
    # Сертифицированный шум — для типов, которых нет в базе EASA (Ту-214):
    # без него категории аэропортов, считающих по сертификату, для типа не
    # определяются и честно остаются пустыми.
    "noise_lateral_epndb": "EPNdB", "noise_approach_epndb": "EPNdB",
    "noise_flyover_epndb": "EPNdB", "noise_mtom_t": "т", "noise_chapter": "глава",
    # Только для силуэта в выборе типа (решение 188); в расчёт не входят.
    # Без них силуэт оценивает стреловидность по крейсерскому числу M.
    "sweep_deg": "°", "fuselage_width_m": "м",
}
MOUNTS = ("wing", "rear")
# Вид данных: official — серийный тип по документу производителя или
# сертификату; announced — объявлено производителем для типа в испытаниях
# или разработке; projected — оценка прессы/аналитиков, производитель не
# подтверждал. Статус программы — как в обзорах.
CATALOG = "aircraft_catalog"
DATA_KINDS = ("official", "announced", "projected")
STATUSES = ("in_service", "certifying", "flight_test", "development", "concept",
            "paused", "ended")
# Ставки эксплуатации, названные автором типа (решение 190). Не паспорт,
# а допущение автора — поэтому отдельным блоком `fleet`, в факт
# `<тип>/fleet_<поле>` домена `aircraft`: так они живут и снимаются вместе
# с типом. Любое поле можно не задавать — останется заготовка от массы.
FLEET = {"lease_eur_month": "EUR/мес", "monthly_hours": "ч/мес",
         "maint_eur_per_fh": "EUR/ч", "maint_eur_per_fc": "EUR/цикл",
         "crew_eur_per_fh": "EUR/ч", "crew_eur_per_fc": "EUR/цикл"}
REQUIRED = ("mtow_t", "oew_t", "fuel_capacity_t", "seats_max", "span_m",
            "cruise_mach", "cruise_alt_m")


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    docs = _split(blob)
    facts: list[Fact] = []
    ok = 0
    for d in docs:
        name = d.get("icao") or "<без кода>"
        try:
            facts += _one(d, ctx)
            ok += 1
        except Exception as e:                                    # noqa: BLE001
            ctx.setdefault("rejected", []).append(f"{name}: {type(e).__name__}: {e}")
    ctx["parsed_docs"], ctx["total_docs"] = ok, len(docs)
    ctx.setdefault("summary", []).append(f"разобрано {ok} из {len(docs)} типов")
    if ok == 0:
        raise ValueError("ни один тип не разобран:\n  "
                         + "\n  ".join(ctx.get("rejected", [])))
    return facts


def _split(blob: bytes) -> list[dict]:
    text = blob.decode("utf-8").strip()
    try:
        one = json.loads(text)
        return one if isinstance(one, list) else [one]
    except json.JSONDecodeError:
        pass
    out, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(json.loads(text[start:i + 1]))
                start = None
    if not out:
        raise ValueError("не удалось разобрать ни одного документа")
    return out


def _one(d: dict, ctx: dict) -> list[Fact]:
    icao = str(d["icao"]).strip()
    if not icao:
        raise ValueError("нет поля icao")
    # Ключ обязан либо быть обозначателем ИКАО (2–4 знака, буквы и цифры),
    # либо не выглядеть как он. `NMA` прошёл бы за обозначатель, которого
    # нет, и расчёт однажды спросил бы у openap тип NMA.
    up = icao.upper()
    if not (up.startswith("USER:") or (2 <= len(up) <= 4 and up.isalnum())):
        raise ValueError(f"ключ {icao!r}: обозначатель ИКАО или user:<имя>")
    # Ключ целиком в верхнем регистре: `load_aircraft` и сравнение
    # приводят код к верхнему, и ключ `user:…` строчными они не находили.
    # Двоеточие уже не даёт ему выглядеть обозначателем ИКАО.
    key_ac = up
    for req in ("valid_from", "source", "source_url", "publisher", "checked_at"):
        if not d.get(req):
            raise ValueError(f"{icao}: нет поля {req} — число без издателя не заводится")
    certainty = d.get("certainty", "exact")
    if certainty not in CERTAINTY:
        raise ValueError(f"достоверность вне словаря: {certainty!r}")
    # Хранилище отвергнет неточность без цены ошибки и адресата (решения
    # 75, 76) — но отвергнет при ПРИЁМКЕ, трассировкой из commit_facts.
    # Гейт обязан сказать это раньше и словами.
    if certainty != "exact" and (d.get("error_cost") is None or not d.get("confirm_by")):
        raise ValueError(f"{icao}: certainty={certainty} требует error_cost (число, EUR на "
                         f"эталонном обороте) и confirm_by (кто подтвердит). Если числа — "
                         f"ваше допущение, а не прочтение документа, ставьте exact и "
                         f"пишите это в source")
    fields = d.get("fields") or {}
    missing = [k for k in REQUIRED if fields.get(k) is None]
    # Каталог типов (решение 223) держит и карточки неполных типов: у C929
    # или 777-9 масса пустого не опубликована, но тип нужен в обзоре. Такой
    # тип заводится с перечнем пробелов и в расчёт не выбирается; свой тип
    # владельца по-прежнему обязан быть полным — он заводится для расчёта.
    card_only = ctx.get("source_id") == CATALOG
    if missing and not card_only:
        raise ValueError(f"{icao}: нет полей {', '.join(missing)}")
    unknown = sorted(set(fields) - set(FIELDS))
    if unknown:
        raise ValueError(f"{icao}: неизвестные поля {', '.join(unknown)}; "
                         f"допустимы {', '.join(FIELDS)}")
    if (fields.get("oew_t") is not None and fields.get("mtow_t") is not None
            and float(fields["oew_t"]) >= float(fields["mtow_t"])):
        raise ValueError(f"{icao}: масса пустого не меньше взлётной")

    base = dict(domain="aircraft", valid_from=d["valid_from"],
                source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by=ctx.get("extracted_by", "parser:aircraft_user@1"),
                certainty=certainty, node=d.get("map_node") or ctx.get("node"),
                error_cost=d.get("error_cost"), confirm_by=d.get("confirm_by"),
                # Имя типа — в note, как у парсера openap: витрина читает его оттуда.
                note=d.get("name") or icao,
                source_note=f"{d['source']} | {d['publisher']} | {d['source_url']}")
    facts = [Fact(key=f"{key_ac}/{k}", value=float(v), unit=FIELDS[k],
                  confidence="exact", **base) for k, v in fields.items() if v is not None]
    if missing:
        facts.append(Fact(key=f"{key_ac}/calc_gaps", value_text=", ".join(missing),
                          unit="поля", confidence="exact", **base))
    assumed = (d.get("meta") or {}).get("assumed") or {}
    if assumed:
        facts.append(Fact(key=f"{key_ac}/assumed", value_text="; ".join(
            f"{k}: {v}" for k, v in assumed.items()), unit="текст", confidence="exact", **base))
    fleet = {k: v for k, v in (d.get("fleet") or {}).items() if v not in ("", None)}
    bad = sorted(set(fleet) - set(FLEET))
    if bad:
        raise ValueError(f"{icao}: в fleet неизвестные поля {', '.join(bad)}; "
                         f"допустимы {', '.join(FLEET)}")
    if fleet and not d.get("fleet_source"):
        raise ValueError(f"{icao}: ставки флота без fleet_source — откуда числа "
                         f"(договор, предложение лизингодателя, «моё допущение»)")
    for k, v in fleet.items():
        if float(v) < 0 or (k == "monthly_hours" and not 0 < float(v) <= 744):
            raise ValueError(f"{icao}: fleet.{k} = {v} вне разумного")
        facts.append(Fact(key=f"{key_ac}/fleet_{k}", value=float(v), unit=FLEET[k],
                          currency="EUR" if "eur" in k else None, confidence="exact",
                          **dict(base, note=f"ставка автора типа: {d['fleet_source']}")))
    if d.get("engine_mount"):
        m = str(d["engine_mount"]).strip().lower()
        if m not in MOUNTS:
            raise ValueError(f"{icao}: engine_mount {m!r} — допустимо {', '.join(MOUNTS)}")
        facts.append(Fact(key=f"{key_ac}/engine_mount", value_text=m, unit="место",
                          confidence="exact", **base))
    if d.get("engine"):
        facts.append(Fact(key=f"{key_ac}/engine", value_text=str(d["engine"]),
                          unit="designator", confidence="exact", **base))
    # Статус программы и вид данных (каталог типов, решение 223): у типа в
    # разработке числа — объявленные производителем или оценки прессы, и
    # отчёт обязан сказать это рядом с числом, а не в сноске.
    meta = d.get("meta") or {}
    kind = str(meta.get("data_kind") or "").strip().lower()
    if kind and kind not in DATA_KINDS:
        raise ValueError(f"{icao}: meta.data_kind {kind!r} — допустимо {', '.join(DATA_KINDS)}")
    status = str(meta.get("status") or "").strip().lower()
    if status and status not in STATUSES:
        raise ValueError(f"{icao}: meta.status {status!r} — допустимо {', '.join(STATUSES)}")
    for k, v, unit in (("data_kind", kind, "вид данных"), ("program_status", status, "статус"),
                       ("eis", str(meta.get("eis") or "").strip(), "дата"),
                       ("manufacturer", str(meta.get("manufacturer") or "").strip(), "текст")):
        if v:
            facts.append(Fact(key=f"{key_ac}/{k}", value_text=v, unit=unit,
                              confidence="exact", **base))
    for k in ("range_km", "takeoff_m", "landing_m"):
        if meta.get(k) not in (None, ""):
            facts.append(Fact(key=f"{key_ac}/{k}", value=float(meta[k]),
                              unit="км" if k == "range_km" else "м", confidence="exact",
                              **dict(base, note=f"{d.get('name') or icao}: "
                                                f"{meta.get('range_note') or ''}".strip(": "))))

    burn = d.get("burn") or {}
    if burn:
        analog = str(burn.get("analog") or "").upper()
        if not analog:
            raise ValueError(f"{icao}: в burn нет analog — без аналога ярус 4 не строится")
        anchor = burn.get("anchor_kg_per_h")
        trip = {k: burn.get(f"anchor_trip_{k}") for k in ("kg", "nm", "pax")}
        if any(v is not None for v in trip.values()):
            # Якорь рейсом (решение 224): все три числа или ни одного.
            if any(v is None for v in trip.values()):
                raise ValueError(f"{icao}: якорь рейсом — нужны anchor_trip_kg, anchor_trip_nm "
                                 f"и anchor_trip_pax вместе")
            if not burn.get("anchor_source"):
                raise ValueError(f"{icao}: якорь без anchor_source не заводится")
        # Якорь без издателя — то же, что число с форума (решение 108).
        if anchor is not None and not burn.get("anchor_source"):
            raise ValueError(f"{icao}: якорь без anchor_source не заводится")
        # Вариант с тем же двигателем (свой A320): якорь не нужен,
        # вычислитель аналога и есть вычислитель типа. Флаг явный.
        same = bool(burn.get("same_engine"))
        if same and (anchor is not None or trip.get("kg") is not None):
            raise ValueError(f"{icao}: same_engine и якорь одновременно — выбрать одно")
        bnote = (f"{burn.get('note') or ''} | якорь: {burn.get('anchor_source') or 'не назван'}"
                 f" | аналог назван человеком по поколению двигателя, не выведен")
        b = dict(base, confidence="exact", note=bnote)   # словарь CONFIDENCE закрыт; «назван человеком» — в note
        facts.append(Fact(key=f"{key_ac}/burn_analog", value_text=analog,
                          unit="designator", **b))
        if same:
            facts.append(Fact(key=f"{key_ac}/burn_same_engine", value=1.0,
                              unit="да/нет", **b))
        for k, unit in (("kg", "кг"), ("nm", "nm"), ("pax", "пасс.")):
            if trip.get(k) is not None:
                facts.append(Fact(key=f"{key_ac}/burn_anchor_trip_{k}", value=float(trip[k]),
                                  unit=unit, **b))
        if anchor is not None:
            facts.append(Fact(key=f"{key_ac}/burn_anchor_kg_per_h", value=float(anchor),
                              unit="кг/ч", **b))
            if burn.get("anchor_mass_t") is not None:
                facts.append(Fact(key=f"{key_ac}/burn_anchor_mass_t",
                                  value=float(burn["anchor_mass_t"]), unit="т", **b))
        facts.append(Fact(key=f"{key_ac}/burn_anchor_note",
                          value_text=(burn.get("anchor_source") or
                                      ("вариант с тем же двигателем, множитель 1" if same else
                                       "якорь не назван: тип отвечает «нельзя» до появления якоря")),
                          unit="text", **b))
    return facts
