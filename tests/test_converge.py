"""Item-40 survival/convergence tests (synthetic only, no network)."""
from datetime import datetime, timezone

from research.converge import parse_flags, survival_table, kaplan_meier

T0 = '2026-10-04T00:00:00+00:00'


def _line(basket, state, at):
    import json
    return json.dumps({'basket': basket, 'state': state, 'edge': 1.0,
                       'at': at})


def test_parse_flags_and_timeless():
    lines = [_line('a', 'hold', T0),
             _line('a', 'BANKABLE', '2026-10-04T12:00:00+00:00'),
             '{"basket": "b", "state": "hold", "edge": 1.0, "at": "2026-10-04T06:00:00+00:00"}'[:60],
             'garbage']
    traj, timeless = parse_flags(lines)
    assert [s for _, s in traj['a']] == ['hold', 'BANKABLE']
    assert timeless == 1  # truncated row without recoverable at


def test_survival_table_statuses():
    ledger = {
        'a': {'at': T0, 'floor': 1},  # flags
        'b': {'at': T0, 'floor': 1},  # never flags -> censored
        'c': {'at': T0, 'floor': 1},  # depleted by other means
        'shelf-1': {'at': T0},  # short -> skipped, not censored
    }
    lines = [_line('a', 'BANKABLE', '2026-10-04T10:00:00+00:00'),
             _line('b', 'hold', '2026-10-04T10:00:00+00:00'),
             _line('c', 'depleted', '2026-10-04T10:00:00+00:00')]
    traj, _ = parse_flags(lines)
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    rows = {r['basket']: r for r in
            survival_table(ledger, traj, now)}
    assert set(rows) == {'a', 'b', 'c'}
    assert rows['a']['status'] == 'flagged' and rows['a']['hours'] == 10.0
    assert rows['b']['status'] == 'censored'
    assert rows['c']['status'] == 'depleted'  # competing risk, not an event


def test_kaplan_meier_math():
    rows = [{'basket': 'a', 'hours': 10.0, 'status': 'flagged'},
            {'basket': 'b', 'hours': 20.0, 'status': 'flagged'},
            {'basket': 'c', 'hours': 15.0, 'status': 'censored'},
            {'basket': 'd', 'hours': 5.0, 'status': 'censored'}]
    curve = kaplan_meier(rows)
    # t=10: at_risk={a,b,c}=3, d=1 -> S=2/3; t=20: at_risk={b}=1 -> S=0
    assert curve[0] == (10.0, round(2 / 3, 3), 3)
    assert curve[1] == (20.0, 0.0, 1)


def test_naive_salvaged_ts_assumed_utc():
    from research.converge import parse_ts
    dt = parse_ts('2026-10-05T11:26')  # truncated before offset
    assert dt is not None and dt.tzinfo is not None
