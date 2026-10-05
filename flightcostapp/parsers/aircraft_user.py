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
}
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
    if missing:
        raise ValueError(f"{icao}: нет полей {', '.join(missing)}")
    unknown = sorted(set(fields) - set(FIELDS))
    if unknown:
        raise ValueError(f"{icao}: неизвестные поля {', '.join(unknown)}; "
                         f"допустимы {', '.join(FIELDS)}")
    if float(fields["oew_t"]) >= float(fields["mtow_t"]):
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
                  confidence="exact", **base) for k, v in fields.items()]
    if d.get("engine"):
        facts.append(Fact(key=f"{key_ac}/engine", value_text=str(d["engine"]),
                          unit="designator", confidence="exact", **base))

    burn = d.get("burn") or {}
    if burn:
        analog = str(burn.get("analog") or "").upper()
        if not analog:
            raise ValueError(f"{icao}: в burn нет analog — без аналога ярус 4 не строится")
        anchor = burn.get("anchor_kg_per_h")
        # Якорь без издателя — то же, что число с форума (решение 108).
        if anchor is not None and not burn.get("anchor_source"):
            raise ValueError(f"{icao}: якорь без anchor_source не заводится")
        # Вариант с тем же двигателем (свой A320): якорь не нужен,
        # вычислитель аналога и есть вычислитель типа. Флаг явный.
        same = bool(burn.get("same_engine"))
        if same and anchor is not None:
            raise ValueError(f"{icao}: same_engine и якорь одновременно — выбрать одно")
        bnote = (f"{burn.get('note') or ''} | якорь: {burn.get('anchor_source') or 'не назван'}"
                 f" | аналог назван человеком по поколению двигателя, не выведен")
        b = dict(base, confidence="exact", note=bnote)   # словарь CONFIDENCE закрыт; «назван человеком» — в note
        facts.append(Fact(key=f"{key_ac}/burn_analog", value_text=analog,
                          unit="designator", **b))
        if same:
            facts.append(Fact(key=f"{key_ac}/burn_same_engine", value=1.0,
                              unit="да/нет", **b))
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
