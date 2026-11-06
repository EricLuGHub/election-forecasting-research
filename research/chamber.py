"""E5 chamber-control: scoped, NOT implemented (backlog item 76). Pure.

The item gates E5 on the joint model existing. It does not (rating->P
calibration blocked, same as item 73; 435-race House assembly large).
This module holds the seat-counting mechanics + the comparison stub so
a future build starts from verified arithmetic, not from scratch:
- senate_control(d_held_safe, r_held_safe, swing_results): D needs 51
  (VP Vance (R) breaks ties — R needs 50). swing_results: {race: winner}.
- house_control(d_safe, r_safe, swing_results): 218 to control.
- compare(model_p, market_price): edge only if model interval clears
  price + uncertainty (never point estimates).
STATUS: PARKED pending (a) rating->P calibration data, (b) full seat
assembly, (c) a control-price dislocation worth modeling. Revisit
triggers filed, not silently dropped.
"""
SENATE_D_NEEDED = 51
HOUSE_NEEDED = 218


def senate_control(d_safe, r_safe, swing):
    """swing: {race: 'D'|'R'}. Returns (controller, d_seats, r_seats)."""
    try:
        d, r = int(d_safe), int(r_safe)
    except (TypeError, ValueError):
        return None
    for winner in swing.values():
        if winner == 'D':
            d += 1
        elif winner == 'R':
            r += 1
        else:
            return None
    controller = 'D' if d >= SENATE_D_NEEDED else ('R' if r > 100 - SENATE_D_NEEDED else 'TBD')
    return controller, d, r


def house_control(d_safe, r_safe, swing):
    try:
        d, r = int(d_safe), int(r_safe)
    except (TypeError, ValueError):
        return None
    for winner in swing.values():
        if winner == 'D':
            d += 1
        elif winner == 'R':
            r += 1
        else:
            return None
    if d >= HOUSE_NEEDED:
        controller = 'D'
    elif r >= HOUSE_NEEDED:
        controller = 'R'
    else:
        controller = 'TBD'
    return controller, d, r


def compare(model_p, model_u, market_price):
    """Edge only if interval clears price. None on bad inputs."""
    try:
        p, u, m = float(model_p), float(model_u), float(market_price)
    except (TypeError, ValueError):
        return None
    if not 0 <= p <= 1 or u < 0 or not 0 <= m <= 1:
        return None
    if p - u > m:
        return 'buy'
    if p + u < m:
        return 'sell'
    return 'hold'
