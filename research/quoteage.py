"""Quote-age causality with measured fill ages (backlog item 56). Pure.

The fallacy: "fills occurring after 30s rest earn well, so cancel fresh
orders at 30s." Survivors differ from the newborn — rested fills are the
ones that SURVIVED 30s unfilled (adverse flow already passed them over).
Correct comparison: FIXED policies evaluated prospectively from the
submit decision with only submit-time information:
- REST: hold the quote; outcome = fill economics whenever it fills.
- CANCEL-AT-T: withdraw at T; outcome = 0 thereafter (missed fills count
  as $0, not as avoided losses — you cannot lose on a quote you canceled,
  but you cannot earn either).
fill_age(join of fills x submits) reports the age distribution that
motivates the question; the policy verdict comes from the prospective
comparison, never from conditioning on age.
"""


def _ts(at):
    from datetime import datetime
    if isinstance(at, (int, float)):
        return float(at)
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def fill_ages(fills, submit_of):
    """fills: [(fill_id, order_id, filled_at)]; submit_of: {order_id: ts}.
    Returns [age_seconds] for joinable fills (unjoinable counted, not
    faked — caller reports the join rate separately)."""
    ages = []
    missed = 0
    for _, oid, fat in fills:
        st, ft = _ts(submit_of.get(str(oid))), _ts(fat)
        if st is None or ft is None or ft < st:
            missed += 1
            continue
        ages.append(round(ft - st, 1))
    return ages, missed


def age_summary(ages):
    import statistics
    if not ages:
        return None
    srt = sorted(ages)
    n = len(srt)
    return {'n': n, 'median': srt[n // 2],
            'p90': srt[min(n - 1, 9 * n // 10)],
            'max': srt[-1],
            'mean': round(sum(srt) / n, 1),
            'frac_over_30s': round(sum(1 for a in srt if a > 30) / n, 3)}


def prospective_compare(fill_values, cancel_t=30.0):
    """fill_values: per-fill economics in submit order [(age, value)].
    REST earns all values; CANCEL-AT-T earns only fills with age <= T
    (later fills = $0 missed, not avoided losses). Returns both totals —
    the verdict is arithmetic, not causal storytelling."""
    try:
        t = float(cancel_t)
    except (TypeError, ValueError):
        return None
    rest = sum(v for _, v in fill_values)
    canc = sum(v for a, v in fill_values if a <= t)
    return {'rest_total': round(rest, 2), 'cancel_total': round(canc, 2),
            'n': len(fill_values),
            'n_canceled_away': sum(1 for a, _ in fill_values if a > t)}
