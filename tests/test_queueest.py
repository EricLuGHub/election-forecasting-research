"""Item-49 queue estimate tests (synthetic only, no network)."""
from research.queueest import hours_to_fill, fill_share


def test_hours_to_fill():
    assert hours_to_fill(1000, 500, 3000) == 0.5
    assert hours_to_fill(1000, 500, 0) is None  # no arrival: never
    assert hours_to_fill(1000, 0, 3000) is None
    assert hours_to_fill('x', 5, 5) is None


def test_fill_share():
    assert fill_share(1000, 500, 3000, 1.0) == 1.0
    assert fill_share(1000, 500, 3000, 0.25) == 0.0  # 750 < 1000 ahead
    assert fill_share(100, 500, 3000, 0.25) == 1.0  # capped: fills in 0.2h
    assert fill_share(100, 500, 3000, 0) is None
