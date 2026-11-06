import unittest


class MarksTests(unittest.TestCase):
    """Engine accounting conventions (observed 2026-10-02, verify at settlement).

    LONG YES: uPnl == (mark - avgCost) * qty (exact).
    SHORT YES (-n @ P, mark M): uPnl == ((1 - M) - P) * n, i.e. rebooked as
    long-NO at the fill price. Directionally right (profits when YES falls)
    but NOT equal to (P - M) * n. Never size shorts off naive mark math.
    """

    def test_long_convention(self):
        self.assertAlmostEqual((0.166 - 0.123) * 100, 4.3, places=1)

    def test_short_convention(self):
        # 848: short 600 @ 0.12, mark 0.841, reported +23.47
        self.assertAlmostEqual(((1 - 0.841) - 0.12) * 600, 23.4, places=1)
        # naive (wrong): (0.12 - 0.841) * 600 = -432.6

    def test_short_convention_2(self):
        # 858: short 5 @ 0.86, mark 0.19, reported -0.25
        self.assertAlmostEqual(((1 - 0.19) - 0.86) * 5, -0.25, places=2)


if __name__ == '__main__':
    unittest.main()
