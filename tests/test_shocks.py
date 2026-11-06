"""Item-107 shock coherence tests (synthetic only, no network)."""
from research.shocks import shift, national_wave, revalue, concentration, simulate


def test_national_wave_signs():
    w = national_wave(0.05)
    assert w == {'D': 0.05, 'R': -0.05}
    pos = [{'race': 'x', 'party': 'R', 'side': 'NO', 'qty': -100, 'p': 0.9},
           {'race': 'x', 'party': 'D', 'side': 'NO', 'qty': -100, 'p': 0.1}]
    tot, per = revalue(pos, w)
    # D wave: R-NO gains (+5), D-NO loses (-5) -> net 0 on matched pair
    assert tot == 0.0 and per == {'x': 0.0}


def test_pair_floor_across_waves():
    for shocks in ({'D': 0.5, 'R': -0.5}, {'D': -0.5, 'R': 0.5}):
        tot, per = revalue(
            [{'race': 'x', 'party': 'R', 'side': 'NO', 'qty': -100, 'p': 0.9},
             {'race': 'x', 'party': 'D', 'side': 'NO', 'qty': -100, 'p': 0.1}],
            shocks)
        assert tot == 0.0  # matched pair immune to wave direction


def test_binary_simulation():
    structs = [{'name': 'pair', 'kind': 'pair', 'race': 'x', 'qty': 100, 'cost': 97.0},
               {'name': 'sh', 'kind': 'short', 'race': 'y', 'qty': 1, 'premium': 10.0,
                'tail': 100.0, 'party': 'R'}]
    r = simulate(structs, {'x': (0.5, 0.5, 0.0), 'y': (0.1, 0.9, 0.0)},
                 rho=0.0, n=500, seed=1)
    assert r['floor_breaches'] == 0  # pairs never breach
    assert r['mean'] < 3.0 + 10.0  # pair edge + short premium minus upset rate
    assert r['p5'] < r['mean']  # tail visible


def test_concentration():
    assert concentration({'a': -100, 'b': -50, 'c': -25, 'd': -25}) == 0.875
