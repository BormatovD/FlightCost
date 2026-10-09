"""Право летать пару: свободы воздуха и закрытия неба (решение 156).

Сеть режется правами раньше, чем дальностью. Два слоя:

  * **Структура Чикагской системы** — правило, а не данные: чужой каботаж
    закрыт (ст. 7 Чикагской конвенции), рейс между двумя чужими странами —
    седьмая свобода, по умолчанию не предполагается. Исключение — общий
    авиарынок ЕС: перевозчик ЕС летает между любыми его аэропортами.
    Третья и четвёртая свободы (из своей страны и обратно) считаются
    доступными: двусторонние соглашения здесь не проверяются, и отчёт
    говорит это вслух.
  * **Закрытия** — данные с датой и документом (`data/rights/closures.yaml`):
    вводят и снимают их государства, код этого не знает.

Национальность перевозчика — страна его базы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

CLOSURES_PATH = Path(__file__).resolve().parents[1] / "data" / "rights" / "closures.yaml"

# Общий авиарынок: ЕС по Регламенту 1008/2008, ЕЭЗ и Швейцария по
# соглашениям с ЕС. Перевозчик отсюда летает между любыми его аэропортами.
COMMON_MARKET = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO "
    "SK SI ES SE NO IS LI CH".split())


@dataclass
class Closure:
    id: str
    title: str
    carriers: frozenset          # ISO-2 или "*"
    countries: frozenset
    zones: tuple                 # префиксы ИКАО
    valid_from: str
    valid_to: str | None
    source: str
    url: str = ""
    certainty: str = "exact"
    confirm_by: str = ""

    def active(self, as_of: str) -> bool:
        return self.valid_from <= as_of and (self.valid_to is None or as_of < self.valid_to)

    def applies_to(self, carrier: str) -> bool:
        return "*" in self.carriers or carrier in self.carriers

    def zone_hit(self, zone: str) -> bool:
        return any(zone.startswith(p) for p in self.zones)


@dataclass
class Verdict:
    """Можно ли перевозчику этой страны летать пару — и если нет, почему.

    Причина — словарь, а не строка: у закрытия есть адрес, документ и
    достоверность, и отчёту нужны они, а не пересказ.
    """
    ok: bool
    reasons: list = field(default_factory=list)


def _expand(items, groups) -> list[str]:
    out = []
    for x in items or []:
        x = str(x)
        if x.startswith("@"):
            if x[1:] not in groups:
                raise ValueError(f"группа {x} не описана в groups")
            out += [str(y) for y in groups[x[1:]]]
        else:
            out.append(x)
    return out


def load_closures(path: Path | None = None, data: dict | None = None) -> list[Closure]:
    if data is None:
        import yaml
        p = Path(path or CLOSURES_PATH)
        if not p.exists():
            # Пустой список здесь значил бы «закрытий нет» — а это
            # утверждение о мире, которого никто не делал (решение 67).
            raise FileNotFoundError(f"нет файла закрытий {p}")
        with p.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    groups = data.get("groups") or {}
    out = []
    for c in data.get("closures") or []:
        for need in ("id", "carriers", "valid_from", "source"):
            if not c.get(need):
                raise ValueError(f"закрытие {c.get('id', '?')}: нет поля {need}")
        out.append(Closure(
            id=c["id"], title=c.get("title", c["id"]),
            carriers=frozenset(_expand(c["carriers"], groups)),
            countries=frozenset(_expand(c.get("countries"), groups)),
            zones=tuple(_expand(c.get("zones"), groups)),
            valid_from=str(c["valid_from"]),
            valid_to=str(c["valid_to"]) if c.get("valid_to") else None,
            source=c["source"], url=c.get("url", ""),
            certainty=c.get("certainty", "exact"),
            confirm_by=c.get("confirm_by", "")))
    return out


def _reason(kind: str, text: str, cl: Closure | None = None) -> dict:
    r = {"kind": kind, "text": text}
    if cl:
        r.update(id=cl.id, source=cl.source, url=cl.url,
                 certainty=cl.certainty, confirm_by=cl.confirm_by)
    return r


def pair_rights(carrier: str, ca: str, cb: str, as_of: str | date,
                closures: list[Closure]) -> Verdict:
    """Свободы воздуха и закрытия посадки. Пролёт — `closed_zones`."""
    as_of = str(as_of)
    carrier, ca, cb = carrier.upper(), ca.upper(), cb.upper()
    reasons = []
    if carrier not in (ca, cb):
        common = carrier in COMMON_MARKET and ca in COMMON_MARKET and cb in COMMON_MARKET
        if not common:
            if ca == cb:
                reasons.append(_reason(
                    "cabotage", f"каботаж в {ca}: перевозки внутри чужой страны "
                    f"закрыты (ст. 7 Чикагской конвенции)"))
            else:
                reasons.append(_reason(
                    "seventh_freedom", f"чужие страны на обоих концах "
                    f"({ca}–{cb}): пятая или седьмая свобода, по умолчанию "
                    f"не предполагается"))
    for cl in closures:
        if not (cl.active(as_of) and cl.applies_to(carrier)):
            continue
        hit = sorted({ca, cb} & cl.countries)
        if hit:
            reasons.append(_reason(
                "landing_ban", f"{cl.title} ({', '.join(hit)}), с {cl.valid_from}", cl))
    return Verdict(ok=not reasons, reasons=reasons)


def closed_zones(carrier: str, zones, as_of: str | date,
                 closures: list[Closure]) -> list[dict]:
    """Какие зоны пути закрыты для пролёта этому перевозчику."""
    as_of, carrier = str(as_of), carrier.upper()
    out = []
    for cl in closures:
        if not (cl.active(as_of) and cl.applies_to(carrier)):
            continue
        hit = sorted(z for z in zones if cl.zone_hit(z))
        if hit:
            out.append(_reason(
                "overflight_ban", f"путь через {', '.join(hit)}: {cl.title}", cl))
    return out
