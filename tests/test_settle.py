"""Item-61 settlement-interval tests (synthetic only, no network)."""
from research.settle import implied_probs, breakeven_q


def test_implied_probs():
    d = implied_probs(0.16, 0.865)
    assert d == {'p_r': 0.16, 'p_d': 0.865, 'overround': 0.025}
    assert implied_probs(None, 0.5) is None
    assert implied_probs(1.5, 0.5) is None


def test_breakeven_q():
    assert breakeven_q(24.04, 1000.0) == 0.024
    assert breakeven_q(0, 1000.0) is None
    assert breakeven_q(-5, 1000.0) is None
    assert breakeven_q(10, 0) is None
