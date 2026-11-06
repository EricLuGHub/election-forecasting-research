"""Item-59 trial replay tests (synthetic only, no network)."""
from research.trialreplay import touch_at, replay


def _books(mids, t0=1_000_000, step=60):
    # NO-book series (bid, ask) directly.
    return {'e': [(t0 + i * step, m - 0.005, m + 0.005) for i, m in enumerate(mids)]}


def test_touch_sides():
    s = [(100.0, 0.90, 0.92), (200.0, 0.91, 0.93)]
    assert touch_at(s, 150.0, 'sell') == 0.91
    assert touch_at(s, 150.0, 'buy') == 0.93
    assert touch_at(s, 500.0, 'sell') is None


def test_horizons_and_value():
    # Buy NO at 0.90, drifts up: h5/h10/h30 rise; value triggers at 0.91+.
    mids = [0.90] * 5 + [0.905 + 0.002 * i for i in range(30)]
    out = replay([('e', 1_000_000, 'buy', 100, 0.90)], _books(mids))
    assert out['h5']['proceeds'] == 90.0  # bid at t+5m
    assert out['h30']['proceeds'] == 95.0  # drift captured
    assert out['value']['proceeds'] >= 91.0  # cost+1c hit
    assert out['value']['n'] == 1


def test_losers_marked_not_skipped():
    mids = [0.90] * 40  # flat: value never triggers, marked at touch
    out = replay([('e', 1_000_000, 'buy', 100, 0.90)], _books(mids))
    assert out['value']['proceeds'] == 89.5  # marked at bid touch
    assert out['h5']['missing'] == 0


def test_value_exit_bounded_by_horizon():
    # Jump AFTER the h30 window must NOT trigger value (c244 gap queued).
    from research.trialreplay import replay
    mids = [0.90] * 35 + [0.95] * 10
    books = {'e': [(1_000_000 + i * 60, m - 0.005, m + 0.005) for i, m in enumerate(mids)]}
    out = replay([('e', 1_000_000, 'buy', 100, 0.90)], books)
    assert out['value']['proceeds'] == round(100 * 0.895, 2)  # h30 mark, not late trigger
