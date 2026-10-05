"""Заглушка парсера 'fuel_monitor'.

Источник не разобран: адрес указан на страницу IATA, а отдаёт ли она
число в разбираемом виде — не проверено. Возможной заменой стоит
рассмотреть биржевые котировки авиакеросина, они заведомо машиночитаемы.
"""

from __future__ import annotations

from ..store import Fact


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    raise NotImplementedError(
        "парсер цены топлива не написан; источник не проверен")
