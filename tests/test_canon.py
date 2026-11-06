"""Item-31 canonical enumeration tests (synthetic only, no network)."""
from research.canon import enumerate_pairs


def _mk(mid, title, race='R1', party_rt=True):
    return {'mid': mid, 'title': title, 'eid': 'e' + str(mid),
            'resolutionType': 'Party Winner' if party_rt else 'Other',
            'raceId': race, 'stageId': 'S', 'electionDate': '2026-11-03',
            'raceStage': 'General'}


def test_clean_pair():
    pairs, excl = enumerate_pairs(
        [_mk(1, 'Ohio Senate Republican'), _mk(2, 'Ohio Senate Democratic')])
    assert len(pairs) == 1 and excl == []
    assert pairs[0]['eids'] == {'Republican': 'e1', 'Democratic': 'e2'}


def test_exclusions_recorded():
    mkts = [_mk(1, 'Ohio Senate Republican'),
            _mk(2, 'Control of Senate', race='C1'),
            _mk(3, 'Mystery Market', race='C1'),
            _mk(4, 'X Republican', race=None),
            _mk(5, 'Y Other', party_rt=False),
            _mk(6, 'Lone Wolf Republican', race='L1')]
    pairs, excl = enumerate_pairs(mkts)
    assert pairs == []
    reasons = dict(excl)
    # Control / mystery titles carry no party token (c149 verdict stands).
    assert reasons[2] == 'no unique R/D party in title'
    assert reasons[3] == 'no unique R/D party in title'
    assert reasons[4] == 'missing race metadata'
    assert reasons[5] == 'non-party resolution'
    assert 'single-party' in reasons[6] and 'Democratic' in reasons[6]


def test_duplicate_party_excluded():
    mkts = [_mk(1, 'Ohio Senate Republican'), _mk(9, 'Ohio Senate Republican Runoff'),
            _mk(2, 'Ohio Senate Democratic')]
    pairs, excl = enumerate_pairs(mkts)
    assert pairs == []
    assert any('duplicate Republican' in r for _, r in excl)


def test_missing_metadata_excluded():
    mk = _mk(1, 'Ohio Senate Republican')
    del mk['raceId']
    pairs, excl = enumerate_pairs([mk])
    assert pairs == [] and excl == [(1, 'missing race metadata')]
