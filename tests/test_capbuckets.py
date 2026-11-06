"""Item-109 capacity label tests (synthetic only, no network)."""
from research.capbuckets import label_book, executable_only, gate


def test_buckets_separated():
    b = label_book(1000, 1.0, 307.50, 2192.50, 30000)
    assert b['guaranteed_floor'] == 1000.0
    assert b['premium_contingent'] == 307.50
    assert b['stress_loss'] == 2192.50 + 0.05 * 30000
    assert b['max_loss_bound'] == 2192.50 + (30000 - 1000.0)
    assert b['unvalued'] == []
    assert label_book(-1, 1, 0, 0, 0) is None


def test_executable_no_mark_substitution():
    r = executable_only([100.0, 200.0], ['E9', 'E10'])
    assert r == {'executable_proceeds': 300.0, 'unvalued': ['E9', 'E10']}
    assert executable_only(None, []) is None


def test_gate():
    labels = {'guaranteed_floor': 1000.0, 'premium_contingent': 300.0,
              'stress_loss': 900.0, 'unvalued': ['X']}
    assert gate(labels)[0] is False  # unvalued not accepted
    labels['unvalued_accepted'] = True
    assert gate(labels) == (True, {'margin': 400.0})
    assert gate(dict(labels, stress_loss=1500.0))[0] is False
