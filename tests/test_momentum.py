"""Item-67 momentum tests (synthetic only, no network)."""
from research.momentum import to_mids, formed_events, score_event, summarize


def _rows(eid, mids, t0=1_000_000, step=600):
    from datetime import datetime, timezone
    rows = []
    for i, m in enumerate(mids):
        at = datetime.fromtimestamp(t0 + i * step,
                                    tz=timezone.utc).isoformat()
        rows.append((at, eid, m - 0.005, m + 0.005))
    return rows


def test_pure_trend_continues():
    mids = to_mids(_rows('e', [0.5 + 0.01 * i for i in range(30)]))
    s = summarize(mids, move_min=0.02, lookback_h=1.0, horizon_h=1.0)
    assert s['total']['continuation_rate'] == 1.0


def test_spike_retraces():
    mids = to_mids(_rows('e', [0.5] * 6 + [0.55, 0.50] + [0.5] * 22))
    s = summarize(mids, move_min=0.02, lookback_h=1.0, horizon_h=1.0)
    assert s['total']['n_events'] == 2  # spike forms +1, retrace forms -1
    assert s['total']['continuation_rate'] == 0.0
    # strict: spike reverts (win), retrace-event flats (not a win)
    assert s['total']['fade_win_rate'] == 0.5
    assert s['total']['fade_baseline_wr'] == 0.5


def test_flat_yields_no_events_not_zero():
    mids = to_mids(_rows('e', [0.5] * 30))
    s = summarize(mids)
    assert s['total']['n_events'] == 0
    assert s['total']['continuation_rate'] is None


def test_bad_rows_skipped():
    mids = to_mids([('junk', 'e', 0.5, 0.51), ('2026-10-05T00:00:00+00:00',
                                              'e', None, 0.51)])
    assert mids == {}
