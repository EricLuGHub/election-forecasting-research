import unittest
from research.edge_study import matched_quotes, study


def row(at, bid=.40, ask=.42, eid='1'):
    return {'at': '2026-10-02T'+at+'+00:00', 'exchangeId': eid,
            'title': 'Will the Democratic Party win the Texas Senate?', 'sig_bid': bid, 'sig_ask': ask}


def reference(at, bid='.60', ask='.62'):
    return {'at': '2026-10-02T'+at+'+00:00', 'completedAt': '2026-10-02T'+at+'+00:00',
            'refs': {'SENATETX-26-D': {'yes_bid_dollars': bid, 'yes_ask_dollars': ask,
             'yes_bid_size_fp': '100', 'yes_ask_size_fp': '100', 'volume_24h_fp': '1000', 'status': 'active'}}}


class EdgeStudyTests(unittest.TestCase):
    def test_no_future_reference_join(self):
        matched, errors = matched_quotes([row('01:00:00')], [reference('01:00:01')])
        self.assertFalse(matched)
        self.assertEqual(errors, {'no_prior_reference': 1})

    def test_stale_reference_excluded(self):
        self.assertFalse(matched_quotes([row('01:10:00')], [reference('01:00:00')])[0])

    def test_taker_entry_and_exit_not_midpoints(self):
        result = study([row('01:00:00'), row('02:00:00', .50, .54)], [reference('00:59:00')])
        trade = result['trades'][0]
        self.assertEqual(trade['entryAsk'], .42)
        self.assertEqual(trade['exitBid'], .50)
        self.assertAlmostEqual(trade['netPerShare'], .07)
        self.assertEqual(trade['partition'], 'boundary')

    def test_no_position_is_exited_at_best_future_price(self):
        rows = [row('01:00:00'), row('02:00:00', .44, .46), row('02:10:00', .70, .72)]
        result = study(rows, [reference('00:59:00')])
        self.assertEqual(result['trades'][0]['exitBid'], .44)

    def test_no_same_race_overlapping_signals(self):
        rows = [row('01:00:00'), row('01:01:00'), row('02:00:00', .5, .54)]
        self.assertEqual(len(study(rows, [reference('00:59:00')])['trades']), 1)

    def test_no_side_uses_complements(self):
        rows = [row('01:00:00', .8, .82), row('02:00:00', .5, .52)]
        trade = study(rows, [reference('00:59:00')])['trades'][0]
        self.assertEqual(trade['side'], 'no')
        self.assertAlmostEqual(trade['entryAsk'], .2)
        self.assertAlmostEqual(trade['exitBid'], .48)

    def test_missing_exit_not_optimistically_marked(self):
        self.assertFalse(study([row('01:00:00')], [reference('00:59:00')])['trades'])


if __name__ == '__main__':
    unittest.main()
