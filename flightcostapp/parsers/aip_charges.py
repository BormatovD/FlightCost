"""Заглушка парсера 'aip_charges' — контракт задан, реализация по мере надобности."""

from __future__ import annotations

from ..store import Fact


def parse(blob: bytes, ctx: dict) -> list[Fact]:
    raise NotImplementedError("parser 'aip_charges' not implemented yet")
