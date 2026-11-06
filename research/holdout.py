"""Chronological holdouts with purging + race grouping (item 82). Pure.

Every study so far fit-and-tested on one window (10-01→10-06). This module
enforces the discipline: split observations at a time cut, PURGE a gap at
least as long as the outcome horizon on both sides (labels overlapping the
cut see both regimes — drop them), evaluate the frozen rule on the late
half. Related races travel together: group key (raceId or basket) splits
as a unit where grouping applies — one event never becomes hundreds of
independent successes.

For quote-series rules: split_series(rows, cut_ts, purge_h) -> (early,
late). For basket observations: split_groups(rows, cut, group_key) with
whole-group assignment by first-observation time.
"""


def _ts(at):
    from datetime import datetime
    if isinstance(at, (int, float)):
        return float(at)
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def split_series(rows, cut_ts, purge_h=1.0):
    """[(ts, ...)] -> (early, late). Drops observations within purge_h of
    the cut on EITHER side (labels formed across the cut are contaminated).
    cut_ts: epoch. Refuses (None, None) on bad cut."""
    try:
        cut = float(cut_ts)
        gap = float(purge_h) * 3600
    except (TypeError, ValueError):
        return None, None
    early = [r for r in rows if r[0] < cut - gap]
    late = [r for r in rows if r[0] > cut + gap]
    return early, late


def split_groups(rows, cut_ts, group_key=0, time_key=1):
    """rows: tuples; group_key index identifies the related group (raceId,
    basket). Whole groups assigned by their earliest time: groups starting
    before cut train, groups starting after validate. Groups SPANNING the
    cut are dropped (their labels leak across). Returns (early, late)."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        t = _ts(r[time_key])
        if t is None:
            continue
        groups[r[group_key]].append((t, r))
    early, late = [], []
    cut = float(cut_ts)
    for _, items in sorted(groups.items(), key=lambda kv: str(kv[0])):
        items.sort()
        if items[-1][0] < cut:
            early.extend(r for _, r in items)
        elif items[0][0] > cut:
            late.extend(r for _, r in items)
        # spanning groups: dropped (leakage), counted nowhere
    return early, late


def stability_verdict(early_metric, late_metric, tolerance=0.15):
    """Same-direction + within tolerance -> 'stable'; direction flip ->
    'reversed'; else 'unstable'. Thresholds stated, not tuned."""
    try:
        e, l = float(early_metric), float(late_metric)
    except (TypeError, ValueError):
        return 'unknown'
    if e == 0 and l == 0:
        return 'stable'
    if (e > 0.5) != (l > 0.5):
        return 'reversed'
    denom = max(abs(e), abs(l), 1e-9)
    if abs(e - l) / denom <= tolerance:
        return 'stable'
    return 'unstable'
