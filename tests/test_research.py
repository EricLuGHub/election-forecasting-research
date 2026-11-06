import unittest
from research.pricing import sweep, margin_probability, fractional_kelly, quote, scores, simulate_seats
from research.analyze import basket, race_groups
from research.evaluate import evaluate
from research.external import event_for_title


class PricingTests(unittest.TestCase):
    def test_no_uses_complement_of_bid_and_walks_depth(self):
        book = {'bids': [{'price': .8, 'quantity': 10}, {'price': .7, 'quantity': 10}], 'asks': []}
        fill = sweep(book, 'no', 15)
        self.assertAlmostEqual(fill['cost'], 3.5)
        self.assertTrue(fill['complete'])
        self.assertFalse(sweep(book, 'no', 30)['complete'])

    def test_exclusive_basket_non_exhaustive_and_depth(self):
        books = {'1': {'bids': [{'price': .7, 'quantity': 10}, {'price': .3, 'quantity': 20}], 'asks': []},
                 '2': {'bids': [{'price': .4, 'quantity': 30}], 'asks': []}}
        legs = [{'exchangeId': '1', 'side': 'no'}, {'exchangeId': '2', 'side': 'no'}]
        found = basket(books, legs, 1, 0)
        self.assertEqual(found['quantityEach'], 10)
        self.assertAlmostEqual(found['minimumNetPayoutMinusCost'], 1)
        self.assertIsNone(basket(books, legs, 1, .06))
        # At most one party wins: NO+NO pays 1 for either party or 2 for Other.
        self.assertEqual([sum(1-y for y in outcome) for outcome in [(1,0),(0,1),(0,0)]], [1,1,2])

    def test_increasing_uncertainty_reduces_conviction(self):
        self.assertEqual(margin_probability(0, 5), .5)
        self.assertGreater(margin_probability(3, 3), margin_probability(3, 7))

    def test_kelly_and_tick_quotes(self):
        self.assertEqual(fractional_kelly(.4,.5), 0)
        self.assertAlmostEqual(fractional_kelly(.6,.5), .01)
        self.assertLess(quote(.6, inventory=1000)['yesBid'], quote(.6)['yesBid'])
        self.assertIsNone(quote(.001)['yesBid'])
        for value in quote(.603).values():
            self.assertAlmostEqual(value/.005, round(value/.005))

    def test_score_perfect_and_bad_forecasts(self):
        self.assertEqual(scores([0,1], [0,1])['brier'], 0)
        self.assertEqual(scores([1,0], [0,1])['brier'], 1)
        with self.assertRaises(ValueError):
            scores([float('nan')], [0])

    def test_simulation_preserves_degenerate_probabilities(self):
        result = simulate_seats([1, 0], safe_seats=49, majority=51, draws=500)
        self.assertEqual(result['meanSeats'], 50)
        self.assertEqual(result['controlProbability'], 0)

    def test_race_stage_separates_contests(self):
        snapshot = {'markets': [], 'nodes': {}}
        for i,stage in [('1','general'),('2','special')]:
            snapshot['markets'].append({'id':i,'title':'same title','exchanges':[{'id':i}]})
            snapshot['nodes'][i] = {'root': {'node_type':'contract','contract_details':
                {'resolutionType':'Party Winner','raceId':'A','stageId':stage,'winnerName':i}}}
        self.assertEqual(len(race_groups(snapshot)), 2)

    def test_external_year_district_and_special_election(self):
        self.assertEqual(event_for_title('Will the Democratic Party win the CA-22 House race?'), ('HOUSECA22-26','D'))
        self.assertEqual(event_for_title('Will the Republican Party win the Florida Senate?'), ('SENATEFLS-26','R'))

    def test_evaluation_rejects_future_leak_and_duplicate(self):
        row={'forecast_date':'2024-10-01','event_date':'2024-11-05','event_id':'A','model':'x','p':'.6','outcome':'1'}
        self.assertAlmostEqual(evaluate([row])['x']['brier'], .16)
        with self.assertRaises(ValueError):evaluate([row,row])
        with self.assertRaises(ValueError):evaluate([dict(row, forecast_date='2024-11-06')])


if __name__ == '__main__':
    unittest.main()
