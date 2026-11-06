"""Item-54 strategy separation tests (synthetic only, no network)."""
from research.makervsbuy import classify, STRATEGIES


def test_specs_differ():
    assert STRATEGIES['maker']['horizon'] != STRATEGIES['buyer']['horizon']
    assert STRATEGIES['maker']['bar'] != STRATEGIES['buyer']['bar']


def test_classify_our_book():
    assert classify('E2', True, False, True, 29)[0] == 'buyer'
    assert classify('v4', False, True, False, 0.1)[0] == 'maker'
    assert classify('E1-REDUCE', True, False, False, 30)[0] == 'neither'
    assert classify('X', True, True, True, 'junk')[0] == 'neither'
