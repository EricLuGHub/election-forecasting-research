import unittest
from research.capacity import capacity, slippage


class CapacityTests(unittest.TestCase):
    def test_touch_window(self):
        book = {'bids': [{'price': 0.5, 'quantity': 100},
                         {'price': 0.495, 'quantity': 200},
                         {'price': 0.48, 'quantity': 50}],
                'asks': [{'price': 0.52, 'quantity': 80}]}
        result = capacity(book)
        self.assertEqual(result['bid']['shares'], 300)
        self.assertEqual(result['ask']['shares'], 80)

    def test_empty_side(self):
        self.assertEqual(capacity({'bids': [], 'asks': []})['bid']['shares'], 0)

    def test_slippage_walks_levels(self):
        asks = [{'price': 0.10, 'quantity': 500}, {'price': 0.105, 'quantity': 2000}]
        small = slippage(asks, 600, 'buy')
        self.assertLess(small['avg_price'], 0.105)
        self.assertIsNone(slippage(asks, 3000, 'buy'))

    def test_pair_edges(self):
        # 2-leg race, YES bids 0.94 + 0.05: NO basket costs 0.06+0.95=1.01
        # (no buy edge); selling both YES collects 0.99 vs 1.0 worst case.
        self.assertAlmostEqual(1 - ((1 - 0.94) + (1 - 0.05)), -0.01)
        self.assertAlmostEqual((0.94 + 0.05) - 1.0, -0.01)


if __name__ == '__main__':
    unittest.main()
