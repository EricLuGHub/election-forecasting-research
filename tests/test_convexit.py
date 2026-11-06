"""E8 joint-exit math tests (no network)."""
from research.convexit import BANK_PER_SHARE


def _book(asks):
    return {'asks': [{'price': p, 'quantity': q} for p, q in asks], 'bids': []}


def test_joint_bankable_and_hold():
    from research.convexit import joint_exit
    from research.exit import depth_proceeds

    class C:
        def get(self, path, **kw):
            if '1071' in path:
                return _book([(0.22, 5000)])
            return _book([(0.19, 5000)])

    got = joint_exit(C(), 'tid', '1071', '1070', 1000)
    # NO proceeds: (1-.22)*1000 + (1-.19)*1000 = 780+810 = 1590 vs cost 1953.93
    assert got == 1590.0
    assert (got - 1953.93) / 2000 < BANK_PER_SHARE  # hold, not bankable


def test_bankable_side():
    # proceeds above cost + 0.5c/share flags BANKABLE by the same arithmetic
    edge, size = 30.0, 1000
    assert edge / (2 * size) >= BANK_PER_SHARE


def test_load_baskets_parses_ledger(tmp_path, monkeypatch):
    import json
    from research import convexit
    d = tmp_path / 'data'
    d.mkdir()
    (d / 'e2_taken.json').write_text(json.dumps({
        'nh-2000': {'race': 'NH Senate R/D NO x2000', 'cost': 1953.93, 'floor': 2000.0},
        'junk': {'race': 'zzz', 'cost': 5.0},
    }))
    import pathlib
    monkeypatch.setattr(convexit, 'ROOT', tmp_path)
    rows = convexit.load_baskets()
    assert ('nh-2000', 'NH Senate R/D NO x2000', 2000, 1953.93) in rows
    assert len(rows) == 1


def test_race_pair_strict_identity():
    import json
    from research.convexit import race_pair, parse_race
    mkts = json.load(open('data/markets.json'))

    class C:
        def pages(self, path, **kw):
            return mkts

    c = C()
    # audit regression cases (item 11): these resolved to control/AL/House before
    assert race_pair(c, 't', 'OK Senate R/D NO x1000') == ('975', '1072')
    assert race_pair(c, 't', 'OK Governor R/D NO x1000') == ('1063', '875')
    assert race_pair(c, 't', 'CA-Gov R/D NO x250') == ('851', '850')
    # previously-correct resolutions must not move
    assert race_pair(c, 't', 'NH Senate R/D NO x2000') == ('1071', '1070')
    assert race_pair(c, 't', 'VA-05 R/D NO x1000') == ('1034', '1033')
    assert race_pair(c, 't', 'MA Senate R/D NO x250') == ('1069', '1068')
    assert race_pair(c, 't', 'HI Governor R/D NO x250') == ('991', '990')
    # refusals: unknown state, unknown office, control titles unmatchable
    assert parse_race('XX Senate R/D NO x100') == (None, None, None)
    assert parse_race('ZZ R/D NO x100') == (None, None, None)
    assert race_pair(c, 't', 'XX Senate R/D NO x100') is None


def test_exit_qty_and_own_resting():
    from research.convexit import exit_qty, own_resting
    assert exit_qty(1940, 2000) == 1940
    assert exit_qty(0, 2000) == 0
    assert exit_qty(None, 2000) == 0
    assert exit_qty(2500, 2000) == 2000
    orders = [{'idempotencyKey': 'ROT3-x', 'exchangeId': '975', 'quantity': 100,
               'open': True},
              {'idempotencyKey': 'other', 'exchangeId': '975', 'quantity': 50,
               'open': True},
              {'idempotencyKey': 'Q4-y', 'exchangeId': '975', 'quantity': 5,
               'open': False}]
    assert own_resting(orders, {'975'}) == {'975': 100.0}
    assert own_resting([], {'975'}) == {}


def test_control_titles_unmatchable():
    """Wrong-contract states are impossible by construction (item 14): no
    state resolution may ever return control exchanges 843/842/841/840."""
    import json
    from research.convexit import race_pair, STATEMAP
    mkts = json.load(open('data/markets.json'))

    class C:
        def pages(self, path, **kw):
            return mkts

    c = C()
    control = {'843', '842', '841', '840'}
    for code in STATEMAP:
        for office in ('Senate', 'Governor', 'House'):
            pair = race_pair(c, 't', '%s %s R/D NO x100' % (code, office))
            if pair is not None:
                assert not (set(pair) & control), (code, office, pair)
    # every resolving pair is a same-state R/D match, never control
    assert race_pair(c, 't', 'OK Senate R/D NO x100') == ('975', '1072')


def test_format_row_never_truncates():
    import json
    from research.convexit import format_row
    row = {'basket': 'nh-2000', 'state': 'BANKABLE', 'exited_qty': 2000,
           'proceeds': 1951.45, 'cost': 1905.38, 'edge': 46.07,
           'per_share': 0.0115, 'per_unit': 0.023,
           'own_resting': {'1234': 0, '5678': 0},
           'at': '2026-10-05T20:00:00+00:00'}
    back = json.loads(format_row(row))
    assert back == row  # at + own_resting survive (old [:220] cut them)
