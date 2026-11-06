"""Item-65 input-dependence tests (synthetic only, no network)."""
from research.inputs import register, audit


def test_same_family_collapses():
    recs = [register('poll-a', 'polls', 't', 'ia', 0.80),
            register('avg-b', 'aggregates', 't', 'ia', 0.82),
            register('avg-c', 'aggregates', 't', 'ia', 0.84)]
    a = audit(recs)
    assert a['effective_families'] == ['polls']  # three sources, one vote
    assert a['widen'] is False and 'single' in a['note']


def test_cross_family_disagreement_widens():
    recs = [register('polls', 'polls', 't', 'ia', 0.86),
            register('fund', 'fundamentals', 't', 'ia', 0.40)]
    a = audit(recs)
    assert a['spread'] == 0.46 and a['widen'] is True


def test_markets_track_polls_no_widen():
    recs = [register('polls', 'polls', 't', 'ia', 0.86),
            register('kalshi', 'markets', 't', 'ia', 0.88),
            register('poly', 'markets', 't', 'ia', 0.89)]
    a = audit(recs)
    assert a['effective_families'] == ['markets', 'polls']
    assert a['widen'] is False  # 0.03 spread: same story


def test_refusals():
    assert register('x', 'vibes', 't', 'ia', 0.5) is None
    assert register('x', 'polls', 't', 'ia', 1.5) is None
    assert audit([])['spread'] == 0.0
