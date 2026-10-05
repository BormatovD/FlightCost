"""Тарифы аэропорта: JSON со строками правил -> факты домена airport_charge.

Формат — то, что производит агент, читая AIP или тарифный документ, либо
что ты заполняешь руками для яруса 1. Ставка попадает в числовое поле
факта и проходит валидаторы гейта; описание правила едет в value_text.
"""

from __future__ import annotations

import hashlib
import json

from ..store import Fact

# Достоверность прочтения живёт в СВОЁМ поле `certainty`, а не в
# `confidence`: там закрытый словарь exact/derived/estimated про качество
# происхождения, и `estimated` — обещанная в README метка яруса 3.
# Слить их значило бы сделать «мы посчитали сами» неотличимым от
# «мы списали из негодного документа». Словарь — в store.CERTAINTY.
from ..store import CERTAINTY


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    """Разбор по документу, а не по папке целиком.

    Один плохой файл раньше убивал все пятнадцать: источник типа
    `directory` склеивает документы и падает на первом же. Четырнадцать
    исправных давали ноль фактов, и увидеть это можно было раз в полгода.
    Теперь отвергнутый документ называется поимённо и не попадает в
    хранилище, остальные проходят.
    """
    docs = _split(blob)
    facts: list[Fact] = []
    ok = 0
    for d in docs:
        name = d.get("icao") or d.get("state") or "<без имени>"
        try:
            got = _state(d, ctx) if "state" in d else _one(d, ctx)
            facts += got
            ok += 1
            # Документ разобран ПОЛНОСТЬЮ — только такие дают право снимать
            # с учёта старые ключи (решение 63). Отвергнутый не даёт.
            ctx.setdefault("parsed_prefixes", []).extend(
                sorted({f.key.rsplit("/", 2)[0] for f in got}))
        except Exception as e:                                    # noqa: BLE001
            ctx.setdefault("rejected", []).append(f"{name}: {type(e).__name__}: {e}")
    ctx["parsed_docs"] = ok
    ctx["total_docs"] = len(docs)
    # Итог обязан называть обе цифры. «ok» неотличимо от «ok, но пусто».
    ctx.setdefault("summary", []).append(
        f"разобрано {ok} из {len(docs)} документов тарифа")
    if ok == 0:
        raise ValueError("ни один документ тарифа не разобран:\n  "
                         + "\n  ".join(ctx.get("rejected", [])))
    return facts


def _split(blob: bytes) -> list[dict]:
    """Один JSON или несколько, склеенных построчно источником-папкой.

    Скобки считаются ТОЛЬКО вне строковых литералов: раньше `{` внутри
    примечания сдвигал границы документов, и разъезжалась вся склейка.
    """
    text = blob.decode("utf-8").strip()
    try:
        return [json.loads(text)]
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
        raise ValueError("не удалось разобрать ни одного документа тарифа")
    return out


# Поля записи, а не правила: в Rule они не идут.
RECORD_FIELDS = ("variant", "certainty", "valid_from", "error_cost", "confirm_by")


def _bare(raw: dict) -> dict:
    return {k: v for k, v in raw.items() if k not in RECORD_FIELDS}


def _rule_key(prefix: str, r, variant: str = "") -> str:
    """Ключ по СОДЕРЖАНИЮ правила, а не по его месту в файле.

    Порядковый номер по позиции означал, что перестановка строк в файле
    переписывает смысл ключей: на Дублине 24 из 28. Хранилище append-only
    записало бы это как изменение двух десятков ставок, которого в мире не
    было, и ложно уронило бы проверку дельты. Ставка в ключ не входит —
    иначе изменение цены заводило бы новый ключ вместо новой версии.
    """
    ident = json.dumps({"base": r.base, "events": r.events,
                        "when": r.when, "currency": r.currency,
                        "threshold": r.threshold, "exponent": r.exponent,
                        "pct_of": r.pct_of, "round_mtow": r.round_mtow,
                        "variant": variant},
                       sort_keys=True, ensure_ascii=False)
    return f"{prefix}/{r.code}/{hashlib.sha256(ident.encode()).hexdigest()[:8]}"


