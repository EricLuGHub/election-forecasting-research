"""Item-26 clock tests (synthetic journal + fills)."""
from research.sigclock import leg_clock, summarize


def _entry():
    return {
        'body': {'legs': [
            {'exchangeId': '901', 'side': 'no', 'action': 'buy',
             'quantity': 1000, 'price': 0.90},
            {'exchangeId': '902', 'side': 'no', 'action': 'buy',
             'quantity': 1000, 'price': 0.10}]},
        'at': '2026-10-05T12:00:00+00:00',
        'status': 'confirmed',
        'response': {'results': [
            {'data': {'orderId': 1, 'quantityTraded': 1000,
                      'remainingQuantity': 0}},
            {'data': {'orderId': 2, 'quantityTraded': 1000,
                      'remainingQuantity': 0}}]},
    }


def _fills():
    return [
        {'orderId': 1, 'price': 0.90,
         'filledAt': '2026-10-05T12:00:20+00:00'},
        {'orderId': 2, 'price': 0.105,
         'filledAt': '2026-10-05T12:01:00+00:00'},
    ]


def test_latency_and_slip():
    legs = leg_clock(_entry(), _fills())
    assert legs[0]['latency_s'] == 20.0
    assert legs[0]['slip'] == 0.0
    assert legs[1]['latency_s'] == 60.0
    assert legs[1]['slip'] == 0.005  # paid worse than limit: information


def test_summary():
    s = summarize([[{'latency_s': 20.0, 'slip': 0.0},
                    {'latency_s': 60.0, 'slip': 0.005}]])
    assert s['legs_measured'] == 2
    assert s['latency_max'] == 60.0
    assert s['worst_slip'] == 0.0 or s['worst_slip'] == 0.005


def test_missing_fill():
    legs = leg_clock(_entry(), [])
    assert all(c['latency_s'] is None and c['slip'] is None for c in legs)
    assert summarize([legs])['legs_measured'] == 0
