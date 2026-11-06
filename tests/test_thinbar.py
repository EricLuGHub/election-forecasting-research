"""Thin-tier tests (synthetic only, no network)."""
from research.thinbar import qualifies, THIN_ABS, THIN_RATE, THIN_CAP


def test_thin_clears_where_standard_fails():
    rows = [(250, 3.75), (500, 7.5), (1000, 13.0)]
    assert qualifies(rows) == (1000, 13.0)  # 0.65c rate clears 0.5c bar
    assert THIN_ABS == 5.0 and THIN_RATE == 0.005 and THIN_CAP == 2000.0


def test_rate_bar_binds():
    rows = [(250, 1.0), (500, 2.0)]  # 0.2c rate
    assert qualifies(rows) is None


def test_dust_stays_dead():
    assert qualifies([(250, 1.25)]) is None  # $1.25 < $5 absolute
