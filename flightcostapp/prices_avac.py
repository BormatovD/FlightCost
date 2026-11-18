"""Проверка ячеек двух таблиц AVAC для четырёх типов, без сетевого запроса."""

import re


_PERIODS = {
    "https://aviationstrategy.aero/newsletter/Nov-2019/5/Jet-Values-and-Lease-Rates": "2019-10",
    "https://aviationstrategy.aero/newsletter/Oct-2020/4/Jet-Values-and-Lease-Rates": "2020-10",
}
_MODELS = {"A320": "A320-200", "B738": "737-800", "A359": "A350-900", "B789": "787-9"}
_AGES = ("new", 5, 10, 20)
_ISSUE_MONTHS = {"2019-10": ("2019-11",), "2020-10": ("2020-10", "2020-11")}
_BASES = {"value": "market_value_condition_unspecified", "lease": "market_monthly_lease"}
_USD_SCALE = {"value": 1_000_000, "lease": 1_000}

# Jet Values (USD млн) и Jet Lease Rates (USD тыс./месяц), столбцы New/5/10/20.
# § = HGW. Отдельный знак относится ко всей строке, знак в ячейке — только к ней.
# Сверено с обеими страницами _PERIODS и с проверенными строками B738/A359/B789
# в research/aircraft-prices-2026-11/out/history_source_observations.json.
_ROWS = {
    "2019-10": {
        ("A320", "value"): ("§", ("42.8", "32.1", "21.4", "")),
        ("A320", "lease"): ("§", ("312", "255", "200", "")),
        ("B738", "value"): ("§", ("44.9", "34.2", "27.8", "9.5")),
        ("B738", "lease"): ("§", ("339", "278", "243", "145")),
        ("A359", "value"): ("", ("150.0", "98.4", "", "")),
        ("A359", "lease"): ("", ("1172", "887", "", "")),
        ("B789", "value"): ("", ("146.9", "97.2", "", "")),
        ("B789", "lease"): ("", ("1100", "827", "", "")),
    },
    "2020-10": {
        ("A320", "value"): ("§", ("32.5", "25.0", "17.5", "7.9")),
        ("A320", "lease"): ("§", ("208", "177", "144", "114")),
        ("B738", "value"): ("", ("33.1", "26.0", "14.8§", "8.3§")),
        ("B738", "lease"): ("", ("215", "183", "131§", "115§")),
        ("A359", "value"): ("", ("110.5", "80.2", "", "")),
        ("A359", "lease"): ("", ("789", "620", "", "")),
        ("B789", "value"): ("", ("107.7", "79.1", "", "")),
        ("B789", "lease"): ("", ("724", "598", "", "")),
    },
}
_MODEL = re.compile(
    r"(?<!\w)(?:" + "|".join(model.replace("-", r"\s*[-–—−]\s*") for model in _MODELS.values()) + r")(?!\w)",
    re.I,
)
_CELL = re.compile(r"[\s|,:]*`?(\d+(?:,\d{3})*(?:\.\d+)?)(?:\s*([§†‡♯∞]))?(?![\w–—−-]|[.,]\d)")
_ROW_SPEC = re.compile(r"^[\s|]*(?:(\([A-Z]{3}\)|\b(?:HGW|IGW|LGW)\b|[§†‡♯∞])"
                       r"(?:\s*\(([A-Z]{3})\))?)?", re.I)
_CELL_AGE = re.compile(r"^[\s|,]*(?:\(\s*)?(new|[0-9]+\s*(?:yrs?\.?|years?(?:\s+old)?))\s*\)?[ :]+", re.I)
_HEADING = re.compile(r"\bJet\s+(values|lease\s+rates)\b(?:\s*\(([^)]*)\))?", re.I)
_QUOTED_PERIOD = re.compile(r"\b(?:end[-\s]+)?October\s+(20\d{2})\b", re.I)
_CONTRADICTORY_UNITS = {"value": r"000|\bthousands?\b|\bmonth", "lease": r"(?<=\$)m\b|\bmillions?\b"}


def _label(s: str) -> str:
    """Сравнение названий типа независимо от регистра, тире и пробелов."""
    return re.sub(r"[^a-z0-9§†‡♯∞]", "", re.sub(r"^(airbus|boeing)\s+", "", s.strip(), flags=re.I).lower())


def _quote_cells(tail: str) -> list[tuple[float, str]]:
    cells = []
    while match := _CELL.match(tail):
        cells.append((float(match[1].replace(",", "")), match[2] or ""))
        tail = tail[match.end():]
    return cells


