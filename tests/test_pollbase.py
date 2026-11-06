"""Item-73 polling baseline tests (synthetic only, no network)."""
from research.pollbase import weight, average


def test_weight_decay_and_sponsor():
    w0 = weight(1000, 3.0, 0, False)
    assert weight(1000, 3.0, 14, False) == w0 / 2
    assert weight(1000, 3.0, 0, True) == w0 / 2
    assert weight(1000, 0, 0, False) is None
    assert weight(-5, 3.0, 0, False) is None


def test_average_and_house():
    polls = [(10.0, 1000, 3.0, '2026-10-01T00:00:00+00:00', False, 'a'),
             (4.0, 500, 4.0, '2026-10-01T00:00:00+00:00', True, 'b')]
    r = average(polls, '2026-10-05T00:00:00+00:00')
    assert 4.0 < r['avg'] < 10.0 and r['n'] == 2
    assert r['house_effects']['b'] < 0  # b runs below consensus
    assert r['se'] >= 3.5  # election floor respected


def test_refusals():
    assert average([], '2026-10-05T00:00:00+00:00') is None
    assert average([(5.0, 100, 3.0, 'junk', False, 'a')],
                   '2026-10-05T00:00:00+00:00') is None
