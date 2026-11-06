"""Item-53 normalization tests (synthetic only, no network)."""
from research.normbook import normalize, book_balance


def test_normalize_sides():
    n = normalize(-500, 0.16, 0.155, 'YES')
    assert n['booked'] == 'short-YES' and n['direction'] == 'longshot'
    assert n['capital'] == 80.0
    n = normalize(1000, 0.97, 0.99, 'NO')
    assert n['booked'] == 'long-NO' and n['direction'] == 'favorite'
    assert normalize(0, 0.5, 0.5, 'YES') is None
    assert normalize(100, 0.5, 1.5, 'YES') is None
    assert normalize(100, 0.5, 0.5, 'MAYBE') is None


def test_balance_verdicts():
    fav = [normalize(100, 0.9, 0.9, 'YES')]
    longs = [normalize(-100, 0.1, 0.1, 'YES') for _ in range(9)]
    b = book_balance(fav + longs)
    assert b['longshot_share'] == round(90.0 / 180.0, 3)
    assert b['verdict'] == 'balanced'
    assert book_balance(longs)['verdict'] == 'single-direction'
    assert book_balance([])['verdict'] == 'empty'