def source_cell(row: dict, amounts: tuple[float, float]) -> tuple | None:
    """Вернуть ключ проверенной ячейки. Для других источников действует общая проверка."""
    source = row.get("source") or ""
    period = _PERIODS.get(source)
    quote = row.get("quote") or ""
    model = _MODEL.search(quote)
    icao = str(row.get("icao") or "").upper()
    if period is None:
        avac_attribution = " ".join(str(row.get(k) or "") for k in ("source_family", "publisher"))
        avac_url = re.match(r"https?://(?:www\.)?aviationstrategy\.aero/newsletter/[^?#]+/jet-values-and-lease-rates",
                            source, re.I)
        if model and (avac_url or re.search(r"\bAVAC\b", avac_attribution, re.I)):
            tail = quote[model.end():]
            cells = _quote_cells(tail[_ROW_SPEC.match(tail).end():])
            if len(cells) > 1 or (cells and "§" in tail):
                raise ValueError("источник строки AVAC отсутствует в проверенном снимке таблиц")
        return None
    if icao not in _MODELS:
        if model:
            raise ValueError("тип не соответствует строке проверенной таблицы AVAC")
        return None

    kind, age = row.get("kind"), row.get("age")
    if age == 0 and not isinstance(age, bool):
        age = "new"
    if kind not in _USD_SCALE or age not in _AGES or str(row.get("month")) != period:
        raise ValueError("период, вид и возраст должны соответствовать таблице AVAC")
    if row.get("published_on") and row["published_on"][:7] not in _ISSUE_MONTHS[period]:
        raise ValueError("дата публикации не соответствует месяцу выпуска AVAC")
    if row.get("valuation_basis") not in (None, "", _BASES[kind]):
        raise ValueError("основание оценки не соответствует таблице AVAC")

    row_flag, raw_cells = _ROWS[period][icao, kind]
    i = _AGES.index(age)
    raw = raw_cells[i]
    if not raw or "value" not in row or (row.get("currency") or "USD").upper() != "USD":
        raise ValueError("ожидается опубликованная скалярная ячейка AVAC в USD")
    cell_value = float(raw.rstrip("§"))
    expected_usd = round(cell_value * _USD_SCALE[kind])
    if amounts != (expected_usd, expected_usd):
        raise ValueError("сумма с учётом единиц не совпадает с ячейкой возраста в таблице AVAC")

    model_label = _label(_MODELS[icao])
    hgw = bool(row_flag or raw.endswith("§"))
    permitted = {"", model_label}
    if hgw:
        for specification in ("hgw", "§", "§hgw", "hgw§"):
            permitted.update({specification, model_label + specification})
    if _label(row.get("variant") or "") not in permitted:
        raise ValueError("модификация не совпадает с обозначением ячейки AVAC")
    if model is None or _label(model[0]) != model_label:
        raise ValueError("в цитате AVAC отсутствует нужная строка типа")

    header_text = quote[:model.start()]
    heading = _HEADING.search(header_text)
    quoted_period = _QUOTED_PERIOD.search(header_text)
    if heading and ("value" if heading[1].lower() == "values" else "lease") != kind:
        raise ValueError("заголовок в цитате указывает на другой вид таблицы AVAC")
    if re.search(r"[€£]|\b(?:EUR|GBP)\b", header_text, re.I) or (
        heading and re.search(_CONTRADICTORY_UNITS[kind], heading[2] or "", re.I)
    ):
        raise ValueError("единицы в цитате не совпадают с таблицей AVAC")
    if quoted_period and quoted_period[1] != period[:4]:
        raise ValueError("период в цитате не совпадает с выпуском AVAC")
    tail = quote[model.end():]
    spec = _ROW_SPEC.match(tail)
    if spec[1] and (not hgw or _label(spec[1]) not in ("§", "hgw") or _label(spec[2] or "") not in ("", "hgw")):
        raise ValueError("обозначение в цитате не совпадает с ячейкой AVAC")
    tail = tail[spec.end():]
    age_match = _CELL_AGE.match(tail)
    if age_match:
        age_label = age_match[1].lower()
        quoted_age = "new" if age_label == "new" else int(age_label.split()[0])
        if quoted_age != age:
            raise ValueError("возраст в цитате не совпадает со столбцом AVAC")
        tail = tail[age_match.end():]
    quoted = _quote_cells(tail)
    published = [(float(c.rstrip("§")), "§" if c.endswith("§") else "") for c in raw_cells if c]
    for start in range(i + 1):
        end = start + len(quoted)
        if start <= i < end <= len(published) and (not age_match or start == i):
            if all(q == v and (not mark or mark == cell_flag)
                   for (q, mark), (v, cell_flag) in zip(quoted, published[start:end])):
                return ("AVAC", source, icao, kind, period, age, hgw, _BASES[kind], expected_usd)
    raise ValueError("ячейка возраста отсутствует в цитате строки AVAC")
