"""Item-46 venue ranking tests (synthetic only, no network)."""
from research.venuerank import score, rank


def test_score_math_and_cap():
    assert score(10, 2, 5, 0.25) == round(10 * 2 * 5 * 0.75, 3)
    assert score(10, 2, 500, 0.25) == score(10, 2, 20, 0.25)  # depth cap
    assert score(10, 2, 5, 1.0) == 0.0  # fully toxic earns nothing
    assert score(-1, 2, 5, 0.2) is None
    assert score(None, 2, 5, 0.2) is None


def test_rank_orders_and_pushes_unscorable_last():
    out = rank([('a', 1, 1, 1, 0.2), ('b', 9, 2, 9, 0.1), ('c', None, 1, 1, 0.1)])
    assert [e for e, _ in out] == ['b', 'a', 'c']
    assert out[-1][1] is None
