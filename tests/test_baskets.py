"""Item-28 basket runner tests (pure parts + dry-run fire)."""
from research.baskets import walk_cost, verify, fire, MIN_EDGE


class FakeClient:
    def __init__(self, books):
        self.books = books

    def get(self, path, **kw):
        if 'orderbook' in path:
            eid = path.split('/exchanges/')[1].split('/')[0]
            return self.books[eid]
        if path == '/tournaments':
            return {'data': [{'id': 'tid'}]}
        raise AssertionError(path)


NOW = 1791201610.0  # AT + 10s: reads 10s old, inside all windows
AT = '2026-10-05T12:00:00+00:00'


def _books():
    return {'R': {'asOf': {'at': AT}, 'bids': [{'price': 0.20, 'quantity': 2000}]},
            'D': {'asOf': {'at': AT}, 'bids': [{'price': 0.75, 'quantity': 2000}]}}


def test_walk_cost():
    c = FakeClient(_books())
    cost, worst, filled, _ = walk_cost(c, 'tid', 'R', 1000)
    assert cost == 800.0 and worst == 0.80 and filled is True
    cost2, _, filled2, _ = walk_cost(c, 'tid', 'R', 5000)
    assert filled2 is False


def test_verify_rule():
    books = {'901': {'asOf': {'at': AT}, 'bids': [{'price': 0.10, 'quantity': 2000}]},
             '902': {'asOf': {'at': AT}, 'bids': [{'price': 0.85, 'quantity': 2000}]}}
    c = FakeClient(books)
    # NO costs: R 0.90*1000 + D 0.15*1000 = 1050 > 1000 floor -> refused
    rows = list(verify(c, 'tid', [(0.0, 'X', '901', '902', 0.1, 0.85)], size=1000, now=NOW))
    assert rows[0]['verified'] is False
    assert rows[0]['reason'] == 'below_rule'


def test_verify_and_dry_fire():
    books = {'901': {'asOf': {'at': AT}, 'bids': [{'price': 0.15, 'quantity': 2000}]},
             '902': {'asOf': {'at': AT}, 'bids': [{'price': 0.90, 'quantity': 2000}]}}
    c = FakeClient(books)
    rows = list(verify(c, 'tid', [(0.05, 'Y', '901', '902', 0.15, 0.90)], size=1000, now=NOW))
    assert rows[0]['verified'] is True
    assert rows[0]['edge'] == 50.0
    class Exe:
        dry_run = True
        def journal(self): return {}
        def submit_basket(self, basket, expected_capital=0.0):
            return {'dry_run': True, 'basket': basket}
    out = fire(c, rows, live=False, executor=Exe(), tid='tid')
    assert str(out[0]['orders']).startswith('dry_run')
    assert out[0]['edge'] == 50.0


def test_fire_skips_unverified():
    class Exe:
        dry_run = True

        def journal(self):
            return {}

    c = FakeClient(_books())
    out = fire(c, [{'basket': 'Z', 'verified': False, 'reason': 'thin'}],
               live=False, executor=Exe(), tid='tid')
    assert out[0]['skipped'] is True


def _exit_client():
    class C:
        def get(self, path, **kw):
            if 'orderbook' in path:
                eid = path.split('/exchanges/')[1].split('/')[0]
                # NO proceeds 0.95/share on both legs
                return {'bids': [], 'asks': [{'price': 0.05, 'quantity': 5000}]}
            raise AssertionError(path)

        def pages(self, path, **kw):
            return []

    return C()


def test_exit_intents_bankable_hold_depleted():
    # Books price NO exits at 0.05/share: proceeds 50 per 1000-share leg.
    from research.baskets import exit_intents
    import research.baskets as B

    class C:
        def get(self, path, **kw):
            return {'bids': [], 'asks': [{'price': 0.95, 'quantity': 5000}]}

    mapping = {'full': ('R1', 'D1'), 'part': ('R2', 'D2'),
               'gone': ('R9', 'D9'), 'capped': ('R4', 'D4')}
    B.race_pair = lambda client, tid, race: mapping.get(race.split()[0])
    ledger = {
        'full': {'race': 'full Senate R/D NO x1000', 'cost': 80.0, 'floor': 1000.0},
        'part': {'race': 'part Senate R/D NO x1000', 'cost': 80.0, 'floor': 1000.0},
        'gone': {'race': 'gone Senate R/D NO x1000', 'cost': 80.0, 'floor': 1000.0},
        'capped': {'race': 'capped Senate R/D NO x1000', 'cost': 80.0, 'floor': 1000.0,
                   'round_trips': 2},
    }
    lots = lambda q: [{'side': 'NO', 'quantity': q}]

    class P(list):
        pass

    positions = [
        {'exchangeId': 'R1', 'quantity': 1000, 'lots': lots(1000)},
        {'exchangeId': 'D1', 'quantity': 1000, 'lots': lots(1000)},
        {'exchangeId': 'R2', 'quantity': 400, 'lots': lots(400)},
        {'exchangeId': 'D2', 'quantity': 1000, 'lots': lots(1000)},
        {'exchangeId': 'R4', 'quantity': 1000, 'lots': lots(1000)},
        {'exchangeId': 'D4', 'quantity': 1000, 'lots': lots(1000)},
    ]
    try:
        rows = exit_intents(C(), 'tid', ledger, positions, min_edge=15.0)
    finally:
        import importlib
        importlib.reload(B)
    by_name = {r['basket']: r for r in rows}
    # proceeds per leg (1-0.95)*1000 = 50; joint 100 vs cost 80 -> edge 20
    assert by_name['full']['reason'] == 'bankable'
    assert by_name['full']['edge'] == 20.0
    assert by_name['gone']['reason'] == 'depleted'
    assert by_name['capped']['reason'] == 'hold_roundtrip_cap'
    assert by_name['part']['exited_qty'] == 400


def test_verify_shared_venue_screen():
    from research.baskets import verify

    class C:
        def get(self, path, **kw):
            raise AssertionError('no fetch on screened pair')

    rows = list(verify(C(), 'tid', [(0.05, 'Y', '1044', '1043', 0.1, 0.9)],
                        size=1000, avoid={'1044'}))
    assert rows[0]['verified'] is False
    assert rows[0]['reason'] == 'shared_venue'


def test_verify_stale_and_skew():
    from research.baskets import verify
    old = '2026-10-05T11:50:00+00:00'  # 610s old: stale
    books = {'901': {'asOf': {'at': AT}, 'bids': [{'price': 0.15, 'quantity': 2000}]},
             '902': {'asOf': {'at': old}, 'bids': [{'price': 0.90, 'quantity': 2000}]}}
    c = FakeClient(books)
    # skew 600s > 60s limit -> older leg re-read once (same fixture: still old)
    rows = list(verify(c, 'tid', [(0.05, 'Y', '901', '902', 0.15, 0.90)],
                        size=1000, now=NOW))
    assert rows[0]['verified'] is False
    assert rows[0]['reason'] in ('stale_pair', 'thin')
    # both fresh but far apart in read time is impossible here (same call);
    # missing timestamps -> stale_pair, never silently accepted
    books2 = {'901': {'bids': [{'price': 0.15, 'quantity': 2000}]},
              '902': {'bids': [{'price': 0.90, 'quantity': 2000}]}}
    rows2 = list(verify(FakeClient(books2), 'tid',
                         [(0.05, 'Y', '901', '902', 0.15, 0.90)],
                         size=1000, now=NOW))
    assert rows2[0]['reason'] == 'stale_pair'
