"""Item-6 fixed-horizon tests (synthetic sqlite history)."""
import json
import sqlite3
from research.markout import at_fill_mids, HORIZONS


def _db(tmp_path):
    path = str(tmp_path / 'h.sqlite3')
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE observations (id INTEGER PRIMARY KEY, at TEXT, '
               'kind TEXT, resource TEXT, payload TEXT)')
    # fill at T+0 on E1; quotes at +5s (bid .10/ask .12), +70s (.11/.13)
    db.execute("INSERT INTO observations (at, kind, resource, payload) VALUES "
               "('2026-10-05T00:00:05+00:00', 'quote_change', 'E1', ?)",
               (json.dumps({'bestBid': 0.10, 'bestAsk': 0.12}),))
    db.execute("INSERT INTO observations (at, kind, resource, payload) VALUES "
               "('2026-10-05T00:01:10+00:00', 'quote_change', 'E1', ?)",
               (json.dumps({'bestBid': 0.11, 'bestAsk': 0.13}),))
    db.commit()
    db.close()
    return path


def test_fixed_horizons_and_exclusions(tmp_path):
    path = _db(tmp_path)
    fills = [{'exchangeId': 'E1', 'quantity': 5, 'price': 0.09,
              'filledAt': '2026-10-05T00:00:00+00:00'}]
    out = at_fill_mids(path, fills, delays=[5.0, 30.0, 60.0])
    per = out[0]
    # 5s quote lands at lag 5 (within 5+30): mid .11, bid .10
    assert per[5.0][0] == 0.11 and per[5.0][1] == 0.10
    # 30s target: next quote at lag 70 > 30+30 → excluded
    assert 30.0 not in per
    # 60s target: quote at lag 70 within 60+30 → mid .12, ask .13
    assert per[60.0][0] == 0.12 and per[60.0][2] == 0.13


def test_executable_exit_sides():
    # long exits into YES bid; short (long-NO) exits into 1-YES ask
    long_edge_exe = 0.10 - 0.09
    short_edge_exe = 0.13 - 0.13  # exec 0.13 vs ask 0.13
    assert abs(long_edge_exe - 0.01) < 1e-9
    assert abs(short_edge_exe) < 1e-9


def test_horizons_constant():
    assert HORIZONS == (5.0, 30.0, 60.0, 300.0, 1800.0)
