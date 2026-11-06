"""Item-69 replenishment tests (synthetic only, no network)."""
from research.replenish import depth_at, verdict


def test_depth_at():
    assert depth_at([(0.10, 100), (0.09, 200), (0.11, 50)], 0.10) == 150.0
    assert depth_at([], 0.1) == 0.0
    assert depth_at(None, 0.1) is None


def test_refilled():
    v, d = verdict('e', [(0.10, 1000)], [(0.10, 900)], 0.10, 0.10)
    assert v == 'refilled' and d['ratio'] == 0.9


def test_pulled():
    v, d = verdict('e', [(0.10, 1000)], [(0.10, 50)], 0.10, 0.10)
    assert v == 'pulled' and d['ratio'] == 0.05


def test_partial():
    v, d = verdict('e', [(0.10, 1000)], [(0.10, 500)], 0.10, 0.10)
    assert v == 'partial'


def test_refusals():
    assert verdict('e', [], [(0.10, 5)], 0.10, 0.10)[0] is None
    assert verdict('e', None, [(0.10, 5)], 0.10, 0.10)[0] is None


def test_float_dust_tolerance():
    assert depth_at([(0.10499999999999998, 2223.0)], 0.105) == 2223.0
