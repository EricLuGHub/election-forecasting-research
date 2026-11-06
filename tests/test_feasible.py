"""Item-60 feasibility tests (synthetic only, no network)."""
from research.feasible import feasible


def test_feasible():
    v, d = feasible('e', 0.5, 20.0, 500, 1000)
    assert v == 'feasible'


def test_each_leg_can_fail():
    assert feasible('e', 0.1, 20.0, 500, 1000)[0] == 'thin'
    assert feasible('e', 0.5, 5.0, 500, 1000)[0] == 'thin'
    assert feasible('e', 0.5, 20.0, 500, 100)[0] == 'thin'
    assert feasible('e', None, 20.0, 500, 1000)[0] == 'refused'
    assert feasible('e', 'x', 20.0, 500, 1000)[0] == 'refused'
