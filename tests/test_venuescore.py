"""Item-55 venue scoring tests (synthetic only, no network)."""
from research.venuescore import shrink, select_allowlist, validate


def test_shrinkage():
    assert shrink(1.0, 2, 0.0) == round((2 * 1.0) / 12, 4)  # tiny -> baseline
    assert shrink(1.0, 1000, 0.0) == round(1000 / 1010, 4)  # big -> itself
    assert shrink(1.0, 0, 0.0) is None
    assert shrink('x', 5, 0.0) is None


def test_select_and_validate():
    scores = {'a': 0.5, 'b': -0.1, 'c': 0.3}
    assert select_allowlist(scores) == ['a', 'c']
    assert select_allowlist(scores, bar=0.4) == ['a']
    assert validate(['a', 'c'], {'a': 1, 'c': -1, 'z': 1}) == {'n': 2, 'agree_rate': 0.5}
    assert validate(['a'], {'z': 1}) is None
