"""Item-82 holdout tests (synthetic only, no network)."""
from research.holdout import split_series, split_groups, stability_verdict


def test_purge_gap_drops_both_sides():
    rows = [(t,) for t in (0, 3599, 3600, 3601, 7199, 7200, 7201, 10800, 14400)]
    early, late = split_series(rows, 7200, purge_h=1.0)
    assert [r[0] for r in early] == [0, 3599]  # 3600 sits on the boundary
    assert [r[0] for r in late] == [14400]  # 7201..10800 inside the gap
    assert split_series(rows, 'junk') == (None, None)


def test_spanning_groups_dropped():
    rows = [('a', 100), ('a', 500), ('b', 600), ('c', 100), ('c', 200)]
    early, late = split_groups(rows, 400, group_key=0, time_key=1)
    assert [r[0] for r in early] == ['c', 'c']
    assert [r[0] for r in late] == ['b']
    # 'a' spans the cut (100 < 400 < 500): dropped


def test_stability_verdicts():
    assert stability_verdict(0.26, 0.28) == 'stable'
    assert stability_verdict(0.26, 0.60) == 'reversed'
    assert stability_verdict(0.26, 0.40) == 'unstable'
    assert stability_verdict(None, 0.1) == 'unknown'
