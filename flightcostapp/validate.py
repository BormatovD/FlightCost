"""Гейт: что можно принять молча, а что нести человеку.

Ключевая мысль: агент (или парсер) НИКОГДА не пишет в базу напрямую.
Он производит набор Fact, который проходит через один и тот же набор
проверок независимо от того, кто его породил. Разница между контурами
только в дефолтном исходе: детерминированный парсер по умолчанию auto,
агентный — review.

Проверки идут от дешёвых к дорогим и от структурных к смысловым:
  1. схема       — есть ли обязательные поля, разумны ли типы
  2. единицы     — совпадает ли unit с ожидаемым для домена
  3. диапазон    — попадает ли значение в физически осмысленный коридор
  4. дельта      — насколько сильно отличается от предыдущего значения
  5. полнота     — не схлопнулось ли количество строк (признак поломки парсера)

Пункт 5 — самый недооценённый. Молчаливая деградация выглядит не как
ошибка, а как успешный прогон, в котором вместо 500 аэропортов приехало 12.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import corpus, review
from .store import Fact, Store


@dataclass
class Finding:
    level: str          # 'error' | 'warn' | 'info'
    code: str
    message: str
    key: str | None = None


@dataclass
class GateResult:
    verdict: str                      # 'auto' | 'review' | 'reject'
    findings: list[Finding] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warn"]


def _check(facts, rules, store, domain, prev_count):
    """Пять проверок от дешёвых к дорогим: схема, единицы, диапазон,
    дельта к предыдущему значению, полнота набора."""
    out: list[Finding] = []
    # --- 1. схема -------------------------------------------------------
    for f in facts:
        if not f.key or not f.domain:
            out.append(Finding("error", "schema.key", "пустой domain/key"))
        if f.value is None and f.value_text is None:
            out.append(Finding("error", "schema.value", "нет значения", f.key))
        if not f.valid_from:
            out.append(Finding("error", "schema.valid_from", "нет valid_from", f.key))

    # --- 2. единицы -----------------------------------------------------
    want_unit = rules.get("unit")
    if want_unit:
        for f in facts:
            if f.unit != want_unit:
                out.append(
                    Finding("error", "unit.mismatch",
                            f"unit={f.unit!r}, ожидалось {want_unit!r}", f.key))

    # --- 3. диапазон ----------------------------------------------------
    lo, hi = rules.get("value_min"), rules.get("value_max")
    for f in facts:
        if f.value is None:
            continue
        if lo is not None and f.value < lo:
            out.append(Finding("error", "range.low", f"{f.value} < {lo}", f.key))
        if hi is not None and f.value > hi:
            out.append(Finding("error", "range.high", f"{f.value} > {hi}", f.key))

    # --- 4. дельта к предыдущему ----------------------------------------
    max_delta = rules.get("yoy_delta_max_pct")
    for f in facts:
        # именно latest_before, а не get: см. комментарий в store.py —
        # у помесячных источников на дату нового значения предыдущее уже
        # истекло, и get() вернул бы None, отключив проверку целиком
        prev = store.latest_before(f.domain, f.key, f.valid_from)
        if prev is None or prev["value"] in (None, 0) or f.value is None:
            continue
        delta = (f.value - prev["value"]) / abs(prev["value"]) * 100.0
        if max_delta is not None and abs(delta) > max_delta:
            out.append(
                Finding("warn", "delta.jump",
                        f"{prev['value']:g} -> {f.value:g} ({delta:+.1f}%), "
                        f"порог {max_delta}%", f.key))

    # --- 5. полнота -----------------------------------------------------
    n_min = rules.get("row_count_min")
    if n_min is not None and len(facts) < n_min:
        out.append(Finding("error", "count.min",
                                f"строк {len(facts)}, минимум {n_min}"))
    drop_max = rules.get("row_count_drop_max_pct")
    if drop_max is not None and prev_count:
        drop = (prev_count - len(facts)) / prev_count * 100.0
        if drop > drop_max:
            out.append(Finding("error", "count.drop",
                                    f"строк стало меньше на {drop:.1f}% "
                                    f"({prev_count} -> {len(facts)})"))
    return out


def _referential(facts: list[Fact], store: Store) -> list[Finding]:
    """Ключ ссылается на аэропорт, которого нет в справочнике.

    Файл сборов Палермо был разобран, прошёл гейт и принят для аэропорта,
    которого в домене `airport` не оказалось: шесть проверок отработали
    верно, а связи между доменами не было вовсе. Всплыло только потому,
    что человек набрал маршрут руками.

    Двадцать один итальянский код разрешён по названиям городов из GEN
    4.1 — там кодов нет. Ошибка в одном означает надбавку 6,50 EUR не в
    том аэропорту, и заметить её сегодня нечем.
    """
    icaos = {f.key.split("/")[0] for f in facts
             if f.domain == "airport_charge" and len(f.key.split("/")[0]) == 4}
    if not icaos:
        return []
    if not store.count_keys("airport"):
        # Проверка, которая не может выполниться, обязана сказать об этом,
        # а не промолчать: молчание неотличимо от «все ключи на месте».
        return [Finding("warn", "reference.no_domain",
                        "домен airport пуст: ссылочная проверка не выполнялась")]
    # Домен `airport` ПЛОСКИЙ: один ключ на аэропорт, ключ — код ИАТА, а
    # ИКАО лежит вторым полем value_text. Прежний `select(prefix=f"{icao}/")`
    # не совпал бы ни при каком наполнении — слэша в ключах нет, — и потому
    # отвергал все пятнадцать аэропортов. Первый ложный срабатыв совпал с
    # искомым случаем и был прочитан как подтверждение (решение 100).
    known = store.icao_index()
    out = []
    for icao in sorted(icaos):
        if icao not in known:
            out.append(Finding("error", "reference.icao",
                               f"{icao} отсутствует в домене airport", icao))
    return out


def run_gate(facts: list[Fact], *, source: dict, store: Store,
             prev_count: int | None = None, ctx: dict | None = None) -> GateResult:
    """Правила применяются по доменам.

    Один парсер имеет право выдавать факты нескольких доменов: разбор
    ставок CRCO попутно достаёт курсы валют, применённые для пересчёта.
    Проверять курс франка правилом «не меньше 3 EUR за единицу» —
    бессмысленно, поэтому у каждого домена свой набор правил.
    Основной домен источника берёт `validators`, остальные —
    `validators_extra.<домен>`, а при их отсутствии проходят только
    проверку схемы.
    """
    primary = source.get("domain")
    default_gate = source.get("gate", "review")
    findings: list[Finding] = []
    extra = source.get("validators_extra") or {}

    groups: dict[str, list[Fact]] = {}
    for f in facts:
        groups.setdefault(f.domain, []).append(f)

    for dom, sub in groups.items():
        rules = (source.get("validators") or {}) if dom == primary \
            else (extra.get(dom) or {})
        findings += _check(sub, rules, store, dom,
                           prev_count if dom == primary else None)

    # --- ссылочная проверка, корпусная полнота, приёмка по исключениям --
    review_stats: dict = {}
    if any(f.domain == "airport_charge" for f in facts):
        findings += _referential(facts, store)
        by, res = corpus.from_facts(store)
        for icao in {f.key.split("/")[0] for f in facts if len(f.key.split("/")[0]) == 4}:
            by.setdefault(icao, set())
        for f in facts:                       # корпус вместе с новой поставкой
            parts = f.key.split("/")
            if len(parts) >= 2 and len(parts[0]) == 4 and not parts[1].startswith("_"):
                by[parts[0]].add(parts[1])
            elif len(parts) >= 3 and parts[1] == "_na":
                res.setdefault(parts[0], set()).add(parts[2])
        cands = corpus.check_corpus(by, res)
        flags, review_stats = review.flag(
            facts, store=store, fx=(ctx or {}).get("fx"),
            corpus_candidates=cands, dead_rules=(ctx or {}).get("dead_rules", ()),
            acked=store.acked())
        for fl in flags:
            findings.append(Finding("info", f"review.{fl.trigger}", fl.why, fl.key))
        # Доля выделенных — индикатор второго требования решения 96: если
        # на сотом документе она вырастет, порог выбран неверно.
        findings.append(Finding(
            "info", "review.share",
            f"выделено {review_stats['flagged']} из {review_stats['rules']} строк "
            f"({review_stats['share']:.1%}), поводы: {review_stats['by_trigger'] or 'нет'}"))

    # Предложение, которое ничего не меняет, не должно ждать человека.
    # На приёмку легло 256 фактов, все до одного совпадающие с тем, что уже
    # лежит: решать нечего, а очередь заполняется и приучает нажимать
    # «принять» не глядя. Пометка достоверности при этом уже в хранилище —
    # она приехала с прошлой приёмкой, и повторять вопрос не о чем.
    # Что именно изменилось — по классам, а не одним счётчиком. Прежний
    # счётчик сравнивал только число, и исправление провенанса (узел карты
    # у 246 фактов тарифа) выглядело как «все совпадают — принимать
    # нечего»: гейт честно пропускал приёмку, хранилище честно ничего не
    # писало, и факты навсегда оставались без узла. Сравнение то же, что у
    # хранилища (`store._same`), иначе гейт и запись снова разойдутся.
    from .store import _close
    kinds = {"value": 0, "content": 0, "reading": 0, "node": 0}
    for f in facts:
        p = store.get(f.domain, f.key, f.valid_from)
        if p is None:
            continue
        if not _close(p["value"], f.value):
            kinds["value"] += 1
        elif ((p["unit"] or None) != (f.unit or None)
              or (p["currency"] or None) != (f.currency or None)
              or (p["value_text"] or None) != (f.value_text or None)):
            kinds["content"] += 1
        elif ((p["certainty"] or "exact") != (f.certainty or "exact")
              or not _close(p["error_cost"], f.error_cost)
              or (p["confirm_by"] or None) != (f.confirm_by or None)):
            kinds["reading"] += 1
        elif (p["node"] or None) != (f.node or None):
            kinds["node"] += 1
    n_changed = kinds["value"]

    # --- вердикт --------------------------------------------------------
    n_new = sum(1 for f in facts
                if store.get(f.domain, f.key, f.valid_from) is None)
    substantive = kinds["value"] + kinds["content"] + kinds["reading"] + n_new
    if kinds["node"]:
        findings.append(Finding(
            "info", "diff.node",
            f"узел карты исправлен у {kinds['node']} фактов — значения не "
            f"менялись, записывается как исправление на том же интервале"))
    if kinds["reading"]:
        findings.append(Finding(
            "info", "diff.reading",
            f"у {kinds['reading']} фактов изменилась достоверность, цена "
            f"ошибки или адресат при том же значении"))
    if any(f.level == "error" for f in findings):
        verdict = "reject"
    elif any(f.level == "warn" for f in findings):
        verdict = "review"          # предупреждение всегда поднимает до ревью
    elif substantive == 0 and kinds["node"] == 0:
        # Нечего принимать: содержимое совпадает с хранилищем целиком.
        verdict = "auto"
        findings.append(Finding(
            "info", "diff.empty",
            f"все {len(facts)} фактов совпадают с хранилищем — принимать "
            f"нечего, приёмка пропущена"))
    elif substantive == 0:
        # Только узел: утверждение о мире не менялось, менялось то, где
        # на карте его проверять. Держать это в очереди человека — учить
        # его принимать не глядя; пишется сразу и называется строкой выше.
        verdict = "auto"
    else:
        verdict = default_gate

    # значения от агента с оценочной уверенностью не проходят авто никогда
    if verdict == "auto" and any(
        f.confidence != "exact" or f.extracted_by.startswith("agent:") for f in facts
    ):
        if source.get("contour") == "agent" and source.get("gate") != "auto":
            verdict = "review"

    # Достоверность прочтения — вторая ось (решение 73), и проверялась
    # только первая. Ставки Дохи редакции 2020 с меткой `stale_edition`
    # прошли бы авто: происхождение у них `exact`, документ настоящий.
    # Оси ортогональны, значит и условие должно смотреть на обе.
    if verdict == "auto" and any(f.certainty != "exact" for f in facts):
        verdict = "review"

    return GateResult(
        verdict=verdict,
        findings=findings,
        facts=facts,
        stats={"n_facts": len(facts), "n_changed": n_changed,
               "n_node_fixed": kinds["node"], "n_reading_changed": kinds["reading"],
               "n_content_changed": kinds["content"],
               "domains": {d: len(v) for d, v in groups.items()},
               **({"review": review_stats} if review_stats else {})},
    )


def freshness_report(store: Store, registry: dict, today=None) -> list[dict]:
    """Какие источники просрочены. Вызывается и планировщиком, и моделью:
    расчёт на протухших ставках должен об этом сообщать, а не молчать."""
    from datetime import date, datetime

    today = today or date.today()
    out = []
    for sid, src in registry["sources"].items():
        st = store.source_state(sid)
        sla = src.get("sla_days", 365)
        if st is None or not st["last_ok"]:
            out.append({"source": sid, "state": "never", "age_days": None, "sla": sla})
            continue
        last_ok = datetime.fromisoformat(st["last_ok"]).date()
        age = (today - last_ok).days
        state = "stale" if age > sla else "fresh"
        why = None
        # Срок годности от ДАТЫ СЛЕДУЮЩЕЙ ПУБЛИКАЦИИ, если она известна.
        # У Дублина тариф с 29 марта, у Порту с 1 июня, у Алматы с 1 июля:
        # годовой SLA от даты загрузки молча предполагает календарный год и
        # полгода отдаёт прошлогоднюю ставку, оставаясь `fresh`.
        for row in store.select(src.get("domain", ""), suffix="/_next").values():
            nxt = (row["note"] or "")[:10]
            if nxt and str(last_ok) < nxt <= str(today):
                state, why = "stale", f"вышла новая редакция {row['key']} от {nxt}"
                break
        out.append({
            "source": sid, "state": state, "age_days": age, "sla": sla,
            "title": src.get("title", sid), **({"why": why} if why else {}),
        })
    return out
