"""Item-62 short-book tests (synthetic only, no network)."""
from research.shortbook import analyze, wave_loss


def test_certified():
    s, d = analyze('x', 'R', 500, 80.0, 500.0, 40.0, 0.02)
    assert s == 'certified' and d['banked_now'] == 40.0
    assert d['max_loss'] == 420.0 and d['bound_cost'] == 10.0


def test_watch_when_cover_above_premium():
    s, d = analyze('x', 'D', 500, 55.0, 500.0, 70.0, 0.02)
    assert s == 'watch' and d['banked_now'] == -15.0


def test_breach_when_bound_fails():
    s, d = analyze('x', 'R', 500, 47.5, 500.0, 30.0, 0.20)
    assert s == 'breach'  # 0.20*500=100 >= 47.5


def test_unmeasurable_cover_caps_at_watch():
    s, d = analyze('x', 'R', 500, 47.5, 500.0, None, 0.02)
    assert s == 'watch' and d['banked_now'] is None


def test_refusals():
    assert analyze('x', 'R', 0, 50.0, 500.0, 10.0, 0.02)[0] is None
    assert analyze('x', 'R', 500, 50.0, 500.0, 10.0, 1.5)[0] is None


def test_wave_aggregation():
    rows = [analyze('a', 'R', 500, 80.0, 500.0, 40.0, 0.02),
            analyze('b', 'R', 500, 47.5, 500.0, 30.0, 0.02),
            analyze('c', 'D', 500, 55.0, 500.0, 70.0, 0.02)]
    w = wave_loss(rows)
    assert w == {'R': -872.5, 'D': -445.0}
