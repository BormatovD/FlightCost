"""Standard-atmosphere cruise fuel flow for the 737-800 / CFM56-7B26."""

from bisect import bisect_left, bisect_right
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _table():
    import yaml

    data = yaml.safe_load(Path(__file__).with_name("b738_cruise.yaml").read_text())
    rows = data["flow_per_engine"]
    return data["mass_kg"], sorted(rows), rows


def b738_cruise_reference(alt_ft: float, mass_kg: float) -> float | None:
    """Both engines, kg/h at M.79. Interpolate only between published cells."""
    import numpy as np

    masses, levels, rows = _table()
    if not levels[0] <= alt_ft <= levels[-1]:
        return None
    lower = bisect_right(levels, alt_ft) - 1
    upper = bisect_left(levels, alt_ft)
    bracket = levels[lower:upper + 1]
    flows = []
    for level in bracket:
        row = rows[level]
        if not masses[0] <= mass_kg <= masses[len(row) - 1]:
            return None
        flows.append(np.interp(mass_kg, masses[:len(row)], row))
    return float(2 * np.interp(alt_ft, bracket, flows))


def cruise_flow_kg_h(flow, use_boeing: bool, mass: float, tas: float,
                     alt: float) -> tuple[float, bool]:
    """Keep OpenAP's local speed response around the published M.79 datum."""
    actual = flow.enroute(mass=mass, tas=tas, alt=alt) * 3600
    if use_boeing:
        from openap import aero

        # Apply the fixed-Mach table only to speeds that round to its M.79.
        mach = aero.tas2mach(tas * aero.kts, alt * aero.ft)
        if 0.785 <= mach < 0.795:
            reference = b738_cruise_reference(alt, mass)
            if reference is not None:
                tas_79 = aero.mach2tas(0.79, alt * aero.ft) / aero.kts
                at_79 = flow.enroute(mass=mass, tas=tas_79, alt=alt) * 3600
                return reference * (actual / at_79), True
    return actual, False
