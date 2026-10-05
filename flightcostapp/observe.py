"""Накопление наблюдений эксплуатации и свёртка их в факты.

Живой поток отдаёт настоящее, а не прошлое: исторический массив выдаётся
исследователям при университетах, государственным организациям и
авиационным властям, частным лицам — по заявке с рассмотрением. Форма та
же, что у BADA, и рассчитывать на неё нельзя. **Чего не накопили сами —
того потом не будет.**

Поэтому здесь нет ни сети, ни ключей: `collect` принимает готовый список
рейсов от вызывающего. Сбор запускается по расписанию снаружи, а модуль
отвечает за форму, дедупликацию и свёртку. Так его можно проверить без
сети и заменить источник, не трогая контур.

ЧТО ИМЕННО НАБЛЮДАЕТСЯ — см. `OBSERVED_QUANTITY` ниже. Название величины
здесь важнее её значения.
"""

from __future__ import annotations

import json
import statistics
from datetime import date, datetime

from .store import Fact

# Наблюдается время между ПЕРВЫМ и ПОСЛЕДНИМ контактом борта, а не
# блок-время. Разница не терминологическая:
#
#   блок-время   — от снятия колодок до их постановки, счёт эксплуатанта;
#   контакт      — от первой принятой посылки до последней.
#
# На земле приём зависит от того, видит ли аэродром наземный приёмник.
# Где видит, контакт близок к блок-времени; где нет — к времени в воздухе,
# и разница составляет время руления, то есть десятки минут.
#
# Называть это блок-временем нельзя: величина настоящая, из настоящего
# источника, но граница учёта другая. Ровно то, на чём мы обожглись с
# ТОиР в M7, где строка отчёта Ryanair означала только линейное
# обслуживание.
#
# Поэтому вид наблюдения назван по тому, что измерено, а перевод в
# блок-время — отдельный шаг, требующий времени руления (B27, строка 4).
OBSERVED_QUANTITY = {
    "contact_time":  ("мин", "от первого до последнего контакта борта"),
    "airborne_time": ("мин", "контакт без близости к аэродрому хотя бы на одном конце"),
    "ground_time":   ("мин", "движение по земле до вылета или после прилёта"),
    "path_nm":       ("nm", "фактическая длина пути против ортодромии"),
    "level_ft":      ("ft", "занимаемый крейсерский эшелон"),
    "frequency":     ("рейсов", "число рейсов на линии за сутки, ключ содержит дату"),
}

MIN_OBS = 3          # медиана по двум наблюдениям — не медиана


def table_state(store, *, as_of=None, sla_days=None,
                table: str = "observations") -> dict:
    """Что известно о таблице наблюдений — для витрины данных.

    Домен `observed` держит в фактах только агрегаты, а сырое лежит здесь
    (решение 9), и витрина показывала его как «0 фактов». Четыре состояния
    названы отдельно (решение 67): `unknown` — таблицы нет и смотреть
    нечего; `empty` — есть, но забор ни разу не отработал; `stale` —
    последнее наблюдение старше SLA; `live` — копится.

    Просрочка здесь — не устаревшее число, а безвозвратная потеря: прошлое
    поток не отдаёт, и пропущенные сутки не восстанавливаются. Поэтому
    `stale` объясняется именно этим, а не общим «обновить».
    """
    today = date.fromisoformat(str(as_of or date.today()))
    st: dict = {"state": "unknown", "why": "", "count": None,
                "first": None, "latest": None, "age_days": None,
                "sla_days": sla_days}
    has = store.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    if not has:
        st["why"] = f"таблицы {table} в хранилище нет"
        return st
    n, first, last = store.db.execute(
        f"SELECT COUNT(*), MIN(observed_at), MAX(observed_at) FROM {table}").fetchone()
    st.update(count=n, first=first, latest=last)
    if not n:
        st.update(state="empty",
                  why="таблица есть, строк нет: забор ни разу не отработал")
        return st
    st["kinds"] = {r[0]: r[1] for r in store.db.execute(
        f"SELECT kind, COUNT(*) FROM {table} GROUP BY kind ORDER BY kind")}
    st["days"] = store.db.execute(
        f"SELECT COUNT(DISTINCT substr(observed_at, 1, 10)) FROM {table}").fetchone()[0]
    # Пары аэропортов — по частоте: у неё ключ `<пара>/<дата>`, и пара
    # есть у каждого рейса, в отличие от типа.
    st["pairs"] = store.db.execute(
        f"""SELECT COUNT(DISTINCT substr(key, 1, instr(key, '/') - 1))
            FROM {table} WHERE kind = 'frequency' AND instr(key, '/') > 0""").fetchone()[0]
    try:
        st["age_days"] = (today - date.fromisoformat(str(last)[:10])).days
    except ValueError:
        st["age_days"] = None
    if sla_days and st["age_days"] is not None and st["age_days"] > sla_days:
        st.update(state="stale",
                  why=(f"последнее наблюдение {st['age_days']} дн. назад при SLA "
                       f"{sla_days} дн.: пропущенные сутки не восстанавливаются"))
    else:
        st["state"] = "live"
    return st


