"""Ставки аэронавигации государства, где их устанавливает регулятор.

Первый случай — Россия: приказ ФАС утверждает разом и маршрутные ставки
(за 100 км ортодромии, по полосам МВМ, отдельно для внутренних и
международных полётов и отдельно для иностранных без договоров), и
терминальные — за тонну МВМ по каждому аэродрому поимённо. Ни того, ни
другого в форме EUROCONTROL нет: маршрутный сбор не зависит от √массы,
терминальный не имеет показателя 0,7. Поэтому формула едет в факте, а
не в коде (решение 43): `value_text` несёт параметры `Formula` из
`navcharge.py`, а расчёт читает их оттуда.

Приказ — скан без текстового слоя. Выписка делается человеком в YAML и
принимается как любая другая поставка; парсер только раскладывает её в
факты. Форма записи:

    source, source_url, publisher, valid_from
    enroute:
      - zones: [UU, UL, ...]     # префиксы ИКАО зон, на которые ставка
        operator: national       # national | foreign
        flight: domestic         # domestic | international
        currency: RUB
        d_div: 100  d_unit: km  d_exp: 1  m_exp: 0
        bands: [[2, 226.2], ...] # (до_т включительно, ставка за 100 км)
        note: "прил. 6"
    terminal:
      - icao: UUEE
        national: {rate: 148.4, currency: RUB, note: "прил. 7, п. 97"}
        foreign:  {rate: 11.8, currency: USD, valid_from: 2026-04-01,
                   note: "прил. 9, п. 31"}

Ключи фактов:
  enroute_rate  <зона>/<operator>/<flight>     value — ставка полосы
                                                50–100 т (представительная),
                                                полосы целиком в value_text
  terminal_rate <ИКАО>/<operator>              value — ставка за тонну
"""

from __future__ import annotations

import json

from ..store import Fact

FORMULA_KEYS = ("d_div", "d_unit", "d_exp", "m_div", "m_exp", "bands")


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    import yaml
    d = yaml.safe_load(blob.decode("utf-8")) or {}
    for req in ("source", "source_url", "publisher", "valid_from"):
        if not d.get(req):
            raise ValueError(f"нет обязательного поля {req!r}")
    base = dict(source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by=ctx.get("extracted_by", "parser:fas_ans@1"),
                confidence="exact")
    vfrom = str(d["valid_from"])
    doc_note = f"{d['publisher']}: {d['source']} | {d['source_url']}"
    facts: list[Fact] = []

    for e in d.get("enroute") or []:
        for req in ("zones", "operator", "flight", "currency", "bands"):
            if not e.get(req):
                raise ValueError(f"enroute: нет поля {req!r}")
        if e["operator"] not in ("national", "foreign") or \
                e["flight"] not in ("domestic", "international"):
            raise ValueError(f"enroute: operator/flight вне словаря: {e}")
        bands = [[float(a), float(b)] for a, b in e["bands"]]
        if bands != sorted(bands):
            raise ValueError("enroute: полосы должны идти по возрастанию массы")
        # Представительная ставка — полоса, в которую попадает 50–100 т:
        # A320 и B737 сидят там. Абсолютный порог гейта проверяет её.
        rep = next((r for lim, r in bands if 100.0 <= lim), bands[-1][1])
        cfg = {k: e[k] for k in FORMULA_KEYS if k in e}
        cfg["bands"] = bands
        for z in e["zones"]:
            facts.append(Fact(
                domain="enroute_rate",
                key=f"{str(z).upper()}/{e['operator']}/{e['flight']}",
                valid_from=str(e.get("valid_from") or vfrom),
                valid_to=str(e["valid_to"]) if e.get("valid_to") else None,
                value=rep, unit="per_100km_by_mtow_band",
                currency=str(e["currency"]).upper(),
                value_text=json.dumps(cfg, ensure_ascii=False),
                note=f"{e.get('note', '')} | {doc_note}",
                certainty=e.get("certainty", "exact"),
                error_cost=e.get("error_cost"), confirm_by=e.get("confirm_by"),
                node="d_rate", **base))

    for t in d.get("terminal") or []:
        icao = str(t.get("icao", "")).upper()
        if len(icao) != 4:
            raise ValueError(f"terminal: нет кода ИКАО в {t}")
        for op in ("national", "foreign"):
            r = t.get(op)
            if not r:
                continue
            if "rate" not in r or "currency" not in r:
                raise ValueError(f"terminal {icao}/{op}: нужны rate и currency")
            cfg = {"m_div": float(r.get("m_div", 1.0)),
                   "m_exp": float(r.get("m_exp", 1.0)), "per": "turnaround"}
            facts.append(Fact(
                domain="terminal_rate", key=f"{icao}/{op}",
                valid_from=str(r.get("valid_from") or vfrom),
                valid_to=str(r["valid_to"]) if r.get("valid_to") else None,
                value=float(r["rate"]), unit="per_tonne_mtow",
                currency=str(r["currency"]).upper(),
                value_text=json.dumps(cfg),
                note=f"{r.get('note', '')} | {doc_note}",
                certainty=r.get("certainty", "exact"),
                error_cost=r.get("error_cost"), confirm_by=r.get("confirm_by"),
                node="d_terminal", **base))
    if not facts:
        raise ValueError("выписка пуста: ни маршрутных, ни терминальных ставок")
    ctx.setdefault("summary", []).append(
        f"аэронавигация: {sum(f.domain == 'enroute_rate' for f in facts)} "
        f"маршрутных и {sum(f.domain == 'terminal_rate' for f in facts)} "
        f"терминальных ставок")
    return facts
