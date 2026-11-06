"""Item-83 policy baselines tests (synthetic only, no network)."""
from research.policybase import cash, stressed_cash, compare


TABLE = {
    'a': {'o1': None, 'o2': 100.0, 'o3': 105.0, 'floor': 95.0, 'fill': 104.0},
    'b': {'o1': None, 'o2': None, 'floor': 90.0, 'fill': None},
}


def test_cash_rules():
    assert cash(TABLE, 'a', 'hold') == (95.0, 'floor')
    assert cash(TABLE, 'a', 'first')[0] == 100.0
    assert cash(TABLE, 'a', 'gated') == (104.0, 'realized fill')
    assert cash(TABLE, 'b', 'gated')[0] == 90.0
    assert cash(TABLE, 'zzz', 'hold') == (None, 'floor')


def test_stressed():
    assert stressed_cash(1000.0, 1000) == 995.0
    assert stressed_cash(None, 5) is None


def test_compare_verdicts():
    out = compare(TABLE, ['a', 'b'], {'a': 100, 'b': 100})
    assert out['a']['verdict'] == 'timing-adds'  # 104 > 100 > 95
    assert out['a']['gated_stressed'][0] == 103.5
    assert out['b']['verdict'] in ('hold-wins', 'timing-holds', 'mixed')
