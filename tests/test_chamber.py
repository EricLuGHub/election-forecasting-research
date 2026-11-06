"""Item-76 chamber scope tests (synthetic only, no network)."""
from research.chamber import senate_control, house_control, compare


def test_senate_math():
    assert senate_control(34, 31, {}) == ('TBD', 34, 31)
    c, d, r = senate_control(34, 31, {'x%d' % i: 'D' for i in range(17)})
    assert (c, d, r) == ('D', 51, 31)
    c, d, r = senate_control(34, 31, {'x%d' % i: 'R' for i in range(19)})
    assert c == 'R' and r == 50
    assert senate_control('x', 1, {}) is None


def test_house_math():
    assert house_control(200, 200, {})[0] == 'TBD'
    assert house_control(200, 200, {'a%d' % i: 'D' for i in range(18)})[0] == 'D'
    assert house_control(200, 200, {'a%d' % i: 'R' for i in range(18)})[0] == 'R'


def test_compare_needs_interval_clearance():
    assert compare(0.66, 0.05, 0.55) == 'buy'
    assert compare(0.66, 0.15, 0.60) == 'hold'
    assert compare(0.40, 0.05, 0.60) == 'sell'
    assert compare(None, 0.1, 0.5) is None
