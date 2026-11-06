"""Item-56 quote-age tests (synthetic only, no network)."""
from research.quoteage import fill_ages, age_summary, prospective_compare


def test_fill_ages_join():
    fills = [('f1', 'o1', 1060.0), ('f2', 'o2', 2000.0), ('f3', 'o9', 3000.0)]
    ages, missed = fill_ages(fills, {'o1': 1000.0, 'o2': 1000.0})
    assert ages == [60.0, 1000.0] and missed == 1


def test_summary():
    s = age_summary([5.0, 60.0, 120.0])
    assert s['median'] == 60.0 and s['frac_over_30s'] == round(2 / 3, 3)
    assert age_summary([]) is None


def test_prospective_compare():
    r = prospective_compare([(5.0, 1.0), (60.0, 2.0), (120.0, -0.5)])
    assert r == {'rest_total': 2.5, 'cancel_total': 1.0, 'n': 3,
                 'n_canceled_away': 2}
    assert prospective_compare([(1.0, 1.0)], 'junk') is None
