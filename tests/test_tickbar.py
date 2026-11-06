"""Item-48 tick-threshold tests in venue ticks (synthetic only)."""
from research.tickbar import to_vticks, bucket_expected, eligible


def test_integer_venue_ticks():
    assert to_vticks(0.12) - to_vticks(0.10) == 4  # 2c = 4 venue ticks
    assert to_vticks(0.105) == 21
    assert to_vticks(0.10) == 20
    assert to_vticks('junk') is None


def test_expected_capture_vticks():
    assert bucket_expected(8, 0.5, 'join') == 2.0
    assert bucket_expected(8, 0.5, 'improve') == 3.0
    assert bucket_expected(2, 0.5, 'improve') == 0.0  # 1-tick spread: eaten
    assert bucket_expected(4, 0.3, 'join') == 0.6
    assert bucket_expected(-1, 0.5, 'join') is None


def test_eligible_set_vticks():
    buckets = [(2, 0.3), (4, 0.45), (6, 0.6), (8, 0.72)]
    assert eligible(buckets, 'join', min_expected=1.0) == [6, 8]
    assert eligible(buckets, 'improve', min_expected=1.0) == [4, 6, 8]
