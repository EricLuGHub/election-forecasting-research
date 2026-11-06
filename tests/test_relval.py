"""Item-77 relative value tests (synthetic only, no network)."""
from research.relval import spread, size_ratio, residual_stress, verdict


def test_spread_and_ratio():
    assert spread(0.60, 0.65) == 0.05
    assert spread(None, 0.5) is None
    assert size_ratio(2.0, 1.0) == 0.5
    assert size_ratio(0, 1.0) is None


def test_residual():
    assert residual_stress(100, 50, 0.05) == 2.5
    assert residual_stress(100, 100, 0.05) == 0.0  # balanced: wave-neutral
    assert residual_stress(100, 50, 'x') is None


def test_verdict():
    v, d = verdict('x', 0.60, 0.65, 1.0, 1.0)
    assert v == 'paper-setup' and d['qty_ratio_rich_over_cheap'] == 1.0
    assert verdict('x', 0.60, 0.615, 1.0, 1.0)[0] == 'no-spread'
    assert verdict('x', None, 0.6, 1.0, 1.0)[0] is None
