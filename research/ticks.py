"""One price-unit and tick definition (item 101). Canonical.

VENUE TRUTH: limit prices sit on the 0.005 grid (execution.validate_leg
enforces it; round_tick() is the single rounder — import it, don't
redefine it). ONE venue tick = 0.005 (200 per $1). Display convention:
SUSQies with 3 decimals AND integer venue-ticks side by side, so
"3 ticks" can never silently mean cents again.
Conversions: dollars -> vticks = round(price / 0.005); back with
round_tick for placement (never raw floats to the venue).
"""
from .execution import TICK as VENUE_TICK
from .execution import round_tick

VTICK = 0.005


def to_vticks(price):
    """Dollars -> integer venue ticks, or None."""
    try:
        return int(round(float(price) / VTICK))
    except (TypeError, ValueError):
        return None


def from_vticks(n):
    """Integer venue ticks -> placeable dollars via round_tick."""
    try:
        return round_tick(int(n) * VTICK)
    except (TypeError, ValueError):
        return None


def display(price):
    """(dollars, vticks) for logs. None-safe."""
    v = to_vticks(price)
    if v is None:
        return None
    return {'susqies': from_vticks(v), 'vticks': v}
