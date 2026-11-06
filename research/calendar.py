"""Public-information event calendar + response study (item 70). Pure.

Rule zero: verify dates and relevance; never fabricate a catalyst per
race. An event enters the registry only with (what, race-scope,
timestamp-or-window, source). Response study: absolute mid-move in the
POST window after the event vs the same-length PRE window baseline on
the same exchange (volatility ratio). A ratio near 1.0 with tiny moves
is a NON-response — tradable catalysts must move books first.

Sources carry their retrieval date; polls are dated by END date (when
the information existed), not publication hype.
"""
PRE_H = 24.0
POST_H = 24.0


def register(what, scope, at, source):
    """Verified event record. at: ISO timestamp (or None when only a
    window is known — dateless events never enter response studies)."""
    if not what or not scope or not source:
        return None
    return {'what': what, 'scope': scope, 'at': at, 'source': source}


def _ts(at):
    from datetime import datetime
    if isinstance(at, (int, float)):
        return float(at)
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def response(series, event_ts, pre_h=PRE_H, post_h=POST_H):
    """series: [(ts, mid)] sorted. Returns (post_move, pre_move, ratio)
    of absolute mid changes, or None when coverage is short on either
    side (a study needs both windows — stated, not interpolated)."""
    t = _ts(event_ts)
    if t is None:
        return None
    pre = [m for ts, m in series if t - pre_h * 3600 <= ts < t]
    post = [m for ts, m in series if t <= ts <= t + post_h * 3600]
    if len(pre) < 2 or len(post) < 2:
        return None
    pre_move = abs(pre[-1] - pre[0])
    post_move = abs(post[-1] - post[0])
    ratio = round(post_move / pre_move, 2) if pre_move > 0 else None
    return {'post_move': round(post_move, 4), 'pre_move': round(pre_move, 4),
            'ratio': ratio}
