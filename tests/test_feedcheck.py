"""Item-24 feedcheck tests (tmp sqlite + fake client)."""
import json
import sqlite3
from research.feedcheck import latest_obs, check_venue


def _history(tmp_path, rows):
    path = str(tmp_path / 'h.sqlite3')
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE observations (id INTEGER PRIMARY KEY, at TEXT, '
               'kind TEXT, resource TEXT, payload TEXT)')
    for i, (at, eid, bid, ask) in enumerate(rows):
        db.execute('INSERT INTO observations VALUES (?,?,?,?,?)',
                   (i, at, 'quote_change', eid,
                    json.dumps({'bestBid': bid, 'bestAsk': ask})))
    db.commit()
    db.close()
    return path


class FakeClient:
    def __init__(self, books):
        self.books = books

    def get(self, path, **kw):
        eid = path.split('/exchanges/')[1].split('/')[0]
        return self.books[eid]


def _book(bid, ask, seq=99):
    return {'asOf': {'sequence': seq}, 'bids': [{'price': bid, 'quantity': 10}],
            'asks': [{'price': ask, 'quantity': 10}]}


def test_ok_and_diverged(tmp_path):
    path = _history(tmp_path, [('2026-10-05T12:00:00+00:00', 'E1', 0.10, 0.12)])
    c = FakeClient({'E1': _book(0.10, 0.12)})
    from datetime import datetime, timezone
    now = datetime(2026, 10, 5, 12, 0, 30, tzinfo=timezone.utc)
    row = check_venue(c, 'tid', path, 'E1', now=now)
    assert row['verdict'] == 'ok' and row['rest_seq'] == 99
    c2 = FakeClient({'E1': _book(0.20, 0.22)})
    row2 = check_venue(c2, 'tid', path, 'E1', now=now)
    assert row2['verdict'] == 'diverged' and row2['diff'] == 0.10


def test_no_obs(tmp_path):
    path = _history(tmp_path, [])
    row = check_venue(FakeClient({'E9': _book(0.1, 0.2)}), 'tid', path, 'E9')
    assert row['verdict'] == 'no_obs'
    assert latest_obs(path, 'E9') is None
