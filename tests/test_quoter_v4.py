"""v4 rule unit tests (cycle 107). No network, no orders."""
from research.quoter import quote_age_ok, v4_legs, V4_ALLOW, quote_pair


def test_age_boundaries():
    assert quote_age_ok(0.0, 119.9, 120)
    assert not quote_age_ok(0.0, 120.1, 120)
    assert quote_age_ok(0.0, 9999.0, 0)  # disabled
    assert quote_age_ok(0.0, 9999.0, None)


def test_legs():
    assert v4_legs(True) == (('yes', 'buy'),)
    assert v4_legs(False) == (('yes', 'buy'), ('yes', 'sell'))


def test_allowlist_direction():
    for banned in ('987', '994', '890', '885', '1070', '936', '863', '861'):
        assert banned not in V4_ALLOW
    for allowed in ('1074', '889', '937', '875', '881', '1061'):
        assert allowed in V4_ALLOW


def test_quote_pair_still_guards():
    assert quote_pair(0.5, 0.51, 0, 5) is None  # spread < 2c
    qb, qa = quote_pair(0.10, 0.20, 0, 5)
    assert 0 < qb < qa < 1


def test_gate_helpers():
    import pytest
    from research.quoter import gate_suppress, gate_active, approx_edge
    s = {}
    assert not gate_suppress(s, '1', -0.01, 100.0)  # above thresh
    assert gate_suppress(s, '1', -0.05, 100.0)  # suppressed 15 min
    assert gate_active(s, '1', 200.0)
    assert not gate_active(s, '1', 2000.0)  # expired + pruned
    assert s == {}
    assert approx_edge({'quantity': 5, 'price': 0.5, 'exchangeId': '1'},
                       {'1': 0.52},
                       {'side': 'yes', 'action': 'buy', 'quantity': 5, 'price': 0.5}) == pytest.approx(0.02)
    assert approx_edge({'quantity': -5, 'price': 0.5, 'exchangeId': '1'},
                       {'1': 0.52},
                       {'side': 'yes', 'action': 'sell', 'quantity': 5, 'price': 0.5}) == pytest.approx(-0.02)
    assert approx_edge({'quantity': 5, 'price': 0.5, 'exchangeId': '9'}, {}) is None
    # canonicalized NO print of a YES sale: must score +0.01, not +0.75
    assert approx_edge({'quantity': -5, 'price': 0.87, 'side': 'no', 'exchangeId': '1'},
                       {'1': 0.12},
                       {'side': 'yes', 'action': 'sell', 'quantity': 5, 'price': 0.13}) == pytest.approx(0.01)
    # no order, no score (never forced)
    assert approx_edge({'quantity': 5, 'price': 0.5, 'exchangeId': '1'}, {'1': 0.52}) is None


def test_strategy_budget():
    from research.quoter import strategy_budget_ok
    from research.execution import Executor
    assert strategy_budget_ok(0.0, 5, 2000.0)
    assert strategy_budget_ok(1995.0, 5, 2000.0)
    assert not strategy_budget_ok(1999.0, 5, 2000.0)
    assert not strategy_budget_ok(0.0, 5, 0.01)  # tiny cap rejects everything
    assert not strategy_budget_ok('x', 5, 2000.0)
    exe = Executor(slug='midterm-elections', dry_run=True, max_basket_capital=37.5)
    assert exe.max_basket_capital == 37.5  # arg reaches the guard


def test_executor_caps_bite():
    import pytest
    from research.execution import Executor
    exe = Executor(slug='midterm-elections', dry_run=True,
                   max_basket_capital=2000.0, max_total_capital=20000.0)
    book = {'grossCapital': 0.0, 'openOrderCapital': 0.0}
    exe._check_caps(1999.0, book)  # fits
    with pytest.raises(ValueError):
        exe._check_caps(2000.01, book)  # basket cap bites
    with pytest.raises(ValueError):
        exe._check_caps(100.0, {'grossCapital': 19950.0, 'openOrderCapital': 0.0})


def test_recover_state():
    import time
    from research.quoter import recover_state, load_cursor, save_cursor
    journal = {'Q4-abc': {'body': {}, 'status': 'confirmed',
                          'at': '2026-10-05T00:00:00+00:00'}}
    orders = [{'id': 1, 'idempotencyKey': 'Q4-abc', 'exchangeId': '901',
               'side': 'yes', 'action': 'buy', 'quantity': 5, 'price': 0.5,
               'open': True},
              {'id': 2, 'idempotencyKey': 'E1-x', 'exchangeId': '901',
               'side': 'yes', 'action': 'buy', 'quantity': 5, 'price': 0.6,
               'open': True},
              {'id': 3, 'idempotencyKey': 'Q4-zzz', 'exchangeId': '901',
               'side': 'yes', 'action': 'buy', 'quantity': 5, 'price': 0.7,
               'open': True}]
    born, submitted, count = recover_state(orders, journal, now=9999999999.0)
    assert count == 2  # Q4 orders only (E1 excluded)
    assert 1 in submitted and 3 in submitted
    # known-age order keeps journal time; unknown-age treated as oldest
    assert max(born.values()) > 0
    assert min(born.values()) == 0.0
    # cursor round-trip
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    save_cursor({'gate_checked': 'X'}, path)
    assert load_cursor(path) == {'gate_checked': 'X'}
    os.unlink(path)
    assert load_cursor('/nonexistent-xyz.json') == {}
