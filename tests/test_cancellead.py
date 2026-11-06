"""Item-57 cancellation tests (synthetic only, no network)."""
from research.cancellead import should_cancel, keep_priority


def test_book_trigger():
    assert should_cancel('buy', 0.50, 0.48, 0.49, None, None, 10.0)[0] is True
    assert should_cancel('buy', 0.50, 0.495, 0.505, None, None, 10.0) == (False, 'hold')
    assert should_cancel('sell', 0.50, 0.51, 0.52, None, None, 10.0)[0] is True
    assert should_cancel('sell', 0.50, 0.51, 0.49, None, None, 10.0) == (False, 'hold')


def test_age_cap_and_reference():
    assert should_cancel('buy', 0.50, 0.50, 0.51, None, None, 120.0) == (True, 'age cap')
    assert should_cancel('buy', 0.50, 0.50, 0.51, 0.60, 0.58, 10.0)[0] is True
    assert should_cancel('buy', 0.50, 0.50, 0.51, 0.60, 0.61, 10.0) == (False, 'hold')


def test_priority_and_refusals():
    assert keep_priority(0.50, 0.505) is True
    assert keep_priority(0.50, 0.52) is False
    assert should_cancel('buy', 'x', 0.5, 0.5, None, None, 1.0) == (False, 'bad inputs')
    assert should_cancel('buy', 0.5, None, None, None, None, 1.0) == (False, 'no book')
