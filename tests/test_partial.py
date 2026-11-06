"""Item-29 partial-fill tree tests (synthetic books, no network)."""
from research.partial import decide, walk_buy_no, walk_sell_no


def _books():
    return {'R': {'bids': [(0.20, 5000)], 'asks': [(0.22, 5000)]},
            'D': {'bids': [(0.75, 5000)], 'asks': [(0.77, 5000)]}}


def test_complete_within_limit():
    action, det = decide({'R': 1000}, {'D': 1000}, _books(),
                         {'R': 0.80, 'D': 0.25}, 1000)
    assert action == 'COMPLETE'
    assert det['reason'] == 'within_limit'


def test_unwind_on_thin_remainder():
    books = {'R': {'bids': [(0.20, 5000)], 'asks': [(0.22, 5000)]},
             'D': {'bids': [(0.75, 10)], 'asks': [(0.77, 10)]}}
    action, det = decide({'R': 1000}, {'D': 1000}, books,
                         {'R': 0.80, 'D': 0.25}, 1000)
    assert action == 'UNWIND'
    assert det['reason'] == 'remainder_thin'


def test_unwind_on_timeout():
    action, det = decide({'R': 1000}, {'D': 1000}, _books(),
                         {'R': 0.80, 'D': 0.25}, 1000,
                         elapsed_min=20.0, timeout_min=15.0)
    assert action == 'UNWIND'
    assert det['reason'] == 'timeout'


def test_hold_when_exposed_but_patient():
    books = {'R': {'bids': [(0.20, 5000)], 'asks': [(0.22, 5000)]},
             'D': {'bids': [(0.60, 5000)], 'asks': [(0.62, 5000)]}}
    # D remainder costs 0.40 vs 0.25 limit: over tol, but 1000 <= orphan cap
    action, det = decide({'R': 1000}, {'D': 1000}, books,
                         {'R': 0.80, 'D': 0.25}, 1000, max_orphan=2000.0)
    assert action == 'HOLD'
    action2, det2 = decide({'R': 1000}, {'D': 1000}, books,
                           {'R': 0.80, 'D': 0.25}, 1000, max_orphan=100.0)
    assert action2 == 'UNWIND'
    assert det2['reason'] == 'orphan_breach'


def test_walk_helpers():
    avg, ok = walk_buy_no([(0.20, 500)], 1000)
    assert ok is False
    avg2, ok2 = walk_buy_no([(0.20, 2000)], 1000)
    assert ok2 and abs(avg2 - 0.80) < 1e-9
    p, ok3 = walk_sell_no([(0.77, 2000)], 1000)
    assert ok3 and abs(p - 0.23) < 1e-9
