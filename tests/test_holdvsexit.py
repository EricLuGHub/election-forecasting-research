"""Item-38 hold-vs-exit tests (synthetic only, no network)."""
from research.holdvsexit import analyze, rank


def test_exit_when_book_beats_guarantee():
    v, d = analyze('x', 1000.0, 1000, 1000, 1005.0, 965.0)
    assert v == 'exit' and d['retain'] == -5.0


def test_hold_when_retain_beats_dust():
    v, d = analyze('y', 1000.0, 1000, 1000, 985.0, 970.0)
    assert v == 'hold' and d['G'] == 1000.0 and d['retain'] == 15.0


def test_concrete_replacement_can_flip():
    v, _ = analyze('y', 1000.0, 1000, 1000, 985.0, 970.0,
                   replacement={'name': 'fresh arb', 'gain': 30.0})
    assert v == 'contingent'  # 15 within 30+5? no: 15 < 35 -> contingent
    v2, _ = analyze('y', 1000.0, 1000, 1000, 985.0, 970.0,
                    replacement={'name': 'fresh arb', 'gain': 5.0})
    assert v2 == 'hold'  # 15 > 5+5


def test_refusals():
    assert analyze('z', 1000.0, 1000, 0, 985.0, 970.0)[0] is None
    assert analyze('z', 'n/a', 1000, 500, 985.0, 970.0)[0] is None
    assert analyze('z', 1000.0, 1000, 1500, 985.0, 970.0)[0] is None


def test_rank_orders_exits_first():
    out = rank([('h', 1000.0, 1000, 1000, 985.0, 970.0),
                ('e', 1000.0, 1000, 1000, 1005.0, 965.0)])
    assert [t[0] for t in out] == ['exit', 'hold']


def test_paired_cost_not_rescaled():
    # Convexit row cost is already cost-at-qty; analyzer must reproduce the
    # row edge exactly (c188 caught 52.66/237.92 double-scale phantoms).
    v, d = analyze('arsen', 1000.0, 1000, 975, 984.75, 955.99)
    assert d['edge_vs_cost'] == 28.76
    v, d = analyze('idgov', 1000.0, 1000, 678, 688.17, 664.08)
    assert d['edge_vs_cost'] == 24.09
