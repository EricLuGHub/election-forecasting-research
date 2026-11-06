"""Item-39 sub-cost/blocked-exit tests (synthetic only, no network)."""
from research.subcost import analyze_basket


def _pos(avg, lots, mv_per_share):
    # lots: [(entryPrice, qty)]; qty sign ignored by cost_ceiling (abs)
    lot_dicts = [{'entryPrice': p, 'quantity': q} for p, q in lots]
    qty = sum(abs(q) for _, q in lots)
    return {'quantity': -qty, 'costBasis': avg * qty,
            'marketValue': mv_per_share * qty, 'lots': lot_dicts}


def test_blocked_profitable():
    # Joint +10 but leg B bid 0.50 < floor max(0.60+0.01, mark).
    legs = [('R', _pos(0.45, [(0.45, 500), (0.60, 500)], 0.55), 0.62),
            ('D', _pos(0.50, [(0.50, 1000)], 0.50), 0.50)]
    v, d = analyze_basket('b', legs, 1020.0, 1010.0)
    assert v == 'blocked-profitable' and d['blocked_value'] == 10.0
    assert sum(1 for l in d['legs'] if l['blocked']) == 1


def test_fires_today():
    legs = [('R', _pos(0.45, [(0.45, 1000)], 0.55), 0.56),
            ('D', _pos(0.50, [(0.50, 1000)], 0.50), 0.52)]
    v, d = analyze_basket('b', legs, 1020.0, 1010.0)
    assert v == 'fires-today'


def test_hold_candidate_not_judged():
    legs = [('R', _pos(0.45, [(0.45, 1000)], 0.40), 0.39),
            ('D', _pos(0.50, [(0.50, 1000)], 0.50), 0.52)]
    v, d = analyze_basket('b', legs, 990.0, 1010.0)
    assert v == 'hold-candidate' and d['joint_edge'] == -20.0


def test_missing_bid_refuses():
    legs = [('R', _pos(0.45, [(0.45, 1000)], 0.55), None)]
    assert analyze_basket('b', legs, 1020.0, 1010.0)[0] is None
