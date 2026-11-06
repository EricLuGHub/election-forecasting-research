"""Item-51 flow imbalance tests (synthetic only, no network)."""
from research.flowimb import ofi, head_to_head


def test_ofi_flow_math():
    v, d = ofi([(0.5, 100)], [(0.52, 100)], [(0.5, 150)], [(0.52, 80)],
               [{'size': 10, 'side': 'YES'}, {'size': 5, 'side': 'sell'},
                {'size': 7, 'side': '???'}])
    assert v == 50 - (-20) + (10 - 5)
    assert d == {'d_bid': 50.0, 'd_ask': -20.0, 'signed_trades': 5.0,
                 'unsigned_vol': 7.0}
    assert ofi([], [(0.5, 1)], [(0.5, 1)], [(0.5, 1)])[0] is None


def test_head_to_head():
    r = head_to_head([(0.5, 0.3, 0.01), (-0.5, -0.4, -0.01),
                      (0.5, -0.2, -0.01), (0.1, 0.1, 0.0)])
    assert r == {'n': 3, 'static_hit': round(2 / 3, 3), 'flow_hit': 1.0}
    assert head_to_head([]) is None
