"""Item-8 attribution tests (synthetic, no network)."""
from research.attrib import engine_of, attribute_engines


def test_engine_prefixes():
    assert engine_of({'idempotencyKey': 'Q4-abc'}) == 'quoter-mine'
    assert engine_of({'idempotencyKey': 'ROT3-x'}) == 'baskets-mine'
    assert engine_of({'idempotencyKey': 'SHELF-y'}) == 'baskets-mine'
    assert engine_of({'idempotencyKey': None}) == 'E1-other'
    assert engine_of({}) == 'E1-other'


def test_shared_credit():
    # quoter buys YES 10 @0.50 (Q4), E1 sells 10 @0.60 (no key):
    # +1.00 shared quoter-mine > E1-other, never single-engine.
    orders = [
        {'id': '1', 'idempotencyKey': 'Q4-a', 'side': 'yes', 'action': 'buy',
         'quantity': 10, 'price': 0.50},
        {'id': '2', 'idempotencyKey': None, 'side': 'yes', 'action': 'sell',
         'quantity': 10, 'price': 0.60},
    ]
    fills = [
        {'exchangeId': 'E', 'orderId': '1', 'side': 'yes', 'quantity': 10,
         'price': 0.50, 'filledAt': '2026-01-01T00:00:00+00:00'},
        {'exchangeId': 'E', 'orderId': '2', 'side': 'yes', 'quantity': -10,
         'price': 0.60, 'filledAt': '2026-01-01T01:00:00+00:00'},
    ]
    matrix, closes, unattributed = attribute_engines(fills, orders)
    assert closes == 1 and unattributed == 0
    assert matrix['quoter-mine>E1-other'] == [1.0, 10]


def test_unmatched_counted():
    matrix, closes, unattributed = attribute_engines(
        [{'exchangeId': 'E', 'orderId': 'zzz', 'side': 'yes', 'quantity': 5,
          'price': 0.5, 'filledAt': '2026-01-01T00:00:00+00:00'}], [])
    assert unattributed == 1 and closes == 0 and matrix == {}


def test_journal_component_mapping():
    from research.attrib import journal_order_engines, attribute_engines
    journal = {'ROT-x': {'response': {'results': [
        {'data': {'orderId': 11}}, {'data': {'orderId': 12}}]}}}
    assert journal_order_engines(journal) == {'11': 'baskets-mine',
                                              '12': 'baskets-mine'}
    assert journal_order_engines({}) == {}
    orders = [
        {'id': '11', 'idempotencyKey': None, 'side': 'no', 'action': 'buy',
         'quantity': 10, 'price': 0.90},
        {'id': '21', 'idempotencyKey': None, 'side': 'no', 'action': 'sell',
         'quantity': 10, 'price': 0.95},
    ]
    fills = [
        {'exchangeId': 'E', 'orderId': '11', 'side': 'no', 'quantity': 10,
         'price': 0.90, 'filledAt': '2026-01-01T00:00:00+00:00'},
        {'exchangeId': 'E', 'orderId': '21', 'side': 'no', 'quantity': -10,
         'price': 0.95, 'filledAt': '2026-01-01T01:00:00+00:00'},
    ]
    matrix, closes, unattributed = attribute_engines(
        fills, orders, journal)
    # NO buy @.90 (long-NO, econ short-YES @.10), NO sell @.95 (+.05/share):
    # entry baskets-mine, exit E1-other -> shared credit +0.50
    assert closes == 1 and unattributed == 0
    assert matrix['baskets-mine>E1-other'] == [0.5, 10]
