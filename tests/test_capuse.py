"""Item-88 capital-use tests (pure)."""
from datetime import datetime, timezone
from research.capuse import capital_use


def test_separates_basket_from_legacy():
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    out = capital_use(1000.0, 1025.0, 9000.0, 300.0, 2200.0, now=now)
    assert out['cash_tied'] == 10000.0
    assert out['basket_cost'] == 1000.0
    assert out['other_cost'] == 9000.0
    assert out['locked_edge'] == 325.0  # (1025-1000) + 300
    assert out['worst_loss'] == 2200.0 + 0.05 * 10000.0
    assert out['return_on_exposure'] == round(325.0 / 2700.0, 3)
    assert out['days_to_settlement'] == 30.0
    # ~0.108%/day on tied cash: the binding constraint is opportunity, visible
    assert out['edge_per_capital_day'] == round(325.0 / 10000.0 / 30.0, 6)


def test_zero_safe():
    out = capital_use(0.0, 0.0, 0.0, 0.0, 0.0)
    assert out['return_on_exposure'] is None
    assert out['edge_per_capital_day'] is None
