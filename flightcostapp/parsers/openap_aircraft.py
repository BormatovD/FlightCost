"""Справочник воздушных судов.

Три разных вида знания, которые нельзя держать в одном домене.

**1. Физика и сертификат — домен `aircraft`.**
Взлётная масса, размах, длина, кресла, двигатель. Объективные величины,
их не выбирают. Приезжают из openap детерминированным парсером, 37 типов.
Провенанс `exact`.

**2. Классификация у оператора аэропорта — домен `aircraft_billing`.**
Категория шума во Франкфурте, группа стоянки, класс наземного
обслуживания, группа перрона в Вене. Это не свойство самолёта, а решение
конкретного аэропорта о том, в какую строку тарифа его поместить. Часть
выводится из физики (группа стоянки — из размаха и длины), часть только
таблицей из документа.

**3. Экономика эксплуатации — домен `fleet_economics`.**
Лизинг, ТОиР, экипаж. Это НЕ факты, а допущения, и они зависят от
перевозчика: A320 у сетевого и у лоукостера стоят по-разному. Ключ
`<перевозчик>/<тип>` с запасным `*/<тип>`. Провенанс `estimated`,
пользователь переопределяет.

Смешивать их — та же ошибка, что держать ставку сбора и признак движения
в одной строке: величины разного происхождения требуют разной проверки.
"""

from __future__ import annotations

from ..categories import code_letter
from ..store import Fact

# Группы стоянки Франкфурта (Anhang 3) жили здесь таблицей FRA_STAND и
# писались фактом `fra_stand_group`, у которого не было читателя (решение
# 101): расчёт брал группу из `--set`, а без него статья стоянки пропадала.
# Знание аэропорта в парсере ТИПА — не на своём месте. Таблица переехала в
# раздел `categories.stand_group` файла тарифа Франкфурта.


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    """blob не используется: источник — установленный пакет openap.

    Формально это тоже внешний источник, просто поставляемый через pip.
    Версия пакета фиксируется в артефакте, поэтому обновление openap
    пройдёт через тот же гейт, что и обновление любого файла.
    """
    import openap

    day = ctx.get("today") or ""
    facts: list[Fact] = []
    for t in sorted(openap.prop.available_aircraft()):
        icao = t.upper()
        try:
            a = openap.prop.aircraft(t)
        except Exception:                              # noqa: BLE001
            continue
        span = float(a["wing"]["span"])
        length = float(a["fuselage"]["length"])
        eng = a.get("engine", {})
        fields = {
            "mtow_t": a["mtow"] / 1000.0,
            "oew_t": a["oew"] / 1000.0,
            "mlw_t": a["mlw"] / 1000.0,
            "fuel_capacity_t": a["mfc"] / 1000.0,
            "seats_max": float(a["pax"]["max"]),
            "seats_typical": float(a["pax"]["high"]),
            "span_m": span,
            "length_m": length,
            "cruise_mach": float(a["cruise"]["mach"]),
            "cruise_alt_m": float(a["cruise"]["height"]),
            "engine_count": float(eng.get("number", 2)),
        }
        for name, value in fields.items():
            facts.append(Fact(
                domain="aircraft", key=f"{icao}/{name}", valid_from=day,
                value=value, unit=name.rsplit("_", 1)[-1],
                source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
                extracted_by="parser:openap_aircraft@1",
                confidence="exact",
                note=a["aircraft"],
            ))
        # Буква кода ИКАО по размаху — выведенная величина, одна функция на
        # проект (categories.code_letter). Факт — ради витрины и сверки;
        # правила категорий считают её сами и для своих типов тоже.
        letter = code_letter(span)
        if letter:
            facts.append(Fact(
                domain="aircraft", key=f"{icao}/code_letter", valid_from=day,
                value_text=letter, unit="буква", source_id=ctx["source_id"],
                artifact_sha=ctx.get("sha"), extracted_by="parser:openap_aircraft@2",
                confidence="derived", note="Приложение 14, табл. 1-1: по размаху"))
        facts.append(Fact(
            domain="aircraft", key=f"{icao}/engine", valid_from=day,
            value_text=str(eng.get("default", "")), unit="designator",
            source_id=ctx["source_id"], artifact_sha=ctx.get("sha"),
            extracted_by="parser:openap_aircraft@1", confidence="exact",
            note="нужен для эмиссионного сбора: ключ к базе ICAO EEDB",
        ))
    if len({f.key.split("/")[0] for f in facts}) < 20:
        raise ValueError("типов меньше двадцати — openap не установлен или урезан")
    return facts
