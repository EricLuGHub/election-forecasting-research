"""Item-89 collateral audit tests (synthetic only, no network)."""
from research.collateral import audit


def test_cash_binding():
    v, d = audit({}, 29000, 89000, 500, 2500)
    assert v == 'cash-binding' and d['collateral'] == 0.0


def test_offsets_live():
    v, d = audit({'collateralValue': 5000}, 29000, 89000, 500, 2500)
    assert v == 'offsets-live' and d['collateral'] == 5000.0


def test_scope_and_bad_inputs():
    assert audit({}, 1, 1, 1, 1, tournament_ok=False)[0] == 'refused'
    assert audit({}, 1, 1, 1, 1)[0] == 'cash-binding'
    assert audit({}, -1, 1, 1, 1)[0] is None
    assert audit('x', 1, 1, 1, 1)[0] is None
