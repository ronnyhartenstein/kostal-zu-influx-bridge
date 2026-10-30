import math
from typing import Dict, List, Optional, Tuple

from decoders import DecodedPoint

_FROM_WATT = 0.001
_SOC_TO_CAPACITY = 0.095

# site_name -> (Bridge-Punkt, Faktor). Formatgleich zu den alten NodeRED-Reihen in haus.strom.
LEGACY_SERIES: Dict[str, Tuple[str, float]] = {
    "pv_production": ("ac_wirkleistung_gesamt_w", _FROM_WATT),
    "own_use_from_pv": ("hausverbrauch_pv_w", _FROM_WATT),
    "own_use_from_battery": ("hausverbrauch_batterie_w", _FROM_WATT),
    "own_use_from_grid": ("hausverbrauch_netz_w", _FROM_WATT),
    "total_power": ("netzleistung_gesamt_w", _FROM_WATT),
    # NodeRED liest hier ebenfalls Register 252, für den Verlauf beibehalten.
    "total_home_consumption": ("netzleistung_gesamt_w", _FROM_WATT),
    "battery_capacity": ("batterie_soc_prozent_int", _SOC_TO_CAPACITY),
}


def _convert(raw: object, factor: float) -> Optional[float]:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if not math.isfinite(raw):
        return None
    return round(float(raw) * factor, 4)


def legacy_values(points: List[DecodedPoint]) -> Dict[str, float]:
    by_name = {p.point: p.value for p in points if p.model == "flat"}

    values: Dict[str, float] = {}
    for site_name, (point, factor) in LEGACY_SERIES.items():
        value = _convert(by_name.get(point), factor)
        if value is not None:
            values[site_name] = value
    return values
