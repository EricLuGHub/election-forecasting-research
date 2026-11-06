from datetime import timedelta
import unittest

from research.e7eval import evaluate
from test_engine7 import NOW, START, FILL, SCOPES, BOOK, fill, journal
from research.pilot import instant


class EvaluationTests(unittest.TestCase):
    def test_empty_orders_are_not_performance(self):
        r = evaluate({'startedAt': START, 'exchanges': SCOPES}, [], journal(), [], NOW)
        self.assertEqual(r['actualFillRecords'], 0)
        self.assertEqual(r['completedRoundTrips'], 0)
        self.assertFalse(r['strategyValidated'])

    def test_unmatched_inventory_and_stress_are_counted(self):
        obs = {'at': NOW.isoformat(), 'observations': {'3': {'book': BOOK, 'bookAt': NOW.isoformat()}},
               'accounting': {'cashFlow': -77, 'quantities': {'3': 100}, 'realizedGross': 0,
                              'boughtShares': 100, 'soldShares': 0}}
        r = evaluate({'startedAt': START, 'exchanges': SCOPES}, [fill()], journal(), [obs], NOW)
        self.assertAlmostEqual(r['liquidationGross'], -.5)
        self.assertAlmostEqual(r['stressedLiquidationGross'], -1.5)
        self.assertEqual(r['forwardEntryMarkouts']['300']['observedEntryFills'], 1)

    def test_first_after_horizon_not_best_future(self):
        t = instant(FILL)+timedelta(seconds=300)
        account = {'cashFlow': 0, 'quantities': {}, 'realizedGross': 0, 'boughtShares': 0, 'soldShares': 0}
        obs = [{'at': t.isoformat(), 'accounting': account,
                'observations': {'3': {'book': BOOK, 'bookAt': t.isoformat()}}},
               {'at': (t+timedelta(seconds=10)).isoformat(), 'accounting': account,
                'observations': {'3': {'book': dict(BOOK, asks=[{'price': .2, 'quantity': 100}]),
                                       'bookAt': (t+timedelta(seconds=10)).isoformat()}}}]
        r = evaluate({'startedAt': START, 'exchanges': SCOPES}, [fill()], journal(), obs, t+timedelta(seconds=20))
        self.assertAlmostEqual(r['forwardEntryMarkouts']['300']['quantityWeightedMarkout'], -.005)

    def test_round_trip_requires_actual_flat_inventory(self):
        fs = [fill(), fill(2, 2, -30, .785), fill(3, 2, -70, .785)]
        r = evaluate({'startedAt': START, 'exchanges': SCOPES}, fs, journal(), [], NOW)
        self.assertEqual(r['completedRoundTrips'], 1)


if __name__ == '__main__':
    unittest.main()
