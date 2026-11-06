"""Item-64 settlement-basis tests (synthetic only, no network)."""
from research.basis import classify, pair_basis


def _root(winner, race='R1', rtype='Party Winner', ctype='Election Outcome',
          date='2026-11-04T17:00:00.000Z'):
    return {'contract_type': ctype, 'settlement_date': date,
            'settled_with': None,
            'contract_details': {'resolutionType': rtype, 'raceId': race,
                                 'stageId': 'S', 'electionDate': '2026-11-03',
                                 'raceStage': 'General',
                                 'winnerName': winner}}


def test_matching_pair_passes():
    v, d = pair_basis('x', _root('Republican Party'), _root('Democratic Party'))
    assert v == 'pass'


def test_control_leg_rejects():
    v, d = pair_basis('x', _root('Republican Party'),
                      _root('Democratic Party', rtype='Chamber Control',
                            ctype='Chamber Control'))
    assert v == 'reject' and 'defeats' in d['why']


def test_scope_mismatch_reviews():
    v, _ = pair_basis('x', _root('Republican Party'),
                      _root('Democratic Party', race='R2'))
    assert v == 'review'


def test_null_semantics_reviews_not_passes():
    v, _ = pair_basis('x', {}, _root('Democratic Party'))
    assert v == 'review'
    assert classify({})[0] == 'unknown'


def test_same_winner_rejects():
    v, _ = pair_basis('x', _root('Republican Party'),
                      _root('Republican Party'))
    assert v == 'reject'
