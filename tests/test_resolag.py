"""Item-79 resolution-lag tests (synthetic only, no network)."""
from research.resolag import race_lag, horizon_days


def test_classes():
    assert race_lag('GA')[0] == 'runoff-risk'
    assert race_lag('MS')[0] == 'runoff-risk'
    assert race_lag('LA')[0] == 'clear'  # 2026 closed primaries, no runoff
    assert race_lag('IA')[0] == 'clear'
    assert race_lag('X', contract='control')[0] == 'manual'


def test_horizons():
    assert horizon_days('clear') == 29
    assert horizon_days('runoff-risk') == 57
    assert horizon_days('manual') is None
