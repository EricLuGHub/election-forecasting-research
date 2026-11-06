"""Item-90 rejection ledger tests (fake books)."""
from research.rejectlog import review


class FakeClient:
    def __init__(self, books):
        self.books = books

    def get(self, path, **kw):
        if path == '/tournaments':
            return {'data': [{'id': 'tid'}]}
        eid = path.split('/exchanges/')[1].split('/')[0]
        return self.books[eid]


def test_verdicts():
    books = {
        # rich pair: NO costs 0.90+0.05=0.95 x1000 -> edge +50: missed-winner
        'R': {'bids': [{'price': 0.10, 'quantity': 5000}]},
        'D': {'bids': [{'price': 0.95, 'quantity': 5000}]},
        # thin pair: insufficient depth -> thin
        'T': {'bids': [{'price': 0.50, 'quantity': 10}]},
        'U': {'bids': [{'price': 0.50, 'quantity': 10}]},
        # short still rich: bid above refusal -> stands
        'S': {'bids': [{'price': 0.20, 'quantity': 5000}]},
        # short faded below refusal -> stands (thesis confirmed, edge gone too)
        'F': {'bids': [{'price': 0.065, 'quantity': 5000}]},
    }
    import research.rejectlog as R
    R.REFUSALS = [
        ('rich', 'basket', 1000, 5.0, ('R', 'D'), ''),
        ('thin', 'basket', 1000, 5.0, ('T', 'U'), ''),
        ('held', 'short', 500, 0.16, ('S',), ''),
        ('faded', 'short', 500, 0.16, ('F',), ''),
    ]
    try:
        rows = review(FakeClient(books))
    finally:
        import importlib
        importlib.reload(R)
    by_name = {r['name']: r for r in rows}
    assert by_name['rich']['verdict'] == 'missed-winner'
    assert by_name['rich']['now_edge'] == 50.0
    assert by_name['thin']['state'] == 'thin'
    # richness returned above refusal -> revisit (edge may be back)
    assert by_name['held']['verdict'] == 'revisit'
    # faded below refusal -> stands (thesis confirmed, nothing to revisit)
    assert by_name['faded']['verdict'] == 'stands'
