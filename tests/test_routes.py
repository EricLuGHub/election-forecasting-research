"""Item-63 route comparison tests (synthetic only, no network)."""
from research.routes import table, compare


def test_table_states():
    t = table(0.16, 0.86, 0.155)
    assert t['A_short_YES'] == {'S': -0.84, 'D': 0.16, 'O': 0.16}
    assert t['B_long_DYES']['O'] == -0.86  # third-party bleeds B
    assert t['C_long_SNO'] == {'S': -0.845, 'D': 0.155, 'O': 0.155}
    assert table(0, 0.5, 0.5) is None and table(None, 0.5, 0.5) is None


def test_route_optimal():
    v, d = compare('x', 0.16, 0.86, 0.155)
    assert v == 'route-optimal'


def test_c_cheaper():
    v, d = compare('x', 0.10, 0.86, 0.155)
    assert v == 'c-cheaper'


def test_tie_reports_b_tradeoff():
    v, d = compare('x', 0.155, 0.86, 0.155)
    assert v == 'b-tradeoff'
