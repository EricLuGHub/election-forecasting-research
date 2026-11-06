"""Item-35 refill/depletion tests (synthetic only, no network)."""
from research.refill import score


def _ladder(levels):
    return [(p, s) for p, s in levels]


def test_refilled():
    # Deep 0.48 YES bids: NO cost 0.52/leg -> edge grows with size.
    bids = _ladder([(0.52, 5000)])
    v, d = score('b', bids, bids, 1000, 40.0, quantities=(250, 500, 1000))
    assert v == 'refilled' and d['retention'] == round(d['best']['edge'] / 40.0, 2)


def test_thin():
    # Only 150 deep: fills 100 for edge 4.00, below the $15 bar.
    bids = _ladder([(0.52, 150)])
    v, d = score('b', bids, bids, 1000, 40.0, quantities=(100, 200, 300))
    assert v == 'thin' and d['best'] == {'qty': 100, 'edge': 4.0}


def test_depleted_empty_book():
    v, d = score('b', [], [], 1000, 40.0)
    assert v == 'depleted' and d['best'] is None


def test_depleted_negative():
    # 0.55 YES bids: NO costs 0.45... wait 1-0.55=0.45/leg -> 0.90 < 1 POSITIVE.
    # Use 0.40 bids: cost 0.60/leg -> 1.20 > 1 negative at every qty.
    bids = _ladder([(0.40, 5000)])
    v, d = score('b', bids, bids, 1000, 40.0, quantities=(250, 500))
    assert v == 'depleted' and d['best']['edge'] < 0


def test_refusals_and_nonpositive_base():
    assert score('b', [(0.52, 9)], [(0.52, 9)], 0, 40.0)[0] is None
    v, d = score('b', _ladder([(0.52, 5000)]), _ladder([(0.52, 5000)]),
                 1000, -5.0, quantities=(1000,))
    assert v == 'refilled' and d['retention'] is None
