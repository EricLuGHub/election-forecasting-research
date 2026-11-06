"""Item-80 regime tests (synthetic only, no network)."""
from research.regimes import bucketize, describe, continuation_by_regime

# 2026-10-03/04 = Saturday/Sunday; 2026-10-05 = Monday.
SAT = '2026-10-03T12:00:00+00:00'
MON = '2026-10-05T12:00:00+00:00'


def test_bucketize_splits_weekend():
    rows = [(SAT, 'e', 0.5, 0.52), (MON, 'e', 0.5, 0.54)]
    b = bucketize(rows)
    assert len(b['weekend']) == 1 and len(b['weekday']) == 1
    assert describe([]) is None
    d = describe(b['weekend'])
    assert d['mean_spread'] == 0.02 and d['n'] == 1


def test_continuation_split_runs():
    from datetime import datetime, timezone, timedelta
    base_sat = datetime(2026, 10, 3, tzinfo=timezone.utc)
    base_mon = datetime(2026, 10, 5, tzinfo=timezone.utc)
    rows = []
    for i in range(30):
        for base, tag in ((base_sat, 's'), (base_mon, 'm')):
            at = (base + timedelta(minutes=10 * i)).isoformat()
            m = 0.5 + (0.01 * i if tag == 'm' else 0.0)
            rows.append((at, 'e', m - 0.005, m + 0.005))
    out = continuation_by_regime(rows)
    assert out['weekday']['n_events'] > 0
    assert out['weekend']['n_events'] == 0
    assert out['weekend']['rate'] is None
