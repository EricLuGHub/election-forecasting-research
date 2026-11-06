"""Item-25 acquisition tests (fake client counts fetches)."""
from research.depthacq import acquire_book, depth_needed


class FakeClient:
    def __init__(self):
        self.depths = []

    def get(self, path, **kw):
        depth = kw.get('depth', 50)
        self.depths.append(depth)
        n = max(depth, 1)
        return {'bids': [{'price': 0.10, 'quantity': 100}] * n}


def test_shallow_suffices():
    c = FakeClient()
    book, used = acquire_book(c, 'tid', 'E', size=50)
    assert used == 5 and c.depths == [5]


def test_escalates_only_as_needed():
    c = FakeClient()
    book, used = acquire_book(c, 'tid', 'E', size=600)
    assert used == 20 and c.depths == [5, 20]
    assert depth_needed(book['bids'], 600) >= 600


def test_exhausts_levels():
    c = FakeClient()
    book, used = acquire_book(c, 'tid', 'E', size=10 ** 9)
    assert used == 50 and c.depths == [5, 20, 50]


def test_zero_size_single_shallow():
    c = FakeClient()
    _, used = acquire_book(c, 'tid', 'E', size=0)
    assert used == 5
