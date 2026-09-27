"""Size pick up, concentration stability and glue make up arithmetic."""

from typing import Sequence

from .recipe import IN_BAND, LEAN, RICH


def pick_up(roll_speed: float, stock_speed: float) -> float:
    """Fraction of stock speed the sizing roll carries away."""
    if stock_speed <= 0:
        return 0.0
    return float(roll_speed) / float(stock_speed)


def dose(flow: float, width: float, speed: float) -> float:
    """Glue add on per square metre."""
    area = float(width) * float(speed)
    if area <= 0:
        return 0.0
    return float(flow) / area


def diluted(concentration: float, water: float) -> float:
    """Concentration after a water addition, as a fraction of the original."""
    total = float(concentration) + float(water)
    if total <= 0:
        return 0.0
    return float(concentration) / total


def concentration_verdict(reading: float, low: float, high: float) -> str:
    if reading < low:
        return "lean"
    if reading > high:
        return "rich"
    return "in_band"


def alarm_required(reading: float, low: float, high: float, tolerance: float) -> bool:
    """Whether a reading sits outside the band plus its tolerance."""
    return reading < low - tolerance or reading > high + tolerance


def stability_verdict(readings: Sequence[float], low: float, high: float) -> str:
    """Classify a window of readings: in band across the window, lean or rich."""
    if not readings:
        return IN_BAND
    if all(value < low for value in readings):
        return LEAN
    if all(value > high for value in readings):
        return RICH
    return IN_BAND


def is_stable(readings: Sequence[float], low: float, high: float, size: int) -> bool:
    """Steady only once a full window sits inside the band."""
    if len(readings) < size or size < 1:
        return False
    return all(low <= value <= high for value in readings[-size:])


def makeup_amount(verdict: str, reading: float, target: float, factor: float) -> float:
    """Glue (or water) needed to pull a drifted reading back to target.

    A lean bath needs glue solids, a rich bath needs water; an in-band reading needs
    nothing. The shortfall is scaled by the recipe make up factor.
    """
    if verdict == LEAN:
        return round((target - reading) * factor, 6)
    if verdict == RICH:
        return round((reading - target) * factor, 6)
    return 0.0
