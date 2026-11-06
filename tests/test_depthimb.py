"""Item-50 depth imbalance tests (synthetic only, no network)."""
from research.depthimb import imbalance, mid_of, hit_rate


def test_imbalance():
    assert imbalance([(0.5, 300)], [(0.52, 100)]) == 0.5
    assert imbalance([], [(0.52, 100)]) is None
    assert imbalance([(0.5, 0)], [(0.52, 0)]) is None


def test_hit_rate():
    r = hit_rate([(0.5, 0.01), (0.5, 0.02), (-0.5, -0.01), (0.5, -0.01)])
    assert r == {'n': 4, 'hit_rate': 0.75, 'mean_move': 0.0025,
                 'sd_move': 0.013}
    assert hit_rate([]) is None
    assert hit_rate([(0.5, 0.0)]) is None
