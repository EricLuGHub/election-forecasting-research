import unittest
from research.realized import attribute


def buy(eid, oid, qty, px, side='yes'):
    return {'filledAt': 't', 'exchangeId': eid, 'side': side, 'quantity': qty,
            'price': px, 'orderId': oid}


def limit(oid, eid, side, action, qty, px):
    return {'id': oid, 'exchangeId': eid, 'side': side, 'action': action,
            'quantity': qty, 'price': px}


class RealizedTests(unittest.TestCase):
    def test_long_round_trip(self):
        fills = [buy('1', 1, 100, 0.10), buy('1', 2, -100, 0.15)]
        orders = [limit(1, '1', 'yes', 'buy', 100, 0.10),
                  limit(2, '1', 'yes', 'sell', 100, 0.15)]
        r = attribute(fills, orders)
        self.assertAlmostEqual(r['realized_total'], 5.0)

    def test_short_round_trip(self):
        fills = [buy('2', 3, -50, 0.90), buy('2', 4, 50, 0.95)]
        orders = [limit(3, '2', 'yes', 'sell', 50, 0.90),
                  limit(4, '2', 'yes', 'buy', 50, 0.95)]
        r = attribute(fills, orders)
        self.assertAlmostEqual(r['realized_total'], -2.5)

    def test_fifo_partial(self):
        fills = [buy('3', 5, 100, 0.10), buy('3', 6, 100, 0.20),
                 buy('3', 7, -100, 0.25)]
        orders = [limit(5, '3', 'yes', 'buy', 100, 0.10),
                  limit(6, '3', 'yes', 'buy', 100, 0.20),
                  limit(7, '3', 'yes', 'sell', 100, 0.25)]
        r = attribute(fills, orders)
        self.assertAlmostEqual(r['realized_total'], 15.0)
        self.assertEqual(r['open_lots'], 1)

    def test_canonicalized_round_trip(self):
        # Sell YES canonicalized as side=no in fills; the originating order
        # carries direction, fill price converts to YES terms.
        fills = [buy('9', 1, 5, 0.12),
                 {'filledAt': 't', 'exchangeId': '9', 'side': 'no',
                  'quantity': -5, 'price': 0.87, 'orderId': 2}]
        orders = [limit(1, '9', 'yes', 'buy', 5, 0.12),
                  limit(2, '9', 'yes', 'sell', 5, 0.13)]
        r = attribute(fills, orders)
        self.assertAlmostEqual(r['realized_total'], 0.05)
        self.assertEqual(r['open_lots'], 0)

    def test_unmatched_fills_counted_not_forced(self):
        fills = [buy('9', 99, 5, 0.12)]
        r = attribute(fills, [])
        self.assertEqual(r['realized_total'], 0)
        self.assertEqual(r['unattributed_fills'], 1)


if __name__ == '__main__':
    unittest.main()