def collect(store, flights, *, source_id: str, type_of=None) -> dict:
    """Рейсы -> строки наблюдений.

    `flights` — список словарей с полями `icao24`, `callsign`, `dep`, `arr`,
    `first_seen`, `last_seen` и необязательными `near_dep`, `near_arr`,
    `path_nm`, `level_ft`.

    `type_of(icao24)` -> код типа ВС. Без него наблюдение не привязать к
    типу, а привязка к типу — то, ради чего всё делается: 39%
    себестоимости висят на блок-времени ИМЕННО по типу. Борт вещает адрес
    транспондера, не тип; сопоставление приезжает из отдельного реестра.
    Рейсы без известного типа не выбрасываются, а копятся под ключом пары
    аэропортов: длина пути и частота от типа не зависят.
    """
    rows, no_type = [], 0
    for f in flights:
        dep, arr = f.get("dep"), f.get("arr")
        if not dep or not arr or not f.get("first_seen") or not f.get("last_seen"):
            continue
        pair = f"{dep}-{arr}"
        ac = type_of(f["icao24"]) if type_of else None
        no_type += ac is None
        minutes = (f["last_seen"] - f["first_seen"]) / 60.0
        at = datetime.utcfromtimestamp(f["first_seen"]).isoformat(timespec="seconds")
        ref = f.get("icao24")
        base = dict(observed_at=at, source_id=source_id, ref=ref,
                    note=(f.get("callsign") or "").strip() or None)
        # Близость к аэродрому на обоих концах приближает контакт к
        # блок-времени. Это свойство ПРИЁМА, а не рейса, поэтому вид
        # наблюдения разный, а перевод в блок-время — отдельный шаг,
        # которому нужно время руления.
        kind = ("contact_time" if f.get("near_dep") and f.get("near_arr")
                else "airborne_time")
        # Ключ строится по тому, от чего величина ЗАВИСИТ (решение 114).
        # Прежде длина пути ключевалась по типу при известном типе и по
        # паре при неизвестном: ряд делился надвое, меньшая половина
        # отбрасывалась порогом «наблюдений мало», а точка деления ползла
        # по мере наполнения реестра бортов.
        if ac:
            rows.append(dict(kind=kind, key=f"{ac}/{pair}", value=minutes,
                             unit="мин", **base))
        # Частота — счётная величина за сутки, а не медиана единиц. Период
        # стоит в ключе: «рейсов в сутки» и «рейсов в неделю» — разные
        # утверждения, а без периода в поле лежала бы 1,0 (решение 114).
        rows.append(dict(kind="frequency", key=f"{pair}/{at[:10]}",
                         value=1.0, unit="рейсов", **base))
        if f.get("path_nm"):
            # Фактическая длина пути определяется маршрутизацией, не типом.
            rows.append(dict(kind="path_nm", key=pair,
                             value=float(f["path_nm"]), unit="nm", **base))
        if f.get("level_ft") and ac:
            # Эшелон зависит от типа: без типа наблюдение не адресуемо,
            # и писать его под ключом пары значило бы смешать разные
            # величины под одним именем.
            rows.append(dict(kind="level_ft", key=f"{ac}/{pair}",
                             value=float(f["level_ft"]), unit="ft", **base))
    st = store.add_observations(rows)
    st["flights"] = len(flights)
    st["without_type"] = no_type
    # Срок годности имеет смысл только у источника, который сам отмечает
    # своё состояние (решение 113). Накопитель писал строки и молчал, а
    # `refresh` для `kind: custom` уходил в `skipped:no-url` и `last_ok` не
    # ставил: источник с трёхсуточным SLA навсегда показывал `never`, и
    # тревога, задуманная громче остальных, была нема.
    if hasattr(store, "mark_source"):
        store.mark_source(
            source_id, status="ok" if rows else "todo",
            message=(f"рейсов {len(flights)}, строк {st['added']}, "
                     f"дублей {st['duplicate']}, без типа {no_type}")
            if rows else "забор вернул пусто")
    return st


def aggregate(store, kind: str, *, as_of=None, since=None, min_obs=MIN_OBS,
              source_id="observation") -> tuple[list[Fact], list[str]]:
    """Агрегаты в домен `observed`. В `facts` едут только они.

    Число наблюдений кладётся ОБЯЗАТЕЛЬНО: медиана по трём рейсам и по
    тремстам — разные утверждения, а выглядят одинаково.
    """
    as_of = str(as_of or date.today())
    facts, thin = [], []
    unit = OBSERVED_QUANTITY.get(kind, ("", ""))[0]
    for key, n in store.observation_keys(kind, since=since).items():
        vals = store.observation_stats(kind, key, since=since)
        if kind == "frequency":
            # Счётная величина: значение — число рейсов за период, а не
            # медиана единиц. Прежде в поле лежала 1,0 при любом трафике.
            facts.append(Fact(
                domain="observed", key=f"{kind}/{key}", valid_from=as_of,
                value=float(len(vals)), unit=unit, value_text=json.dumps(
                    {"n": len(vals)}, ensure_ascii=False),
                source_id=source_id, extracted_by="observe@2",
                confidence="derived", certainty="exact",
                note=f"{OBSERVED_QUANTITY[kind][1]}, наблюдений {len(vals)}"))
            continue
        if len(vals) < min_obs:
            thin.append(f"{kind}/{key}: наблюдений {len(vals)}, нужно {min_obs}")
            continue
        vals = sorted(vals)
        # При n < 4 квартилей не существует; писать min под именем p25
        # значит называть величину не тем, что она есть.
        q = statistics.quantiles(vals, n=4) if len(vals) >= 4 else None
        facts.append(Fact(
            domain="observed", key=f"{kind}/{key}", valid_from=as_of,
            value=round(statistics.median(vals), 3), unit=unit,
            value_text=json.dumps(
                {"n": len(vals), "min": round(vals[0], 3),
                 "max": round(vals[-1], 3),
                 **({"p25": round(q[0], 3), "p75": round(q[2], 3)} if q else {})},
                ensure_ascii=False),
            source_id=source_id, extracted_by="observe@1",
            confidence="derived",      # посчитано нами из наблюдений, не списано
            certainty="exact",
            note=f"{OBSERVED_QUANTITY.get(kind, ('', kind))[1]}, наблюдений {len(vals)}"))
    return facts, thin