def _facts_for(prefix: str, d: dict, ctx: dict, rules_raw: list) -> list["Fact"]:
    from ..charges import BASES, CONDITION_KEYS, EVENTS, Rule

    facts, keys = [], set()
    for raw in rules_raw:
        # `variant` не свойство правила, а различитель одинаковых по
        # механике строк: пять законов итальянской надбавки совпадают
        # кодом, базой и условием и отличаются только ставкой. Без него
        # ключ по содержанию схлопывает их в одну строку.
        raw = dict(raw)
        variant = str(raw.pop("variant", ""))
        # Достоверность и дата вступления — свойства ЗАПИСИ, а не правила.
        # Правило описывает механику начисления, поэтому в Rule они не идут.
        certainty = raw.pop("certainty", d.get("certainty", "exact"))
        err = raw.pop("error_cost", d.get("error_cost"))
        conf_by = raw.pop("confirm_by", d.get("confirm_by"))
        vfrom = raw.pop("valid_from", d["valid_from"])
        if certainty not in CERTAINTY:
            raise ValueError(
                f"достоверность вне словаря: {certainty!r}. "
                f"Допустимые: {sorted(CERTAINTY)}")
        r = Rule(**raw)
        if r.base not in BASES:
            raise ValueError(f"неизвестная база начисления: {r.base}")
        if r.events not in EVENTS:
            raise ValueError(f"неизвестный признак начисления: {r.events}")
        bad = set(r.when) - CONDITION_KEYS
        if bad:
            raise ValueError(
                f"условие вне словаря: {sorted(bad)}. Правило с таким ключом "
                f"никогда не сработает, потому что в контексте расчёта его нет. "
                f"Допустимые: {sorted(CONDITION_KEYS)}")
        key = _rule_key(prefix, r, variant)
        if key in keys:
            raise ValueError(
                f"две строки {r.code} с одинаковыми условиями {r.when} и базой "
                f"{r.base}: одна затрёт другую. Если ставки разные — не хватает "
                f"условия или различителя `variant`, если одинаковые — строка лишняя")
        keys.add(key)
        base = dict(domain="airport_charge", valid_from=vfrom,
                    source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                    extracted_by=ctx.get("extracted_by", "parser:airport_charges@2"),
                    certainty=certainty, node=d.get("map_node") or ctx.get("node"),
                    source_note=d.get("icao_note"),
                    error_cost=err, confirm_by=conf_by,
                    # Три сегмента, всегда в этом порядке: пункт документа
                    # для правила | название документа с редакцией | адрес.
                    # Витрина показывает пункт под правилом и документ со
                    # ссылкой в блоке источника; при двух сегментах (старый
                    # разбор) документа не было видно, и правило выглядело
                    # взявшимся ниоткуда.
                    note=f"{r.source_note or ''} | {d.get('source') or ''}"
                         f" | {d['source_url']}")
        # В числовом поле ВСЕГДА ставка: from_fact кладёт его обратно в
        # rate. Минимум, положенный сюда ради гейта, возвращался ставкой —
        # на Гатвике это давало +453 EUR из воздуха.
        facts.append(Fact(key=key, value=float(r.rate),
                          value_text=r.to_json(), unit=r.base,
                          currency=r.currency, **base))
        # Минимум под гейтом — отдельным фактом с пустым value_text.
        # `load_rules` такие строки пропускает, поэтому в расчёт он не
        # попадает дважды, а валидаторы диапазона его видят.
        if r.minimum is not None:
            facts.append(Fact(key=key + "#min", value=float(r.minimum),
                              value_text="", unit="minimum",
                              currency=r.currency, **base))
    return facts


