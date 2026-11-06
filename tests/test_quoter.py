import unittest
from research.quoter import tick, quote_pair


class QuoterTests(unittest.TestCase):
    def test_tick_grid(self):
        self.assertEqual(tick(0.062), 0.06)
        self.assertEqual(tick(0.062, up=True), 0.065)

    def test_improves_touch(self):
        qb, qa = quote_pair(0.05, 0.10, 0, 5)
        self.assertEqual((qb, qa), (0.055, 0.095))

    def test_skew_leans(self):
        base = quote_pair(0.05, 0.10, 0, 5)
        long = quote_pair(0.05, 0.10, 1000, 5)
        self.assertLess(long[0], base[0])
        self.assertLess(long[1], base[1])

    def test_rejects_narrow(self):
        self.assertIsNone(quote_pair(0.05, 0.055, 0, 5))


if __name__ == '__main__':
    unittest.main()
