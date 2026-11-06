"""Item-70 calendar/response tests (synthetic only, no network)."""
from research.calendar import register, response


def _series(mids, t0=1_000_000, step=3600):
    return [(t0 + i * step, m) for i, m in enumerate(mids)]


def test_response_ratio():
    s = _series([0.50] * 24 + [0.50] * 12 + [0.56] + [0.56] * 11)
    r = response(s, 1_000_000 + 24 * 3600)
    assert r['pre_move'] == 0.0 and r['post_move'] == 0.06
    assert r['ratio'] is None  # zero baseline: ratio undefined, moves kept


def test_non_response_ratio_one():
    s = _series([0.50 + 0.001 * i for i in range(24)]
                + [0.524 + 0.001 * i for i in range(24)])
    r = response(s, 1_000_000 + 24 * 3600)
    assert r['ratio'] == 1.0


def test_short_coverage_refuses():
    assert response(_series([0.5] * 5), 1_000_000 + 24 * 3600) is None
    assert response(_series([0.5] * 50), None) is None


def test_dateless_events_never_study():
    e = register('poll', 'IA-Gov', None, 'src 2026-10-05')
    assert e is not None and e['at'] is None
    assert register('', 'IA-Gov', 't', 'src') is None