def _one(d: dict, ctx: dict) -> list["Fact"]:
    from ..charges import Rule, coverage_check, self_check

    icao = d["icao"].upper()
    # Ссылка на публикацию — обязательное поле, а не украшение. Тариф
    # переиздаётся ежегодно, и без адреса обновление превращается в
    # поиск заново по каждому аэропорту.
    if not d.get("source_url"):
        raise ValueError(
            f"{icao}: не указан source_url — адрес публикации тарифа. "
            f"Без него документ нельзя обновить, а значение нельзя проверить")
    # Узел карты обязателен. Без него строки тарифа выпадают из сверки
    # карты с моделью. Приходит из реестра (`node:` источника, в ctx через
    # `**src`) или из `map_node` документа; нет ни того, ни другого —
    # документ отвергается словами, а не пишется несверяемым (решение 58).
    if not (d.get("map_node") or ctx.get("node")):
        raise ValueError(
            f"{icao}: узел карты не задан — ни `node` источника в реестре, ни "
            f"`map_node` в документе. Без узла тариф не сверяется с картой")
    parsed = [Rule(**_bare(raw)) for raw in d["rules"]]
    dead = self_check(parsed)
    if dead:
        raise ValueError("недостижимые правила:\n  " + "\n  ".join(dead))
    ctx.setdefault("coverage", []).extend(       # предупреждение, не отказ
        f"{icao}: {g}" for g in coverage_check(parsed, scales=d.get("scales")))
    ctx.setdefault("icao_seen", []).append(icao)   # для ссылочной проверки гейта
    # Срок годности — от даты СЛЕДУЮЩЕЙ публикации, если она известна.
    # У Дублина тариф с 29 марта, у Порту с 1 июня, у Алматы с 1 июля:
    # годовой SLA от даты загрузки молча предполагает календарный год.
    if d.get("next_edition"):
        ctx.setdefault("next_edition", {})[icao] = d["next_edition"]
    facts = _facts_for(icao, d, ctx, d["rules"])
    # Статья, объявленная неприменимой. Разрешение кандидата корпусной
    # проверки живёт В ДОКУМЕНТЕ и едет фактом: иначе оно останется
    # договорённостью, кандидат всплывёт при следующем прогоне, и список
    # будет вечно содержать известное (решение 57).
    if d.get("next_edition"):
        # Фактом, а не только в ctx: проверку свежести делает гейт, а он
        # видит хранилище, не разбор.
        facts.append(Fact(
            domain="airport_charge", key=f"{icao}/_next", valid_from=d["valid_from"],
            value=0.0, value_text="", unit="next_edition", currency=None,
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by=ctx.get("extracted_by", "parser:airport_charges@3"),
            node=d.get("map_node") or ctx.get("node"), note=d["next_edition"]))
    # Категории типов у этого аэропорта: правила над свойствами типа и
    # поимённый список из документа (см. categories.py). Лежат служебным
    # ключом рядом с `_next` и `_na` — едут с редакцией документа и
    # снимаются с учёта вместе с ним.
    from ..categories import validate as _cat_validate
    from ..charges import DOMAINS as _DOM
    for cond, spec in (d.get("categories") or {}).items():
        dom = _DOM.get(cond)
        _cat_validate(icao, cond, spec, dom if isinstance(dom, set) else None)
        n = len(spec.get("rules") or []) + len(spec.get("named") or {})
        facts.append(Fact(
            domain="airport_charge", key=f"{icao}/_cat/{cond}",
            valid_from=d["valid_from"], value=float(n),
            value_text=json.dumps(spec, ensure_ascii=False, sort_keys=True),
            unit="categories", currency=None, source_id=ctx["source_id"],
            artifact_sha=ctx.get("sha"),
            extracted_by=ctx.get("extracted_by", "parser:airport_charges@3"),
            certainty=spec.get("certainty", d.get("certainty", "exact")),
            error_cost=spec.get("error_cost"), confirm_by=spec.get("confirm_by"),
            node=d.get("map_node") or ctx.get("node"),
            note=f"{spec.get('source_note') or 'категории типов'} | "
                 f"{d.get('source') or ''} | {d['source_url']}"))
    for code, why in (d.get("not_applicable") or {}).items():
        if not why:
            raise ValueError(
                f"{icao}: статья {code} объявлена неприменимой без довода. "
                f"Неприменимость без довода неотличима от пропуска")
        facts.append(Fact(
            domain="airport_charge", key=f"{icao}/_na/{code}",
            valid_from=d["valid_from"], value=0.0, value_text="",
            unit="not_applicable", currency=None, source_id=ctx["source_id"],
            artifact_sha=ctx.get("sha"),
            extracted_by=ctx.get("extracted_by", "parser:airport_charges@3"),
            node=d.get("map_node") or ctx.get("node"), note=why))
    return facts


def _state(d: dict, ctx: dict) -> list["Fact"]:
    """Общегосударственная статья: величину устанавливает закон, не оператор.

    Ключуется государством, а не аэропортом (решение: домен тот же,
    источник отдельный). Область действия НЕ раскрывается здесь: список
    аэропортов государства меняется, исключения датированы, и раскрытие
    на разборе зафиксировало бы состав на дату разбора вместо даты рейса.
    Раскрывает расчёт, читая факт `_scope`.
    """
    from ..charges import Rule, self_check

    st = d["state"].upper()
    if not d.get("source_url"):
        raise ValueError(f"{st}: не указан source_url")
    rules = list(d["rules"])
    for icao, extra in (d.get("airport_extra") or {}).items():
        rules += list(extra)
    dead = self_check([Rule(**_bare(r)) for r in rules])
    if dead:
        raise ValueError("недостижимые правила:\n  " + "\n  ".join(dead))

    facts = _facts_for(st, d, ctx, d["rules"])
    for icao, extra in sorted((d.get("airport_extra") or {}).items()):
        facts += _facts_for(f"{st}:{icao}", d, ctx, extra)
        ctx.setdefault("icao_seen", []).append(icao)
    # Область действия — тоже факт: она датирована и меняется законом.
    # value_text пуст, поэтому load_rules её не примет за правило.
    facts.append(Fact(
        domain="airport_charge", key=f"{st}/_scope", valid_from=d["valid_from"],
        value=float(len((d["scope"].get("exclude") or []))), value_text="",
        unit="scope", currency="", source_id=ctx["source_id"],
        artifact_sha=ctx.get("sha"),
        extracted_by=ctx.get("extracted_by", "parser:airport_charges@2"),
        certainty=d.get("certainty", "exact"), node=d.get("map_node") or ctx.get("node"),
        source_note=d.get("icao_note"), error_cost=d.get("error_cost"),
        confirm_by=d.get("confirm_by"),
        note=json.dumps(d["scope"], ensure_ascii=False)))
    for ex in d["scope"].get("exclude") or []:
        ctx.setdefault("icao_seen", []).extend(ex["icao"])
    return facts
