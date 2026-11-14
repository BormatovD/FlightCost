"""Цены и ставки лизинга самолётов из открытых публикаций — ряд на странице типа.

Справочник `data/prices/_observations.yaml`: каждое наблюдение — тип, вид, число,
валюта, период оценки (месяц, квартал или год), возраст борта, источник и дословная цитата. Собирает агент «цены»
(agent_run.prices) по нескольку типов за прогон; дома `fca master drafts` проверяет,
`--accept-prices` дописывает.

Виды — разные величины, их нельзя смешивать в одну линию:
  list    — каталожная цена производителя (Airbus перестал публиковать в 2018,
            Boeing — в 2023; после — оценки консультантов «по каталогу»);
  deal    — цена сделки за борт из сообщения о продаже, обратном лизинге, заказе
            (в заказе цена за борт — только если её назвали, не делением суммы);
  value   — рыночная стоимость по оценке (appraisal, отчёты по ценным бумагам,
            годовые отчёты лизингодателей);
  lease   — ставка лизинга в месяц.
Числа в справочнике — как напечатаны (валюта и единица рядом); пересчёт — при показе.
Скаляр хранится как value, опубликованный интервал — как value_low/value_high.
Для расчётов используется середина интервала, его исходные границы сохраняются.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date
from statistics import fmean
from tempfile import TemporaryDirectory
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "prices" / "_observations.yaml"
KINDS = ("list", "deal", "value", "lease")
KIND_RU = {"list": "каталог", "deal": "сделка", "value": "оценка рынка", "lease": "лизинг в месяц"}
# Полосы правдоподобия, USD: борт — от 3 до 500 млн, лизинг — от 30 тыс. до 3 млн в месяц.
BAND = {"list": (3e6, 5e8), "deal": (3e6, 5e8), "value": (1e6, 5e8), "lease": (3e4, 3e6)}
SCALE = {"": 1, "k": 1e3, "thousand": 1e3, "тыс": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "млн": 1e6,
         "bn": 1e9, "billion": 1e9, "млрд": 1e9}
PER_RUN = 4
YIELD_PATH = ROOT / "data" / "prices" / "_lessor_yield.yaml"
_CACHE: dict = {}


def lessor_yield(who: str = "AER") -> dict[int, float]:
    """Доходность парка лизингодателя по годам: арендная плата ÷ средний парк."""
    d = load(YIELD_PATH).get(who) or {}
    return {int(y): float(v["rents"]) / float(v["assets"]) for y, v in (d.get("years") or {}).items()}


def real_level(obs: list[dict], new_gen: bool, years: tuple[int, int], to_year: int, cpi: dict) -> float | None:
    """Медиана ставок/середин интервалов нужного возраста за `years`, по CPI, тыс. USD `to_year`."""
    import statistics
    if not cpi:
        return None
    last = max(cpi)
    g = cpi[last] / cpi[last - 1] if last - 1 in cpi else 1.03
    ix = lambda y: cpi[y] if y in cpi else cpi[last] * g ** (y - last)       # noqa: E731
    vals = []
    for o in obs:
        y = int(str(o["month"])[:4])
        age_ok = str(o.get("age")) == "new" if new_gen else \
            isinstance(o.get("age"), (int, float)) and 8 <= float(o["age"]) <= 14
        if o["kind"] == "lease" and age_ok and years[0] <= y <= years[1] and usd(o):
            vals.append(usd(o) * ix(to_year) / ix(y) / 1e3)
    return statistics.median(vals) if vals else None


def period_months(period: str) -> tuple[int, int]:
    """Inclusive start/end months, retaining the original precision in the record."""
    if re.fullmatch(r"[0-9]{4}", period):
        return 1, 12
    if re.fullmatch(r"[0-9]{4}-Q[1-4]", period):
        end = 3 * int(period[-1])
        return end - 2, end
    if re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", period):
        month = int(period[5:])
        return month, month
    raise ValueError(f"ожидается год ГГГГ, квартал ГГГГ-Q1…Q4 или месяц ГГГГ-ММ: {period}")


def period_order(obs: dict) -> tuple:
    period = str(obs["month"])
    start, end = period_months(period)
    return period[:4], end, start


def load(path: Path | None = None) -> dict:
    path = PATH if path is None else path
    try:
        stat = path.stat()
        revision = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}
    hit = _CACHE.get(str(path))
    if not hit or hit[0] != revision:
        hit = (revision, yaml.safe_load(path.read_text("utf-8")) or {})
        _CACHE[str(path)] = hit
    return hit[1]


def of(icao: str, doc: dict | None = None) -> list[dict]:
    d = load() if doc is None else doc
    return sorted((o for o in d.get("observations") or [] if o.get("icao") == icao.upper()),
                  key=period_order)


def is_range(o: dict) -> bool:
    """У наблюдения есть обе исходные границы; их корректность проверяет bounds."""
    return "value_low" in o and "value_high" in o


def bounds(o: dict) -> tuple[float, float]:
    """Исходные числа без масштаба/конвертации: (value, value) либо (value_low, value_high)."""
    if "value" in o and not ("value_low" in o or "value_high" in o):
        values = (o["value"], o["value"])
    elif is_range(o) and "value" not in o:
        values = (o["value_low"], o["value_high"])
    else:
        raise ValueError("нужно либо value, либо оба value_low/value_high, без смешивания")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
        raise ValueError("цена и границы должны быть положительными конечными числами")
    try:
        lo, hi = map(float, values)
    except OverflowError:
        raise ValueError("цена и границы должны быть конечными числами") from None
    if not all(math.isfinite(v) and v > 0 for v in (lo, hi)):
        raise ValueError("цена и границы должны быть положительными конечными числами")
    if lo > hi:
        raise ValueError("value_low больше value_high")
    return lo, hi


def midpoint(o: dict) -> float:
    """Число для расчёта в исходных единицах; середина диапазона не является отдельной котировкой."""
    lo, hi = bounds(o)
    return lo / 2 + hi / 2


def amount_bounds(o: dict) -> tuple[float, float]:
    """Границы в исходной валюте с уже применённым scale."""
    factor = SCALE.get(str(o.get("scale") or "").lower(), 1)
    lo, hi = bounds(o)
    return lo * factor, hi * factor


def usd_bounds(o: dict, rates: dict | None = None) -> tuple[float, float] | None:
    """Границы × масштаб в USD; rates — единиц исходной валюты за 1 USD."""
    lo, hi = amount_bounds(o)
    cur = str(o.get("currency") or "USD").upper()
    if cur == "USD":
        return lo, hi
    k = (rates or {}).get(cur)
    return (lo / k, hi / k) if k else None


def usd(o: dict, rates: dict | None = None) -> float | None:
    """Скаляр или середина диапазона в USD; прежний числовой контракт потребителей."""
    pair = usd_bounds(o, rates)
    return pair[0] / 2 + pair[1] / 2 if pair is not None else None


def _identity(o: dict) -> tuple:
    age = o.get("age")
    if isinstance(age, (int, float)) and not isinstance(age, bool):
        age = float(age)
    base = (o.get("source"), str(o.get("icao") or "").upper(), o.get("kind"),
            str(o.get("month") or ""), age, str(o.get("currency") or "USD").upper(), *amount_bounds(o))
    if o.get("variant") or o.get("valuation_basis"):
        return (*base, o.get("variant"), o.get("valuation_basis"))
    return base


def observation_id(o: dict) -> str:
    """Стабильный SHA-256 семантического наблюдения; примечания и checked в ID не входят."""
    payload = json.dumps(_identity(o), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lease_types() -> list[str]:
    """Types with accepted lease observations; annual_lease selects eligible rates."""
    return sorted({row["icao"] for row in load().get("observations", []) if row["kind"] == "lease"})


def lease_revision() -> str:
    """Invalidate network results when an accepted lease or its source changes."""
    rows = [o for o in load().get("observations", []) if o.get("kind") == "lease"]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _available(obs: dict, day: date) -> bool:
    period = str(obs["month"])
    if period[:4] != str(day.year):
        return False
    start, end = period_months(period)
    if start > day.month:
        return False
    if obs.get("published_on"):
        return str(obs["published_on"]) <= day.isoformat()
    if start != end:
        return day >= date(day.year, end, calendar.monthrange(day.year, end)[1])
    return True


def source_family(obs: dict) -> str:
    family = (obs.get("source_family") or "").strip()
    if family:
        return family.casefold()
    publisher = (obs.get("publisher") or "").strip()
    original = re.search(r"[(]данные ([^()]+)[)]", publisher, re.I)
    return (original[1] if original else publisher or obs.get("source") or "").casefold()


def annual_lease(icao: str, as_of, age: float | None = None, store=None) -> dict | None:
    """Calendar-year mean, equally weighted by original source, using known publications only."""
    from .fleet import generation
    from . import fx
    day = date.fromisoformat(str(as_of)[:10])
    new_gen = generation(icao) == "new"
    groups = defaultdict(dict)
    for obs in of(icao):
        if obs["kind"] != "lease" or not _available(obs, day):
            continue
        years = 0 if obs.get("age") == "new" else obs.get("age")
        if isinstance(years, bool) or not isinstance(years, (int, float)):
            continue
        age_matches = years == age if age is not None else (years == 0 if new_gen else 8 <= years <= 14)
        if not age_matches:
            continue
        # Multiple links reporting the same appraisal must not increase its weight.
        key = (obs["month"], years, obs.get("variant"), obs.get("valuation_basis"),
               obs.get("currency", "USD"), amount_bounds(obs))
        groups[source_family(obs)].setdefault(key, obs)
    if not groups:
        return None

    rows = [o for group in groups.values() for o in group.values()]
    currencies = {o.get("currency", "USD") for o in rows}
    currency = rows[0].get("currency", "USD") if len(currencies) == 1 else "USD"
    quotes = {}

    def rate(cur):
        if cur not in quotes:
            quotes[cur] = (fx.quote(store, cur, day) if store is not None else
                           {"rate": 1.0 if cur == "EUR" else None})
        return quotes[cur]

    sources = []
    means = []
    for group in groups.values():
        values = []
        for obs in group.values():
            cur = obs.get("currency", "USD")
            lo, hi = amount_bounds(obs)
            middle = (lo + hi) / 2
            if cur != currency:
                if not (rate(cur)["rate"] and rate(currency)["rate"]):
                    return None
                middle = middle / rate(cur)["rate"] * rate(currency)["rate"]
            values.append(middle)
            reference = {k: obs.get(k) for k in ("publisher", "source", "month", "age", "variant",
                                                  "published_on", "source_family")}
            reference.update(currency=cur, low=lo, high=hi, id=observation_id(obs))
            sources.append(reference)
        means.append(fmean(values))
    mid = fmean(means)
    exchange = rate(currency)
    only = rows[0] if len(rows) == 1 else {}
    lo, hi = amount_bounds(only) if only else (mid, mid)
    ages = {o.get("age") for o in rows}
    return {"id": observation_id(only) if only else None, "icao": icao,
            "month": only.get("month", str(day.year)), "age": rows[0].get("age") if len(ages) == 1 else None,
            "currency": currency, "low": lo, "high": hi, "midpoint": mid,
            "lease_eur_month": mid / exchange["rate"] if exchange["rate"] else None,
            "fx": {**exchange, "as_of": str(day)}, "year": day.year,
            "source_count": len(groups), "sources": sources,
            **{k: only.get(k) for k in ("source", "publisher", "note", "quote")}}


def lease_selection(obs: dict, store, as_of) -> dict:
    """Published bounds and calculation-date FX, shared by explicit and automatic paths."""
    from . import fx
    currency = str(obs.get("currency") or "USD").upper()
    lo, hi = amount_bounds(obs)
    mid = lo / 2 + hi / 2
    rate = fx.quote(store, currency, as_of)
    k = rate.get("rate")
    eur = mid / k if isinstance(k, (int, float)) and math.isfinite(k) and k > 0 else None
    return {"id": observation_id(obs), "icao": obs["icao"], "month": obs["month"],
            "age": obs.get("age"), "currency": currency, "low": lo, "high": hi,
            "midpoint": mid, "lease_eur_month": eur, "source": obs.get("source"),
            "publisher": obs.get("publisher"), "quote": obs.get("quote"), "note": obs.get("note"),
            "fx": {**rate, "as_of": str(as_of)}}


def find_observation(id: str, doc: dict | None = None) -> dict | None:
    """Только принятое наблюдение из справочника; внешние черновики здесь не загружаются."""
    if not isinstance(id, str) or not re.fullmatch(r"[0-9a-f]{64}", id):
        return None
    for o in (load() if doc is None else doc).get("observations") or []:
        if observation_id(o) == id:
            return dict(o)
    return None


# ── агент и приёмка ──────────────────────────────────────────────────────

def normalize_searched(values) -> list[str]:
    """Коды из служебного поля searched: CODE или CODE (название), без угадывания по названию."""
    if isinstance(values, str):
        values = [values]
    out = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        m = re.fullmatch(r"([A-Z0-9]{4})(?:\s+\([^()\r\n]+\))?", value.strip().upper())
        if m and m[1] not in out:
            out.append(m[1])
    return out


def _searched_dates(values: dict) -> dict[str, str]:
    seen = {}
    for label, when in values.items():
        for code in normalize_searched([label]):
            seen[code] = max(seen.get(code, ""), str(when))
    return seen


def due(types: list[str], doc: dict, today: date | None = None, limit: int = PER_RUN) -> list[str]:
    """Типы по очереди: давно не искали — первыми (поле searched в справочнике)."""
    seen = _searched_dates(doc.get("searched") or {})
    return sorted(types, key=lambda t: str(seen.get(t, "")))[:limit]


def _num_in(quote: str, value: float) -> bool:
    for tok in re.findall(r"\d[\d\s ,.']*\d|\d", quote or ""):
        t = re.sub(r"[\s ']", "", tok)
        for a, b in ((",", "."), (".", ",")):
            try:
                if abs(float(t.replace(a, "").replace(b, ".")) - value) <= max(0.006, abs(value) * 0.002):
                    return True
            except ValueError:
                pass
    return False


def _money_amount(number: str, unit: str | None) -> float:
    number = re.sub(r"[\s'’]", "", number)
    if "," in number and "." in number:
        # Последний разделитель — десятичный: 100,000.50 / 100.000,50.
        decimal = "," if number.rfind(",") > number.rfind(".") else "."
        number = number.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif re.fullmatch(r"[1-9]\d{0,2}(?:[.,]\d{3})+", number):
        number = number.replace(",", "").replace(".", "")
    else:
        number = number.replace(",", ".")
    return float(number) * SCALE.get((unit or "").lower().rstrip("."), 1)


def _money_evidence(quote: str, currency: str) -> tuple[list, list[float]]:
    """Денежные интервалы и самостоятельные суммы вне них; модели/возраст/годы не подходят."""
    cur = {"USD": r"(?:U\.?S\.?\s*(?:\$|dollars?)|USD|\$|dollars?)",
           "EUR": r"(?:EUR|€|euros?)", "GBP": r"(?:GBP|£|pounds?)"}.get(
               currency.upper(), re.escape(currency))
    number = r"\d+(?:[.,]\d+)*(?:[\s'’]\d{3})*(?:[.,]\d+)?"
    unit = r"(?:thousand|million|billion|тыс\.?|млн|млрд|bn|mn|k|m)(?!\w)"

    def part(prefix):
        return rf"(?P<{prefix}c>{cur})?\s*(?P<{prefix}n>{number})\s*(?P<{prefix}u>{unit})?"

    # В «737-800 US$48 million» валюта относится к следующему числу,
    # а не к суффиксу диапазона/предыдущего скаляра.
    suffix = rf"\s*(?:(?P<c>{cur})(?!\s*\d))?"
    patterns = [rf"(?<!\w){part('a')}\s*(?:[-–—−]|\bto\b|\bдо\b)\s*{part('b')}{suffix}"]
    # «and/и» само по себе связывает и независимые цены. Диапазоном
    # считаем только явную пару «between … and …» / «между … и …».
    patterns += [rf"(?<!\w){start}\s+{part('a')}\s+{link}\s+{part('b')}{suffix}"
                 for start, link in (("between", "and"), ("между", "и"))]
    ranges = sorted((m for pattern in patterns for m in re.finditer(pattern, quote, re.I)
                     if m['ac'] or m['bc'] or m['c']), key=lambda m: m.start())
    # Не брать границу, середину или иное число из диапазона. Сохраняем
    # только возможность подтвердить ту же сумму отдельным скаляром.
    for m in reversed(ranges):
        quote = quote[:m.start()] + " " * (m.end() - m.start()) + quote[m.end():]
    scalars = []
    for m in re.finditer(rf"(?<!\w){part('s')}{suffix}", quote, re.I):
        if not (m['sc'] or m['c']):
            continue
        try:
            scalar = _money_amount(m['sn'], m['su'])
        except ValueError:
            continue
        scalars.append(scalar)
    return ranges, scalars


def _money_equal(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.01, abs(b) * 1e-9)


def _money_range_only(quote: str, amount: float, currency: str) -> bool:
    ranges, scalars = _money_evidence(quote, currency)
    return bool(ranges) and not any(_money_equal(value, amount) for value in scalars)


def _quoted_bounds(m) -> tuple[float, float]:
    a, b = _money_amount(m['an'], None), _money_amount(m['bn'], None)
    au, bu = m['au'] or m['bu'], m['bu'] or m['au']
    # US$100,000–115k / US$100k–115,000: полное число уже в валюте.
    if not m['au'] and a >= 1000 > b:
        au = None
    if not m['bu'] and b >= 1000 > a:
        bu = None
    lo, hi = _money_amount(m['an'], au), _money_amount(m['bn'], bu)
    if not m['au'] and not m['bu'] and a < 1000:
        grouped = re.fullmatch(r"\d{1,3}((?:[.,\s'’]\d{3})+)", m['bn'])
        if grouped:
            # Публикуемая сокращённая запись US$100–115,000 означает
            # 100,000–115,000, а US$20–21,000,000 — 20–21 млн.
            factor = 1000 ** len(re.findall(r"[.,\s'’]\d{3}", grouped[1]))
            if a * factor <= hi:
                lo = a * factor
    return lo, hi


def _range_in(quote: str, pair: tuple[float, float], currency: str) -> bool:
    for m in _money_evidence(quote, currency)[0]:
        try:
            lo, hi = _quoted_bounds(m)
        except ValueError:
            continue
        if _money_equal(lo, pair[0]) and _money_equal(hi, pair[1]):
            return True
    return False


def check(blob: bytes, doc: dict | None = None, rates: dict | None = None) -> dict:
    doc = load() if doc is None else doc
    try:
        d = json.loads(blob)
    except ValueError as e:
        return {"rows": [], "error": f"не JSON: {e}", "doubts": [], "searched": []}
    have = {_identity(o) for o in doc.get("observations") or []}
    rows = []
    for p in d.get("observations") or []:
        if not isinstance(p, dict):
            rows.append({"icao": "", "verdict": "reject", "reasons": ["наблюдение должно быть объектом"]})
            continue
        r = {**p, "icao": str(p.get("icao") or "").upper(), "reasons": []}
        r.pop("rejection_code", None)       # служебный маркер вычисляет проверка, не модель
        rows.append(r)
        if p.get("kind") not in KINDS:
            r.update(verdict="reject", reasons=[f"вид не из {KINDS}"])
            continue
        try:
            r["month"] = str(p.get("month") or "")
            period_months(r["month"])
            if p.get("published_on") is not None:
                published = str(p["published_on"])
                if date.fromisoformat(published).isoformat() != published:
                    raise ValueError("published_on должна иметь формат ГГГГ-ММ-ДД")
            raw_pair = bounds(p)
        except ValueError as exc:
            r.update(verdict="reject", reasons=[str(exc)])
            continue
        if any(p.get(k) is not None and not isinstance(p[k], str) for k in ("scale", "currency", "quote", "source", "source_family", "variant", "valuation_basis", "published_on")):
            r.update(verdict="reject", reasons=["scale, currency, quote и source должны быть строками"])
            continue
        age = p.get("age")
        if age is not None and age != "new" and (isinstance(age, bool) or not isinstance(age, (int, float))
                                                or not math.isfinite(age) or age < 0):
            r.update(verdict="reject", reasons=["age должен быть new, числом лет или null"])
            continue
        if str(p.get("scale") or "").lower() not in SCALE:
            r.update(verdict="reject", reasons=[f"масштаб {p.get('scale')!r} не из {sorted(SCALE)}"])
            continue
        quote, currency = str(p.get("quote") or ""), str(p.get("currency") or "USD")
        if is_range(p) and not _range_in(quote, amount_bounds(p), currency):
            r.update(verdict="reject", rejection_code="range_evidence",
                     reasons=["обе границы с масштабом и валютой должны совпадать с денежным диапазоном в цитате"])
            continue
        if not is_range(p) and _money_range_only(quote, amount_bounds(p)[0], currency):
            r.update(verdict="reject", rejection_code="money_range",
                     reasons=["в цитате денежный диапазон, а не отдельная цена или ставка; "
                              "сохраните обе границы в value_low/value_high вместо скалярного value"])
            continue
        if not str(p.get("source") or "").startswith("http"):
            r["reasons"].append("нет адреса страницы")
        if not is_range(p) and not _num_in(quote, raw_pair[0]):
            r["reasons"].append("числа нет в цитате")
        pair = usd_bounds(r, rates)
        lo, hi = BAND[p["kind"]]
        if pair is not None and not (lo <= pair[0] <= pair[1] <= hi):
            shown = f"{pair[0]:,.0f}–{pair[1]:,.0f}" if is_range(r) else f"{pair[0]:,.0f}"
            r["reasons"].append(f"{shown} USD вне полосы {lo:,.0f}–{hi:,.0f} для «{KIND_RU[p['kind']]}»")
        identity = _identity(r)
        if identity in have:
            r.update(verdict="skip", reasons=["уже есть"])
            continue
        if p["kind"] == "deal" and re.search(r"\border|заказ", str(p.get("quote") or ""), re.I) \
                and not re.search(r"\beach\b|per aircraft|за борт|за самол", str(p.get("quote") or ""), re.I):
            r["reasons"].append("похоже на сумму заказа, а не цену за борт")
        r["verdict"] = "look" if r["reasons"] else "clean"
        have.add(identity)
    return {"rows": rows, "doubts": [str(x) for x in d.get("doubts") or []],
            "searched": normalize_searched(d.get("searched"))}


FIELDS = ("icao", "kind", "value", "value_low", "value_high", "scale", "currency", "month", "age", "quote", "source",
          "publisher", "note", "published_on", "variant", "valuation_basis", "source_family")


def merge(rows: list[dict], searched: list[str], path: Path | None = None, today: date | None = None) -> list[str]:
    path = PATH if path is None else path
    doc = (yaml.safe_load(path.read_text("utf-8")) or {}) if path.exists() else {}
    head = "".join(ln for ln in path.read_text("utf-8").splitlines(True) if ln.startswith("#")) \
        if path.exists() else ""
    obs = doc.setdefault("observations", [])
    done = []
    for r in rows:
        o = {k: r.get(k) for k in FIELDS if r.get(k) not in (None, "")}
        o["quote"] = str(o.get("quote", ""))[:300]
        o["checked"] = str(today or date.today())
        obs.append(o)
        lo, hi = bounds(o)
        shown = f"{lo:g}–{hi:g}" if is_range(o) else f"{lo:g}"
        done.append(f"{o['icao']} {KIND_RU[o['kind']]} {shown} {o.get('scale', '')} {o.get('currency', 'USD')} "
                    f"({o['month']})")
    doc["observations"] = sorted(obs, key=lambda o: (o["icao"], period_order(o), o["kind"]))
    s = _searched_dates(doc.get("searched") or {})
    for t in normalize_searched(searched):
        s[t] = max(s.get(t, ""), str(today or date.today()))
    doc["searched"] = dict(sorted(s.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Readers see either complete registry while a reviewed batch is being published.
    with TemporaryDirectory(dir=path.parent) as staging:
        ready = Path(staging) / path.name
        ready.write_text(head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), "utf-8")
        if path.exists():
            ready.chmod(path.stat().st_mode & 0o777)
        ready.replace(path)
    _CACHE.pop(str(path), None)
    return done
