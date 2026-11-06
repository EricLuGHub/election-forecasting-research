from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.e2watch import run_once
from research.maker_study import read_resource, select, tape_stats


def snapshot():
    markets = [{'id': str(i), 'title': f'Will the {party} Party win the Alaska Senate?',
                'status': 'open', 'exchanges': [{'id': str(i)}]}
               for i, party in ((1, 'Democratic'), (2, 'Republican'))]
    return {'markets': markets,
            'quotes': [{'exchangeId': '1', 'bestBid': .6, 'bestAsk': .68},
                       {'exchangeId': '2', 'bestBid': .32, 'bestAsk': .4}],
            'references': {f'SENATEAK-26-{party}': {'bid': bid, 'ask': bid+.01,
                           'status': 'active', 'bidSize': 25, 'askSize': 25, 'volume24h': 101}
                           for party, bid in (('D', .67), ('R', .32))}}


class MakerStudyTests(unittest.TestCase):
    def test_unique_race_and_priority(self):
        result = select(snapshot(), [], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['exchangeId'], '1')

    def test_other_party_position_blocks_entire_race(self):
        self.assertEqual(select(snapshot(), [{'exchangeId': '2', 'quantity': -10}], []), [])

    def test_other_party_open_order_blocks_entire_race(self):
        self.assertEqual(select(snapshot(), [], [{'exchangeId': '2', 'open': True}]), [])

    def test_trial_selection_allows_held_counterpart_not_held_instrument(self):
        result = select(snapshot(), [{'exchangeId': '2', 'quantity': -10}], [], allow_held_counterparts=True)
        self.assertEqual([r['exchangeId'] for r in result], ['1'])

    def test_no_fills_inferred_from_tape(self):
        r = tape_stats([{'data': [{'id': '1', 'size': 100, 'price': .6}],
                         'pagination': {'hasMore': True}}])
        self.assertEqual(r['shares'], 100)
        self.assertFalse(r['completePagination'])
        self.assertIsNone(r['fillRateEstimate'])

    @patch('research.maker_study.time.sleep')
    def test_bounded_timeout_retries(self, sleep):
        class Client:
            calls = 0
            def get(self, path, **kw):
                self.calls += 1
                raise TimeoutError('Timed out')
        c = Client()
        self.assertIn('error', read_resource(c, '/read-only'))
        self.assertEqual(c.calls, 2)

    def test_e2_live_independently_held(self):
        with tempfile.TemporaryDirectory() as d, patch('research.e2watch.ROOT', Path(d)), \
                patch('research.e2watch.beat') as beat, patch('research.e2watch.Executor') as executor:
            run_once({}, SimpleNamespace(live=True))
        self.assertEqual(beat.call_args.args[0]['phase'], 'partial_fill_lifecycle_missing')
        executor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
