"""Concentration correction arithmetic.

A reading that leaves the recipe band is pulled back to the setpoint: a rich
reading is diluted with water, a lean reading is enriched with stock glue. The
amounts come out of the mixing balance on the chest volume.
"""

DILUTE = "dilute"
ENRICH = "enrich"
IN_BAND = "in_band"


def correction_kind(reading: float, low: float, high: float) -> str:
    if reading < low:
        return ENRICH
    if reading > high:
        return DILUTE
    return IN_BAND


def water_to_dilute(current: float, target: float, volume: float) -> float:
    """Water that brings a rich chest back to the setpoint."""
    if target <= 0 or volume <= 0:
        return 0.0
    return max(0.0, float(volume) * (float(current) - float(target)) / float(target))


def concentrate_to_enrich(current: float, target: float, volume: float, stock: float) -> float:
    """Stock glue that brings a lean chest up to the setpoint."""
    if volume <= 0 or stock <= target:
        return 0.0
    return max(0.0, float(volume) * (float(target) - float(current)) / (float(stock) - float(target)))


def correction(
    reading: float,
    target: float,
    tolerance: float,
    volume: float,
    stock: float,
) -> dict[str, float | str]:
    """Kind and amount of the correction that returns the chest to the setpoint."""
    low = float(target) - float(tolerance)
    high = float(target) + float(tolerance)
    kind = correction_kind(reading, low, high)
    if kind == DILUTE:
        amount = water_to_dilute(reading, target, volume)
    elif kind == ENRICH:
        amount = concentrate_to_enrich(reading, target, volume, stock)
    else:
        amount = 0.0
    return {"kind": kind, "amount": amount, "low": low, "high": high}
