"""Item-5 funnel tests."""
from research.funnel import funnel, bottleneck


def test_gates_attach_dollars():
    rounds = [{'fired': [{'edge': 20.0}],
               'refused': [{'edge': 10.0, 'reason': 'below_15_rule'}],
               'blocked': [{'edge': 30.0, 'reason': 'total_cap_20k'}]}]
    rep = funnel(rounds)
    assert rep['gates']['fired'] == {'n': 1, 'edge': 20.0}
    assert rep['gates']['refused_edge'] == {'n': 1, 'edge': 10.0}
    assert rep['gates']['blocked_capital'] == {'n': 1, 'edge': 30.0}
    assert rep['gates']['depth_walked'] == {'n': 2, 'edge': 30.0}
    assert rep['refusal_reasons'] == {'below_15_rule': 1}


def test_bottleneck_names_largest_recoverable():
    assert bottleneck(funnel([{'fired': [], 'refused': [{'edge': 5.0}],
                                       'blocked': [{'edge': 50.0}]}])) == ('capital', 50.0)
    assert bottleneck(funnel([{'fired': [{'edge': 5.0}], 'refused': [],
                                       'blocked': []}])) == ('opportunity_supply', 0.0)
