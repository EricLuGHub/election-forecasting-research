"""Quote-level queue estimates with conservative bounds (item 49). Pure.

No priority or cancel feed exists (c215 audit) — so never assign every
trade at our price to our order. Instead, bound the join:
- ahead: displayed quantity at-or-better than our price when we join
  (stale the next instant — treat as a LOWER bound on the queue ahead;
  hidden size only ever adds).
- arrival: trade volume per hour printing at-or-through our price over
  the recent window (measured, not assumed).
- est_hours_to_fill(qty) = (ahead + qty) / arrival_rate — time for
  enough volume to clear the queue ahead plus our clip. Infinite when
  arrival is zero (no trades at our price: joining earns nothing, and
  the module SAYS so — c215's warning encoded).
- conservative fill share over horizon H: min(1, arrival*H/(ahead+qty)).
Cancellations/replenishment unobserved → bounds stay one-sided
(pessimistic on ahead, historical on arrival). Any policy valid only
under optimistic queue assumptions is rejected upstream (paperbook).
"""


def hours_to_fill(ahead, qty, arrival_per_hour):
    """(hours | None). None when arrival is zero or inputs bad."""
    try:
        a, q, r = float(ahead), float(qty), float(arrival_per_hour)
    except (TypeError, ValueError):
        return None
    if q <= 0 or r <= 0 or a < 0:
        return None
    return round((a + q) / r, 2)


def fill_share(ahead, qty, arrival_per_hour, horizon_h):
    """Conservative share filled within horizon. None on bad inputs."""
    try:
        h = float(horizon_h)
    except (TypeError, ValueError):
        return None
    if h <= 0:
        return None
    t = hours_to_fill(ahead, qty, arrival_per_hour)
    if t is None:
        return None
    if t <= h:
        return 1.0
    import math
    got = float(arrival_per_hour) * h - float(ahead)
    return round(max(got, 0.0) / float(qty), 3)
