"""Забор рейсов из OpenSky и приведение их к форме `observe.collect`.

Сети в контуре нет намеренно: функция `fetch` передаётся снаружи, чтобы
модуль проверялся без сети и чтобы источник можно было заменить, не трогая
накопление.

Доступ на 2026-09: анонимный работает с пониженными лимитами; учётная
запись даёт 4000 запросных единиц в сутки, активный участник сети — 8000.
С 18 марта 2026 программный доступ по учётной записи идёт через OAuth2,
пароль больше не принимается. Исторический массив через Trino выдаётся
исследователям при университетах, государственным организациям и
авиавластям; частным лицам — по заявке. Поэтому копим сами.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

BASE = "https://opensky-network.org/api"

# ОКНО — РОВНО СУТКИ UTC, без перекрытия. Так было не всегда, и причина
# смены важнее самой правки.
#
# Раньше окно бралось с перекрытием в два часа с обеих сторон: считалось,
# что рейс, начавшийся до полуночи и закончившийся после, иначе теряется
# на границе. Опасение оказалось ложным для ЭТИХ эндпоинтов: `departure`
# отбирает рейсы по времени ВЫЛЕТА, `arrival` — по времени ПРИЛЁТА, и
# рейс через полночь попадает в сутки своего события целиком. Терять было
# нечего, а перекрытие давало 28-часовое окно, пересекающее три суточных
# раздела, — и сервер отвечал отказом:
#
#   HTTP 400: You can only query across 2 partitions (days).
#
# Гарантия отсутствия дыры теперь не в перекрытии, а в том, что вылеты и
# прилёты забираются раздельно и объединение покрывает всё. Дедупликация
# в `store.add_observations` остаётся: наш рейс между двумя нашими же
# аэропортами приходит дважды — вылетом и прилётом.
MAX_PARTITIONS = 2          # ограничение API, а не наше решение


def windows(day, *, overlap_h: int = 0) -> tuple[int, int]:
    """Начало и конец окна в секундах эпохи.

    `overlap_h` оставлен параметром, но по умолчанию нулевой и проверяется:
    окно, пересекающее больше двух суточных разделов, сервер отвергает, и
    узнать об этом на двадцать восьмом аэропорту дороже, чем здесь.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    a = start - timedelta(hours=overlap_h)
    b = start + timedelta(days=1, hours=overlap_h)
    days = len({(a + timedelta(hours=h)).date()
                for h in range(0, int((b - a).total_seconds() // 3600) + 1)})
    if days > MAX_PARTITIONS:
        raise ValueError(
            f"окно {a:%Y-%m-%d %H:%M} … {b:%Y-%m-%d %H:%M} пересекает {days} "
            f"суточных раздела, а сервер принимает не больше "
            f"{MAX_PARTITIONS}. Уменьшите overlap_h")
    return int(a.timestamp()), int(b.timestamp())


def pull(fetch, airports, day, *, kind: str = "departure",
         give_up_after: int = 3, budget=None, floor: int = 0) -> tuple[list[dict], list[str], str | None,
                                          list[str]]:
    """Рейсы по списку аэропортов за сутки.

    `fetch(url) -> list[dict]` — вызывающий отвечает за авторизацию,
    паузы между запросами и повторы. Ошибка одного аэропорта не роняет
    остальные: пропуск одного дня по одному аэропорту невосстановим, но
    пропуск всех — хуже.
    """
    begin, end = windows(day)
    out, failed, ok = [], [], []
    streak = 0
    for icao in airports:
        # Останавливаемся САМИ, пока бюджет ещё есть. Дожидаться отказа
        # значит тратить остаток на обращения, которые вернут 429, и
        # оставлять следующий прогон без запаса на повтор.
        left = budget() if budget else None
        if left is not None and left < floor:
            return out, failed, (f"бюджет на исходе: осталось {left} кредитов, "
                                 f"забрано {len(ok)} из {len(airports)}"), ok
        url = f"{BASE}/flights/{kind}?airport={icao}&begin={begin}&end={end}"
        try:
            rows = fetch(url) or []
            streak = 0
            ok.append(icao)
        except Exception as exc:                       # noqa: BLE001
            if getattr(exc, "code", None) == 429:
                streak += 1
                failed.append(f"{icao}: {_why(exc)}")
                if streak >= give_up_after:
                    # Три подряд — не совпадение, а исчерпанный лимит.
                    # Перебирать дальше бессмысленно: тридцать шесть
                    # обречённых обращений ничего не дадут и могут
                    # продлить запрет.
                    #
                    # Но УЖЕ ЗАБРАННОЕ возвращается, а не выбрасывается.
                    # Первая редакция бросала исключение, и вместе с ним
                    # терялись успешные аэропорты этого прохода — то есть
                    # невосстановимые сутки, ради спасения которых всё и
                    # затевалось. Исключение для потока управления тут
                    # ровно тем и плохо: оно уносит контекст.
                    left = airports[airports.index(icao):]
                    halted = (f"лимит исчерпан на {icao}: забрано "
                              f"{len(ok)} из {len(airports)} аэропортов, "
                              f"осталось {len(left)}")
                    return out, failed, halted, ok
                continue
            # Имя класса исключения не диагноз: `HTTPError` одинаково
            # означает и «нет прав», и «слишком часто», и «нет данных».
            # Двадцать восемь строк «HTTPError» не говорят ничего, а
            # выглядят как отчёт. Код и первая строка тела — говорят.
            failed.append(f"{icao}: {_why(exc)}")
            continue
        for r in rows:
            dep = r.get("estDepartureAirport")
            arr = r.get("estArrivalAirport")
            if not dep or not arr or dep == arr:
                continue
            out.append({
                "icao24": (r.get("icao24") or "").strip(),
                "callsign": (r.get("callsign") or "").strip(),
                "dep": dep, "arr": arr,
                "first_seen": r["firstSeen"], "last_seen": r["lastSeen"],
                # Признак земли эндпоинт не отдаёт. Близость первого
                # контакта к аэродрому вылета — косвенный признак, и
                # выдавать его за наблюдение земли нельзя: расстояние до
                # полосы у OpenSky в полях estDepartureAirportHorizDistance.
                "near_dep": _near(r, "Departure"),
                "near_arr": _near(r, "Arrival"),
            })
    return out, failed, None, ok


def _near(row, side: str, metres: int = 3000) -> bool:
    d = row.get(f"est{side}AirportHorizDistance")
    return d is not None and d <= metres


def _why(exc: Exception) -> str:
    """Причина отказа так, чтобы по ней можно было действовать."""
    code = getattr(exc, "code", None)
    if code is None:
        return f"{type(exc).__name__}: {exc}"
    body = ""
    try:
        body = (exc.read() or b"")[:120].decode("utf-8", "replace").strip()
    except Exception:                                  # noqa: BLE001
        pass
    hint = {
        401: "нужны ключи: эндпоинт рейсов анонимно не отдаётся",
        403: "доступ запрещён: ключи есть, но прав на этот запрос нет",
        429: "слишком часто: поднимите --pause или ждите суток",
        404: "нет данных за окно",
    }.get(code, "")
    return f"HTTP {code}" + (f" — {hint}" if hint else "") + (f" [{body}]" if body else "")
