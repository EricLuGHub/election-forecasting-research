"""Item-95 objective math tests."""
from research.objective import required_rates


def test_rates_scale():
    out = required_rates(522.58, 81678.67, 670507.53, days_left=30.0)
    assert out['top20']['need'] == round(81678.67 - 522.58, 2)
    assert out['top20']['per_day'] == round((81678.67 - 522.58) / 30.0, 2)
    # top3 needs ~8x top20 daily rate; +1%/h dwarfs both
    assert out['top3']['per_day'] > 8 * out['top20']['per_day']
    assert out['plus1pct_hour']['per_day'] > 8 * out['top20']['per_day']


def test_already_there():
    out = required_rates(100000.0, 81678.67, 670507.53)
    assert out['top20']['need'] < 0 or out['top20']['per_day'] <= 0
