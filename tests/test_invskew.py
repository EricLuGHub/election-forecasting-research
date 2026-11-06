"""Item-58 inventory skew tests (synthetic only, no network)."""
from research.invskew import pressure, rank


def test_pressure_math():
    s, c = pressure(1000, 10000, 200, 1000, 3, 5, True)
    assert s == round(0.1 * (0.5 + 0.8 + 0.25 * 0.6 + 0.25), 4)
    assert c == {'exposure': 0.1, 'thin': 0.8, 'corr': 0.6,
                 'underwater': 1.0, 'depth_known': True}
    assert pressure(100, 0, 5, 5, 0, 1, False)[0] is None
    assert pressure('x', 1, 1, 1, 0, 1, False)[0] is None


def test_rank_orders_and_parks_bad():
    out, bad = rank([('a', 0.5, {}), ('b', None, {}), ('c', 0.9, {})])
    assert [n for n, _, _ in out] == ['c', 'a'] and bad == ['b']


def test_unknown_depth_flags():
    s, c = pressure(1000, 10000, None, 1000, 3, 5, True)
    assert c['depth_known'] is False and c['thin'] is None
    assert s == round(0.1 * (0.5 + 0.25 * 0.6 + 0.25), 4)
