"""Формулы сбора за аэронавигацию.

Формула `(D_км / 100) · √(MTOW / 50)` — это правило EUROCONTROL, а не
устройство мира. За пределами его зоны считают иначе:

    Казахстан   T · S/100          — без множителя по массе вовсе
    США         D_nm/100 · ставка  — и только для пролётных рейсов;
                                     внутренние за аэронавигацию не платят,
                                     она финансируется налогами
    прочие      от плоской платы за пролёт до платы за тонно-километр

Поэтому формула — данные, а не код. Ровно тот же приём, что с
аэропортовыми сборами: закрытый словарь способов, ставки отдельно.
Добавление государства становится строкой в справочнике, а не правкой
расчёта.

Словарь намеренно короткий. Если для очередной страны понадобится новый
способ, это повод посмотреть на документ внимательно: скорее всего он
выражается через уже имеющиеся.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import math

NM_TO_KM = 1.852


@dataclass
class Formula:
    """Обобщённая форма сбора за пролёт зоны.

        сумма = ставка · (D / d_div) ^ d_exp · (MTOW / m_div) ^ m_exp

    Шесть прежних именованных способов оказались частными случаями одного.
    Проверка на реальных документах: EUROCONTROL берёт d_div=100 км и
    m_div=50 т при показателе 0.5, Таиланд — те же показатели, но d_div=250
    км, Китай считает за километр без учёта массы, Россия — по полосам
    массы за вход в зону независимо от расстояния.

    Держать под каждую страну отдельную функцию значило бы править код при
    каждом новом государстве. Три числа и единица измерения покрывают
    почти всё, что встречается.
    """

    d_div: float = 100.0        # делитель расстояния
    d_unit: str = "km"          # km | nm
    d_exp: float = 1.0          # 0 — расстояние не влияет
    m_div: float = 50.0         # делитель массы, тонны
    m_exp: float = 0.5          # 0 — масса не влияет
    bands: list = field(default_factory=list)   # полосы массы: (до_т, ставка)
    note: str = ""

    def amount(self, dist_nm: float, mtow_t: float, rate: float) -> float:
        if self.bands:
            # Полосы задают саму ставку, а не множитель: так считает Россия
            # и ряд государств Азии — плоский сбор за вход по классу массы.
            rate = next((r for lim, r in self.bands if mtow_t <= lim),
                        self.bands[-1][1])
        d = dist_nm * (NM_TO_KM if self.d_unit == "km" else 1.0)
        f_d = (d / self.d_div) ** self.d_exp if self.d_exp else 1.0
        f_m = (mtow_t / self.m_div) ** self.m_exp if self.m_exp else 1.0
        return rate * f_d * f_m


PRESETS = {
    # 41 государство зоны EUROCONTROL и согласованные с ним
    "eurocontrol":   Formula(100.0, "km", 1.0, 50.0, 0.5,
                             note="(D_км/100) · √(MTOW/50)"),
    # Казахстан, Китай: ставка за расстояние, масса не входит
    "distance_only": Formula(100.0, "km", 1.0, 1.0, 0.0,
                             note="(D_км/100), без учёта массы"),
    # США, Канада: пролётный сбор за морские мили
    "per_100nm":     Formula(100.0, "nm", 1.0, 1.0, 0.0,
                             note="(D_миль/100), без учёта массы"),
    # Таиланд: та же форма, что EUROCONTROL, но делитель расстояния 250 км
    "thailand":      Formula(250.0, "km", 1.0, 50.0, 0.5,
                             note="√(MTOW/X) · D_км/250"),
    "tonne_km":      Formula(1.0, "km", 1.0, 1.0, 1.0, note="D_км · MTOW"),
    "flat":          Formula(1.0, "km", 0.0, 1.0, 0.0,
                             note="плоская плата за пролёт зоны"),
    "none":          Formula(1.0, "km", 0.0, 1.0, 0.0,
                             note="сбор не взимается"),
}

FORMULA_RU = {k: v.note for k, v in PRESETS.items()}
FORMULA_RU["mtow_bands"] = "плоский сбор за вход по полосе массы"


# Способ по умолчанию — для зон, о которых ничего не известно. Выбран
# eurocontrol, потому что 41 государство считает именно так, и потому что
# для незнакомой зоны лучше ошибиться в знакомую сторону, чем не начислить
# ничего. Пробел при этом всё равно виден: ставки-то нет.
DEFAULT_FORMULA = "eurocontrol"


def charge(dist_nm: float, mtow_t: float, rate: float,
           formula: str = DEFAULT_FORMULA, cfg: dict | None = None) -> float:
    """Сбор за пролёт зоны.

    `formula` — имя готовой формы или `custom`, если параметры заданы в
    `cfg`: делители, показатели и полосы. Новая страна становится записью
    в справочнике, а не правкой кода.
    """
    if formula == "none":
        return 0.0
    if cfg and (formula == "custom" or any(
            k in cfg for k in ("d_div", "m_exp", "bands", "d_unit"))):
        f = Formula(**{k: v for k, v in cfg.items()
                       if k in Formula.__dataclass_fields__})
        return f.amount(dist_nm, mtow_t, rate)
    f = PRESETS.get(formula)
    if f is None:
        raise ValueError(f"неизвестный способ расчёта: {formula!r}; "
                         f"допустимые: {', '.join(sorted(PRESETS))} или custom")
    return f.amount(dist_nm, mtow_t, rate)
