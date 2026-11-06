"""Item-22 shared cache tests (tmp paths only, no network)."""
from research.mdache import get_or_fetch, stats


def test_miss_then_hit(tmp_path):
    path = str(tmp_path / 'md.json')
    calls = []

    def fetch():
        calls.append(1)
        return {'a': 1}

    v1, fresh1, hit1 = get_or_fetch('k', 300.0, fetch, path=path, now=1000.0)
    assert (v1, fresh1, hit1) == ({'a': 1}, True, False)
    v2, fresh2, hit2 = get_or_fetch('k', 300.0, fetch, path=path, now=1100.0)
    assert (v2, fresh2, hit2) == ({'a': 1}, True, True)
    assert len(calls) == 1
    assert stats(path)['k'] == {'misses': 1, 'hits': 1}


def test_expiry_refetches(tmp_path):
    path = str(tmp_path / 'md.json')
    n = [0]

    def fetch():
        n[0] += 1
        return n[0]

    get_or_fetch('k', 300.0, fetch, path=path, now=1000.0)
    v, _, hit = get_or_fetch('k', 300.0, fetch, path=path, now=1400.0)
    assert (v, hit) == (2, False)


def test_fetch_errors_propagate_no_stale(tmp_path):
    path = str(tmp_path / 'md.json')

    def good():
        return 1

    def bad():
        raise RuntimeError('downstream down')

    get_or_fetch('k', 300.0, good, path=path, now=1000.0)
    try:
        get_or_fetch('k', 300.0, bad, path=path, now=5000.0)
        raised = False
    except RuntimeError:
        raised = True
    assert raised is True
