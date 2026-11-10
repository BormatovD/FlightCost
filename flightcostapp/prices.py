"""Цены и ставки лизинга самолётов из открытых публикаций — ряд на странице типа.

Справочник `data/prices/_observations.yaml`: каждое наблюдение — тип, вид, число,
валюта, месяц, возраст борта, источник и дословная цитата. Собирает агент «цены»
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
"""

from __future__ import annotations

import json
import re
from datetime import date
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
_CACHE: dict = {}


def load(path: Path | None = None) -> dict:
    path = PATH if path is None else path
    try:
        mt = path.stat().st_mtime
    except OSError:
        return {}
    hit = _CACHE.get(str(path))
    if not hit or hit[0] != mt:
        hit = (mt, yaml.safe_load(path.read_text("utf-8")) or {})
        _CACHE[str(path)] = hit
    return hit[1]


def of(icao: str, doc: dict | None = None) -> list[dict]:
    d = load() if doc is None else doc
    return sorted((o for o in d.get("observations") or [] if o.get("icao") == icao.upper()),
                  key=lambda o: str(o.get("month")))


def usd(o: dict, rates: dict | None = None) -> float | None:
    """Значение в USD: «value» × масштаб; EUR и др. — по `rates` (единиц валюты за 1 USD)."""
    v = float(o["value"]) * SCALE.get(str(o.get("scale") or "").lower(), 1)
    cur = str(o.get("currency") or "USD").upper()
    if cur == "USD":
        return v
    k = (rates or {}).get(cur)
    return v / k if k else None


# ── агент и приёмка ──────────────────────────────────────────────────────

def due(types: list[str], doc: dict, today: date | None = None, limit: int = PER_RUN) -> list[str]:
    """Типы по очереди: давно не искали — первыми (поле searched в справочнике)."""
    seen = (doc.get("searched") or {})
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


def check(blob: bytes, doc: dict | None = None, rates: dict | None = None) -> dict:
    doc = load() if doc is None else doc
    try:
        d = json.loads(blob)
    except ValueError as e:
        return {"rows": [], "error": f"не JSON: {e}", "doubts": [], "searched": []}
    have = {(o.get("source"), o.get("icao"), o.get("kind"), float(o.get("value", 0))) for o in doc.get("observations") or []}
    rows = []
    for p in d.get("observations") or []:
        r = {**p, "icao": str(p.get("icao") or "").upper(), "reasons": []}
        rows.append(r)
        if p.get("kind") not in KINDS or not isinstance(p.get("value"), (int, float)) or p["value"] <= 0 \
                or not re.fullmatch(r"\d{4}-\d{2}", str(p.get("month") or "")):
            r.update(verdict="reject", reasons=[f"вид не из {KINDS}, значение не число или месяц не ГГГГ-ММ"])
            continue
        if str(p.get("scale") or "").lower() not in SCALE:
            r.update(verdict="reject", reasons=[f"масштаб {p.get('scale')!r} не из {sorted(SCALE)}"])
            continue
        if not str(p.get("source") or "").startswith("http"):
            r["reasons"].append("нет адреса страницы")
        if not _num_in(str(p.get("quote") or ""), float(p["value"])):
            r["reasons"].append("числа нет в цитате")
        u = usd(r, rates)
        lo, hi = BAND[p["kind"]]
        if u is not None and not lo <= u <= hi:
            r["reasons"].append(f"{u:,.0f} USD вне полосы {lo:,.0f}–{hi:,.0f} для «{KIND_RU[p['kind']]}»")
        if (p.get("source"), r["icao"], p["kind"], float(p["value"])) in have:
            r.update(verdict="skip", reasons=["уже есть"])
            continue
        if p["kind"] == "deal" and re.search(r"\border|заказ", str(p.get("quote") or ""), re.I) \
                and not re.search(r"\beach\b|per aircraft|за борт|за самол", str(p.get("quote") or ""), re.I):
            r["reasons"].append("похоже на сумму заказа, а не цену за борт")
        r["verdict"] = "look" if r["reasons"] else "clean"
    return {"rows": rows, "doubts": [str(x) for x in d.get("doubts") or []],
            "searched": [str(x).upper() for x in d.get("searched") or []]}


FIELDS = ("icao", "kind", "value", "scale", "currency", "month", "age", "quote", "source", "publisher", "note")


def merge(rows: list[dict], searched: list[str], path: Path = PATH, today: date | None = None) -> list[str]:
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
        done.append(f"{o['icao']} {KIND_RU[o['kind']]} {o['value']} {o.get('scale', '')} {o.get('currency', 'USD')} "
                    f"({o['month']})")
    doc["observations"] = sorted(obs, key=lambda o: (o["icao"], str(o["month"]), o["kind"]))
    s = doc.setdefault("searched", {})
    for t in searched:
        s[t] = str(today or date.today())
    doc["searched"] = dict(sorted(s.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), "utf-8")
    _CACHE.pop(str(path), None)
    return done
