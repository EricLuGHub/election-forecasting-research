"""Item-84 execution stress tests (synthetic only, no network)."""
from research.stress import apply_delay, apply_vanish, walk_proceeds, partial_fill, orphan_residual


def test_delay_and_vanish():
    assert apply_delay([(0.10, 100), (0.91, 100)], 2) == [(0.09, 100), (0.9, 100)]
    assert apply_delay(None, 1) is None
    assert apply_vanish([[(0.1, 5), (0.09, 5)], [(0.9, 5)]], 1) == [[(0.09, 5)], []]
    assert apply_vanish(None, 1) is None


def test_walk_proceeds():
    assert walk_proceeds([(0.10, 100), (0.09, 100)], 150) == 14.5
    assert walk_proceeds([(0.10, 100)], 150) is None  # no assumed remainder
    assert walk_proceeds(None, 5) is None


def test_partial_and_orphan():
    # 316 at 0.96 limit; half fills, rest 3 ticks worse
    assert partial_fill(303.36, 316, 0.5, 3) == round(0.5 * 303.36 + 158 * (0.96 - 0.015), 2)
    assert partial_fill(303.36, 316, 1.0, 3) == 303.36
    o = orphan_residual(303.36, 316, 0.07, True)
    assert o == {'cash': 303.36, 'stranded_mark': 22.12, 'floor_intact': True}
    assert orphan_residual(None, 1, 0.1, True) is None
