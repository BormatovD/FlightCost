"""Interpolation of the sample 737-800 / CFM56-7B26 descent table PI.31.7."""

from functools import lru_cache
from pathlib import Path
from typing import NamedTuple


class Descent(NamedTuple):
    altitude_ft: float
    time_min: float
    fuel_kg: float
    distance_nm: float


@lru_cache(maxsize=1)
def _table():
    import numpy as np
    import yaml

    data = yaml.safe_load(Path(__file__).with_name("b738_descent.yaml").read_text())
    return np.array(data["landing_mass_kg"]), np.array(data["rows"]).T


def b738_descent(cruise_alt_ft: float, landing_kg: float,
                 climb_nm_per_ft: float, available_nm: float) -> Descent | None:
    """Select the highest requested/achievable altitude inside the table."""
    import numpy as np

    masses, (alt, minutes, fuel, *distance) = _table()
    if not masses[0] <= landing_kg <= masses[-1] or cruise_alt_ft < alt[0]:
        return None
    i = min(masses.searchsorted(landing_kg, side="right") - 1, len(masses) - 2)
    fraction = (landing_kg - masses[i]) / (masses[i + 1] - masses[i])
    descent_nm = distance[i] + fraction * (distance[i + 1] - distance[i])
    # Both climb and descent distance increase piecewise linearly with altitude.
    required_nm = alt * climb_nm_per_ft + descent_nm
    if available_nm < required_nm[0] or (cruise_alt_ft > alt[-1] and available_nm > required_nm[-1]):
        return None
    level = min(cruise_alt_ft, np.interp(available_nm, required_nm, alt))
    return Descent(level, np.interp(level, alt, minutes), np.interp(level, alt, fuel),
                   np.interp(level, alt, descent_nm))
