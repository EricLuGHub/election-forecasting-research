"""Item-47 touch calibration tests (synthetic only, no network)."""
from research.touchcal import prevailing, calibrate


def test_prevailing_no_lookbehind():
    ts = [(100.0, 0.5), (200.0, 0.52)]
    assert prevailing(ts, 50.0) is None
    assert prevailing(ts, 200.0) == 0.52
    assert prevailing(ts, 150.0) == 0.5


def test_join_vs_improve_rates():
    touch = [(t, 0.50) for t in (100.0, 200.0, 300.0, 400.0)]
    trades = [(150.0, 0.50, 5), (250.0, 0.49, 5), (350.0, 0.51, 5),
              (50.0, 0.50, 5)]
    r = calibrate(trades, touch)
    assert r['n'] == 3  # pre-window print refused
    assert r['join_rate'] == round(2 / 3, 3)
    # one venue tick (0.005): 0.51 > 0.505 no longer counts as improved
    assert r['improve_rate'] == round(2 / 3, 3)
    assert r['extra_per_tick'] == 0.0


def test_refusals():
    assert calibrate([], [(1.0, 0.5)]) is None
    assert calibrate([(1.0, 'junk', 5)], [(0.0, 0.5)]) is None


def test_side_symmetry():
    from research.touchcal import calibrate
    touch = [(t, 0.50) for t in (100.0, 200.0, 300.0, 400.0)]
    # mirrored prints: buy-side and sell-side must mirror exactly
    buys = [(150.0, 0.50, 5), (250.0, 0.49, 5), (350.0, 0.51, 5)]
    sells = [(150.0, 0.50, 5), (250.0, 0.51, 5), (350.0, 0.49, 5)]
    rb = calibrate(buys, touch)
    rs = calibrate(sells, touch, side='sell')
    assert (rb['join_rate'], rb['improve_rate']) == (rs['join_rate'], rs['improve_rate'])


def test_volume_and_staleness():
    from research.touchcal import calibrate
    touch = [(100.0, 0.50)]
    assert calibrate([(150.0, 0.49, 0)], touch) is None
    assert calibrate([(150.0, 0.49, -3)], touch) is None
    r = calibrate([(150.0, 0.49, 5)], touch, max_touch_age_s=10)
    assert r is None  # 50s-old touch refused, counted stale internally
    r2 = calibrate([(150.0, 0.49, 5)], touch, max_touch_age_s=100)
    assert r2['n'] == 1 and r2['join_rate'] == 1.0
