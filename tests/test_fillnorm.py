"""Item-1 normalizer tests, incl. the audit's canonical example."""
from research.fillnorm import normalize, edge_vs


def test_audit_example():
    # YES sale 5 @0.13 printing as NO fill (qty -5 @0.87), YES mid 0.12.
    fill = {'side': 'no', 'quantity': -5, 'price': 0.87}
    order = {'side': 'yes', 'action': 'sell', 'quantity': 5, 'price': 0.13}
    n = normalize(fill, order)
    assert n['econ_qty'] == -5
    assert abs(n['exec_yes'] - 0.13) < 1e-9
    assert abs(n['premium'] - 0.65) < 1e-9
    assert abs(edge_vs(n, 0.12) - 0.01) < 1e-9  # audit expects +0.01, not +0.75


def test_long_buy():
    fill = {'side': 'yes', 'quantity': 5, 'price': 0.13}
    order = {'side': 'yes', 'action': 'buy', 'quantity': 5, 'price': 0.13}
    n = normalize(fill, order)
    assert n['econ_qty'] == 5
    assert abs(n['premium'] + 0.65) < 1e-9
    assert abs(edge_vs(n, 0.14) - 0.01) < 1e-9


def test_no_buy_is_short_yes():
    # NO buy 5 @0.87 == economically short YES at 0.13, costs cash now.
    fill = {'side': 'no', 'quantity': 5, 'price': 0.87}
    order = {'side': 'no', 'action': 'buy', 'quantity': 5, 'price': 0.87}
    n = normalize(fill, order)
    assert n['econ_qty'] == -5
    assert abs(n['exec_yes'] - 0.13) < 1e-9
    assert abs(edge_vs(n, 0.12) - 0.01) < 1e-9


def test_unmatched_and_garbage():
    assert normalize({'side': 'yes', 'quantity': 5, 'price': 0.5}, {}) is None
    assert normalize({'side': 'yes', 'quantity': 0, 'price': 0.5},
                     {'side': 'yes', 'action': 'buy', 'quantity': 1, 'price': 0.5}) is None
    assert normalize({'side': 'yes', 'quantity': 5, 'price': 0.5},
                     {'side': 'maybe', 'action': 'buy', 'quantity': 1, 'price': 0.5}) is None
    assert edge_vs(None, 0.5) is None
