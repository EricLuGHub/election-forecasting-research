"""Item-71 forecast-delta tests (synthetic only, no network)."""
from research.forecastdelta import version, change_gate, sig_comparison


def test_gate_blocks_noise_passes_moves():
    old = version('pf', 't1', 0.63, 0.15)
    same = version('pf', 't2', 0.63, 0.15)
    assert change_gate(old, same) == (False, {'reason': 'identical content re-retrieved — not news'})
    small = version('pf', 't2', 0.70, 0.15)
    assert change_gate(old, small)[0] is False  # 0.07 < 0.30
    big = version('pf', 't2', 0.85, 0.06)
    fire, d = change_gate(old, big)
    assert fire is True and d['move'] == 0.22


def test_source_mismatch_and_bad_versions():
    assert change_gate(None, version('x', 't', 0.5, 0.1))[0] is False
    assert version('', 't', 0.5, 0.1) is None
    assert version('x', 't', 1.5, 0.1) is None


def test_sig_comparison():
    assert sig_comparison(0.05, 0.03) == 'confirmation'
    assert sig_comparison(0.05, -0.03) == 'divergence'
    assert sig_comparison(0.05, 0.001) == 'stale-or-priced'
    assert sig_comparison(None, 0.1) == 'unknown'
