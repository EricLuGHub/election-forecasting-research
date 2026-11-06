"""Lead-lag: does the public market move first? (backlog item 66). Pure.

Method: receipt-timestamped series on both venues; correlate lagged
Kalshi mid-changes against subsequent SIG executable changes (joint
top-cost moves on the tracked pair). A persistent LEVEL gap (Kalshi 88
vs SIG-implied 86, stable) is a different trade from a short-lived
INFORMATION lag (Kalshi jumps, SIG follows minutes later) — the module
reports both separately because they demand different policies (size a
level arb vs race a latency edge).

Refusals: missing receipt timestamps, single observations, or
non-monotonic clocks — a lag measured on mixed clocks is fiction.
"""


def _changes(series):
    """[(t1, delta)] of consecutive mid changes. Series: [(ts, mid)]."""
    out = []
    for (t0, m0), (t1, m1) in zip(series, series[1:]):
        if t1 <= t0:
            return None
        try:
            out.append((t1, float(m1) - float(m0)))
        except (TypeError, ValueError):
            return None
    return out


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = (sum(d * d for d in dx) * sum(d * d for d in dy)) ** 0.5
    if den == 0:
        return None
    return round(sum(a * b for a, b in zip(dx, dy)) / den, 3)


def lag_corr(kalshi, sig, max_lag=3):
    """{lag_steps: corr} of Kalshi[t-lag]Δ vs SIG[t]Δ over shared steps.

    Both series: [(receipt_ts, mid)]. Aligned by ORDER (uniform sampling
    assumed — caller enforces cadence; mixed cadences refuse elsewhere).
    Needs >=3 shared changes per lag (else None: insufficient, not zero).
    """
    kc, sc = _changes(kalshi), _changes(sig)
    if kc is None or sc is None or len(kc) != len(sc):
        return None
    out = {}
    for lag in range(max_lag + 1):
        xs = [d for _, d in kc[:len(kc) - lag]] if lag else [d for _, d in kc]
        ys = [d for _, d in sc[lag:]]
        n = min(len(xs), len(ys))
        out[lag] = _pearson(xs[:n], ys[:n]) if n >= 3 else None
    return out


def level_gap(k_mid, sig_fair):
    """(gap, note). Persistent != tradable: execution + basis still apply."""
    try:
        return round(float(k_mid) - float(sig_fair), 4), 'level gap'
    except (TypeError, ValueError):
        return None, 'refused'
