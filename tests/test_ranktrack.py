"""Item-10 tracker tests (synthetic boards)."""
from research.ranktrack import summarize, overlap


def _row(i, pnl, name='u%d'):
    return {'id': 'p%d' % i, 'username': name % i, 'pnl': pnl, 'rank': i + 1}


def test_summarize_cutoff_and_self():
    rows = [_row(i, 1000.0 - i * 10.0) for i in range(25)]
    rows[7] = {'id': 'me', 'username': 'happy-pebble-3751', 'pnl': 930.0, 'rank': 8}
    s = summarize(rows, 'all')
    assert len(s['top_ids']) == 20
    assert s['cutoff_top20'] == 1000.0 - 19 * 10.0
    assert s['self']['username'] == 'happy-pebble-3751'


def test_overlap():
    assert overlap(['a', 'b', 'c'], ['b', 'c', 'd']) == round(2 / 3, 3)
    assert overlap([], ['a']) is None
    assert overlap(['a'], ['b']) == 0.0


def test_snapshot_reads_leaderboard_key():
    from research.ranktrack import snapshot

    class C:
        def get(self, path, **kw):
            return {'leaderboard': [{'profileId': 'p1', 'username': 'a',
                                     'pnl': 10.0, 'rank': 1}], 'total': 999}

    rows = snapshot(C())
    assert len(rows) == 1 and rows[0]['profileId'] == 'p1'
