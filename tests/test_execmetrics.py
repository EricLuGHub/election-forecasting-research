"""Item-5 timestamped execution-metric tests (fake lines only, no network)."""
from datetime import datetime, timezone

from research.execmetrics import (
    parse_log_lines, parse_journal, windowed_log, windowed_fills,
    log_freshness,
)

NOW = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)


def _ts(minutes_ago):
    from datetime import timedelta
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


SUBMIT_OK = ('%s SUBMIT 1061 buy yes 5@0.06 -> '
             '{"orderId": 1, "remainingQuantity": 5}') % _ts(30)
SUBMIT_NOID = ('%s SUBMIT 1061 buy yes 5@0.06 -> {"open": true}') % _ts(30)
SUBMIT_OLD = ('%s SUBMIT 1061 buy yes 5@0.06 -> {"orderId": 2}') % _ts(90)
SUBMIT_DAY = ('%s SUBMIT 1061 buy yes 5@0.06 -> {"orderId": 3}') % _ts(1500)
CANCEL_NEW = '%s CANCEL stale 1061@None' % _ts(10)
CANCEL_OLD = '%s CANCEL stale 1061@None' % _ts(2000)
CFAIL_NEW = '%s CANCEL-FAIL 1061@None' % _ts(5)
JUNK = 'not a timestamp at all'


def test_windows_separate_recent_from_old():
    events = parse_log_lines([SUBMIT_OK, SUBMIT_OLD, SUBMIT_DAY,
                              CANCEL_NEW, CANCEL_OLD, CFAIL_NEW, JUNK])
    assert len(events) == 6  # junk skipped
    w = windowed_log(events, NOW)
    assert w['1h'] == {'submits': 1, 'accepted': 1, 'cancels': 1,
                       'cancel_fails': 1}
    assert w['24h']['submits'] == 2 and w['24h']['accepted'] == 2
    assert w['24h']['cancels'] == 1  # 2000-min-old cancel excluded
    assert w['total'] == {'submits': 3, 'cancels': 2}


def test_exact_duplicates_collapsed():
    events = parse_log_lines([SUBMIT_OK, SUBMIT_OK, CANCEL_NEW, CANCEL_NEW])
    assert len(events) == 2


def test_submit_without_orderid_not_accepted():
    events = parse_log_lines([SUBMIT_NOID])
    assert events[0]['accepted'] is False
    assert windowed_log(events, NOW)['1h']['accepted'] == 0


def test_journal_prefix_filter_and_windows():
    obj = {
        'E1R-aaa': {'at': _ts(30),
                   'response': {'quantityTraded': 5, 'totalCost': 1.5}},
        'E1R-old': {'at': _ts(1500),
                   'response': {'quantityTraded': -3, 'totalCost': 0.9}},
        'E7T-other': {'at': _ts(10),
                      'response': {'quantityTraded': 99, 'totalCost': 99}},
        'E1R-nots': {'response': {}},
    }
    rows, dropped = parse_journal(obj, prefix='E1R-')
    assert dropped == 1 and len(rows) == 2  # E7T filtered, ts-less dropped
    w = windowed_fills(rows, NOW)
    assert w['1h'] == {'entries': 1, 'matched_shares': 5, 'turnover': 1.5}
    assert w['total']['matched_shares'] == 8  # abs() of -3
    assert w['total']['turnover'] == 2.4


def test_bell_prefixed_lines_still_count():
    line = '\x07\x07\x07' + SUBMIT_OK
    events = parse_log_lines([line])
    assert len(events) == 1 and events[0]['kind'] == 'submit'


def test_log_freshness_reports_age():
    events = parse_log_lines([SUBMIT_OLD])  # 90 min ago
    fresh = log_freshness(events, NOW)
    assert fresh == {'events': 1, 'last_at': SUBMIT_OLD.split()[0],
                     'age_h': 1.5}
    assert log_freshness([], NOW) == {'events': 0, 'last_at': None,
                                     'age_h': None}


def test_truncated_response_still_accepted():
    line = _ts(5) + (' SUBMIT 1061 buy yes 5@0.06 -> {"orderId": 9, '
                     '"exchangeId": "1061", "open": true, "remain')
    events = parse_log_lines([line])
    assert len(events) == 1 and events[0]['accepted'] is True
