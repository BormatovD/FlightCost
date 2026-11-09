"""Ночные ограничения аэропортов: окно базы в режиме «Сеть» (план network-calc, шаг 4).

Справочник `data/airports/_night.yaml` — по аэропорту: вид ограничения, часы
(местное время), источник и дословная цитата. Собирает агент «ночь»
(agent_run.night) по аэропортам, у которых заведён тариф; дома черновик
проверяет `fca master drafts`, по `--accept-night` точки дописываются сюда.

Как это входит в расчёт. Коэффициенты налёта откалиброваны при окне 18 ч
(netutil.ANNUAL, Form 41 T-2 — в основном аэропорты США без запретов). Поэтому
справочник окно только СУЖАЕТ: запрет «ban» короче 6 ч оставляет 18, длиннее —
окно = 24 − длина запрета. Квоты и ночные надбавки («quota», «surcharge») окно не
меняют, но называются в предупреждении. Шире 18 — только если человек задал сам.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NIGHT_PATH = ROOT / "data" / "airports" / "_night.yaml"
KINDS = ("ban", "quota", "surcharge", "none")
KIND_RU = {"ban": "запрет", "quota": "квота", "surcharge": "ночная надбавка", "none": "без ограничений"}
RECHECK_DAYS = 365
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CACHE: dict = {}


def load(path: Path | None = None) -> dict:
    path = NIGHT_PATH if path is None else path
    try:
        mt = path.stat().st_mtime
    except OSError:
        return {}
    hit = _CACHE.get(str(path))
    if not hit or hit[0] != mt:
        hit = (mt, yaml.safe_load(path.read_text("utf-8")) or {})
        _CACHE[str(path)] = hit
    return hit[1]


def _h(t: str) -> float:
    return int(t[:2]) + int(t[3:]) / 60


def closed_hours(rec: dict) -> float | None:
    """Длина ночного интервала, часов (через полночь — тоже)."""
    a, b = rec.get("from"), rec.get("to")
    if not (a and b and _HHMM.match(str(a)) and _HHMM.match(str(b))):
        return None
    d = (_h(b) - _h(a)) % 24
    return d or None


def of(icao: str, doc: dict | None = None) -> dict | None:
    return ((load() if doc is None else doc).get("airports") or {}).get(icao.upper())


def base_window(icao: str, default: float, doc: dict | None = None) -> tuple[float, str | None]:
    """(окно базы, пояснение или None). Сужает окно только запрет."""
    r = of(icao, doc)
    if not r:
        return default, None
    c = closed_hours(r)
    txt = f"{icao}: {KIND_RU.get(r.get('kind'), r.get('kind'))} {r.get('from')}–{r.get('to')} местного"
    if r.get("kind") == "ban" and c and 24 - c < default:
        return 24 - c, txt + f" — окно базы {24 - c:g} ч вместо {default:g}"
    return default, txt if r.get("kind") in ("ban", "quota", "surcharge") else None


def notes(icaos, doc: dict | None = None) -> list[str]:
    out = []
    for icao in dict.fromkeys(icaos):
        r = of(icao, doc)
        if r and r.get("kind") in ("ban", "quota") and r.get("from"):
            out.append(f"{icao} — {KIND_RU[r['kind']]} {r['from']}–{r['to']}")
    return out


# ── агент и приёмка ──────────────────────────────────────────────────────

def due(charges_dir: Path, doc: dict, today: date | None = None, limit: int = 8) -> list[dict]:
    """Аэропорты с заведённым тарифом, которых нет в справочнике или проверенные
    больше RECHECK_DAYS назад; адрес тарифа — отправная точка агента."""
    today = today or date.today()
    have = doc.get("airports") or {}
    seen, out = set(), []
    for f in sorted(charges_dir.glob("*-*.json"), reverse=True):
        icao = f.stem.split("-")[0]
        if len(icao) != 4 or icao in seen:
            continue
        seen.add(icao)
        r = have.get(icao)
        if r and (today - date.fromisoformat(str(r.get("checked", "1970-01-01")))).days < RECHECK_DAYS:
            continue
        try:
            d = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            d = {}
        out.append({"icao": icao, "publisher": d.get("publisher") or "—",
                    "url": d.get("source_url") or "", "old": bool(r)})
    out.sort(key=lambda x: x["old"])            # сначала незаведённые
    return out[:limit]


def check(blob: bytes, doc: dict | None = None) -> dict:
    doc = load() if doc is None else doc
    try:
        d = json.loads(blob)
    except ValueError as e:
        return {"rows": [], "error": f"не JSON: {e}", "doubts": []}
    rows = []
    for p in d.get("airports") or []:
        icao = str(p.get("icao") or "").upper()
        r = {"icao": icao, "kind": p.get("kind"), "from": p.get("from"), "to": p.get("to"),
             "where": p.get("where"), "quote": p.get("quote"), "reasons": []}
        rows.append(r)
        if p.get("kind") is None:
            r.update(verdict="skip", reasons=["агент не нашёл"])
            continue
        if not re.fullmatch(r"[A-Z]{4}", icao) or p.get("kind") not in KINDS:
            r.update(verdict="reject", reasons=[f"код не ИКАО или вид не из {KINDS}"])
            continue
        if p["kind"] != "none":
            if not (p.get("from") and p.get("to") and _HHMM.match(str(p["from"])) and _HHMM.match(str(p["to"]))):
                r.update(verdict="reject", reasons=["часы не ЧЧ:ММ"])
                continue
            q = str(p.get("quote") or "")
            for t in (p["from"], p["to"]):
                hh, mm = t.split(":")
                if not re.search(rf"\b0?{int(hh)}[:.h]?{mm}\b|\b{hh}{mm}\b", q):
                    r["reasons"].append(f"{t} нет в цитате")
            c = closed_hours(p)
            if p["kind"] == "ban" and c and c > 10:
                r["reasons"].append(f"запрет {c:g} ч — подозрительно долго")
        if not str(p.get("where") or "").startswith("http"):
            r["reasons"].append("нет адреса страницы")
        if of(icao, doc):
            r["reasons"].append("аэропорт уже есть — запись заменится")
        r["verdict"] = "look" if r["reasons"] else "clean"
    return {"rows": rows, "doubts": [str(x) for x in d.get("doubts") or []]}


def merge(rows: list[dict], path: Path = NIGHT_PATH, today: date | None = None) -> list[str]:
    doc = (yaml.safe_load(path.read_text("utf-8")) or {}) if path.exists() else {}
    head = "".join(ln for ln in path.read_text("utf-8").splitlines(True) if ln.startswith("#")) \
        if path.exists() else ""
    ap = doc.setdefault("airports", {})
    done = []
    for r in rows:
        rec = {"kind": r["kind"]}
        if r["kind"] != "none":
            rec.update({"from": r["from"], "to": r["to"]})
        rec.update({"source": r.get("where"), "quote": str(r.get("quote") or "")[:300],
                    "checked": str(today or date.today())})
        ap[r["icao"]] = rec
        done.append(f"{r['icao']} {KIND_RU[r['kind']]} {r.get('from') or ''}–{r.get('to') or ''}".strip("–"))
    doc["airports"] = dict(sorted(ap.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), "utf-8")
    _CACHE.pop(str(path), None)
    return done
