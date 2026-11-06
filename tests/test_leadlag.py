"""Item-66 lead-lag tests (synthetic only, no network)."""
from research.leadlag import lag_corr, level_gap


def _series(mids, t0=1000, step=60):
    return [(t0 + i * step, m) for i, m in enumerate(mids)]


def test_perfect_lag_one_detected():
    k = _series([0.80, 0.81, 0.80, 0.82, 0.81, 0.83])
    s = _series([0.50, 0.50, 0.51, 0.50, 0.52, 0.51])
    out = lag_corr(k, s)
    assert out[1] == 1.0 and out[0] != 1.0


def test_contemporaneous_detected():
    m = [0.80, 0.81, 0.83, 0.82, 0.84]
    out = lag_corr(_series(m), _series(m))
    assert out[0] == 1.0


def test_insufficient_is_none_not_zero():
    out = lag_corr(_series([0.8, 0.81]), _series([0.5, 0.51]))
    assert out == {0: None, 1: None, 2: None, 3: None}


def test_bad_clocks_refuse():
    assert lag_corr([(5, 0.8), (5, 0.81)], [(5, 0.5), (6, 0.51)]) is None
    assert lag_corr([(1, 0.8)], [(1, 0.5)]) == {0: None, 1: None, 2: None,
                                                3: None}


def test_level_gap():
    assert level_gap(0.885, 0.86) == (0.025, 'level gap')
    assert level_gap(None, 0.5)[0] is None
