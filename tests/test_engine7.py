from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from research.engines.engine7_maker import entry, exit_order, fill_accounting, liquidation_value
from research.e7run import Runner, recent_fills
from research.execution import Executor
from research.pilot import PREFIX
from test_execution import FakeClient


NOW = datetime.now(timezone.utc)
START = (NOW-timedelta(hours=1)).isoformat()
FILL = (NOW-timedelta(minutes=5)).isoformat()
BOOK = {'exchangeId': '3', 'marketId': '315', 'bids': [{'price': .21, 'quantity': 1000}],
        'asks': [{'price': .235, 'quantity': 1000}], 'bestBid': .21, 'bestAsk': .235}
REF = {'ticker': 'GOVPARTYWI-26-R', 'status': 'active', 'yes_bid_dollars': '.18', 'yes_ask_dollars': '.185',
       'yes_bid_size_fp': '100', 'yes_ask_size_fp': '100', 'volume_24h_fp': '1000'}
SCOPES = {'3': {'side': 'no', 'maxShares': 100, 'marketId': '315', 'ticker': REF['ticker']}}


def journal():
    return {PREFIX+'buy': {'status': 'confirmed', 'body': {'exchangeId': '3', 'side': 'no',
                           'action': 'buy', 'quantity': 100, 'price': .77}, 'response': {'orderId': 1}},
            PREFIX+'sell': {'status': 'confirmed', 'body': {'exchangeId': '3', 'side': 'no',
                            'action': 'sell', 'quantity': 100, 'price': .785}, 'response': {'orderId': 2}}}


def fill(fid=1, oid=1, qty=-100, price=.77):
    return {'id': fid, 'orderId': oid, 'exchangeId': '3', 'quantity': qty, 'price': price,
            'side': 'no', 'filledAt': FILL}


class MakerTests(unittest.TestCase):
    def test_passive_no_uses_complements(self):
        q = entry(BOOK, 'no', REF, 100)
        self.assertEqual(q['price'], .77)
        self.assertEqual(q['evidence']['referenceGap'], .045)
        self.assertFalse(q['evidence']['makerFillAssumed'])

    def test_cannot_cross_or_ignore_reference(self):
        book = deepcopy(BOOK)
        book['asks'][0]['price'] = .215
        self.assertIsNone(entry(book, 'no', REF, 100))
        self.assertIsNone(entry(BOOK, 'no', dict(REF, yes_bid_dollars='.21', yes_ask_dollars='.22'), 100))

    def test_join_best_when_improvement_consumes_buffer(self):
        q = entry(BOOK, 'no', dict(REF, yes_bid_dollars='.19', yes_ask_dollars='.20'), 100)
        self.assertEqual(q['price'], .765)
        self.assertAlmostEqual(q['evidence']['referenceGap'], .035)

    def test_crossed_and_invalid_reference_rejected(self):
        book = deepcopy(BOOK)
        book['bids'][0]['price'] = .24
        with self.assertRaises(ValueError):
            entry(book, 'no', REF, 100)
        with self.assertRaises(ValueError):
            entry(BOOK, 'no', dict(REF, volume_24h_fp='0'), 100)

    def test_profitable_taker_exit_and_passive_exit(self):
        self.assertEqual(exit_order(BOOK, 'no', 100, .75)['price'], .765)
        q = exit_order(BOOK, 'no', 100, .77)
        self.assertEqual(q['price'], .785)

    def test_urgent_exit_bounded_by_depth(self):
        book = deepcopy(BOOK)
        book['asks'][0]['quantity'] = 17
        q = exit_order(book, 'no', 100, .77, urgent=True)
        self.assertEqual(q['quantity'], 17)
        self.assertEqual(q['price'], .765)

    def test_real_fill_accounting_partial_fifo(self):
        fills = [fill(qty=-60), fill(2, qty=-40, price=.765), fill(3, 2, -70, .785)]
        a = fill_accounting(fills, journal(), SCOPES, START)
        self.assertEqual(a['signedInventory'], {'3': -30})
        self.assertAlmostEqual(a['realizedGross'], 1.1)
        self.assertEqual(a['lots']['3'][0]['quantity'], 30)

    def test_no_touch_or_order_acceptance_credit(self):
        self.assertEqual(fill_accounting([], journal(), SCOPES, START)['boughtShares'], 0)

    def test_foreign_duplicate_oversell_wrong_side_and_price(self):
        cases = [[fill(oid=99)], [fill(), fill()], [fill(oid=2)], [dict(fill(), side='yes')],
                 [fill(price=.78)], [fill(qty=100)], [fill(qty=-101)]]
        for fills in cases:
            with self.subTest(fills=fills), self.assertRaises(ValueError):
                fill_accounting(fills, journal(), SCOPES, START)

    def test_liquidation_no_midpoint_or_infinite_depth(self):
        value, residual = liquidation_value(BOOK, 'no', 1100)
        self.assertAlmostEqual(value, 765)
        self.assertEqual(residual, 100)


class PilotClient(FakeClient):
    def __init__(self):
        super().__init__('active')
        self.fills = []

    def get(self, path, **params):
        if path.endswith('/portfolio/fills'):
            return {'data': self.fills, 'pagination': {'hasMore': False}, 'coverage': {'complete': True}}
        if path.endswith('/orderbook'):
            return deepcopy(BOOK)
        return super().get(path, **params)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.config = {'prefix': PREFIX, 'slug': 'midterm-elections', 'startedAt': START,
                       'expiresAt': (NOW+timedelta(hours=1)).isoformat(), 'reservedExchangeIds': ['3', '4'],
                       'exchanges': SCOPES, 'lossStop': 10, 'maxHoldSeconds': 1800}
        (self.path/'config.json').write_text(json.dumps(self.config))
        permit = dict(self.config, version=1, entryEnabled=True, maxCapital=100)
        (self.path/'mode.json').write_text(json.dumps({'reduceOnly': True, 'openingPermit': permit}))
        self.client = PilotClient()
        self.exe = Executor(client=self.client, dry_run=False, journal_path=self.path/'journal.json',
                            recovery_path=self.path/'mode.json')
        self.runner = Runner(self.exe, self.path, reference_get=lambda _: {'market': REF})

    def test_entry_guard_and_order_are_journaled(self):
        result = self.runner.cycle()
        self.assertEqual(len(self.client.posts), 1)
        self.assertEqual(self.client.posts[0][1]['price'], .77)
        self.assertEqual(result['accounting']['fillCount'], 0)
        self.assertEqual(next(iter(self.exe.journal().values()))['riskProof']['capitalAfter'], 77)

    def test_stop_file_during_preflight_blocks_entry(self):
        original = self.exe.preflight
        calls = []
        def preflight():
            calls.append(1)
            if len(calls) == 2:
                (self.path/'stop.request').touch()
            return original()
        self.exe.preflight = preflight
        with self.assertRaisesRegex(ValueError, 'halted'):
            self.runner.cycle()
        self.assertFalse(self.client.posts)

    def held(self):
        (self.path/'journal.json').write_text(json.dumps(journal()))
        self.client.fills = [fill()]
        self.client.positions = [{'exchangeId': '3', 'quantity': -100, 'costBasis': 77,
                                 'lots': [{'entryPrice': .77}]}]

    def test_attributed_inventory_gets_exit_not_more_entry(self):
        self.held()
        result = self.runner.cycle()
        self.assertEqual(self.client.posts[0][1]['action'], 'sell')
        self.assertEqual(self.client.posts[0][1]['price'], .785)
        self.assertAlmostEqual(result['liquidationGross'], -.5)

    def test_reference_failure_does_not_block_exit(self):
        self.held()
        def failed(_):
            raise TimeoutError('Reference unavailable')
        self.runner.reference_get = failed
        self.runner.cycle()
        self.assertEqual(self.client.posts[0][1]['action'], 'sell')

    def test_inventory_mismatch_does_not_add(self):
        self.held()
        self.client.positions[0]['quantity'] = -90
        self.assertEqual(self.runner.cycle()['phase'], 'reconciliation_wait')
        self.assertFalse(self.client.posts)

    def test_loss_halt_persists_and_urgent_exit_reduces_risk(self):
        self.held()
        original = self.client.get
        def get(path, **kw):
            if path.endswith('/orderbook'):
                return dict(BOOK, bids=[{'price': .31, 'quantity': 1000}], asks=[{'price': .335, 'quantity': 1000}])
            return original(path, **kw)
        self.client.get = get
        r = self.runner.cycle()
        self.assertEqual(r['phase'], 'entries_halted')
        self.assertTrue((self.path/'halt.json').exists())
        self.assertEqual(self.client.posts[0][1]['action'], 'sell')
        self.assertAlmostEqual(self.client.posts[0][1]['price'], .665)

    def test_partial_entry_cancels_remainder_before_exit(self):
        self.held()
        self.client.fills[0]['quantity'] = -30
        self.client.positions[0].update(quantity=-30, costBasis=23.1)
        self.client.orders = [{'id': 1, 'exchangeId': '3', 'side': 'no', 'action': 'buy',
                               'quantity': 70, 'priceLimit': .77, 'open': True}]
        self.runner.cycle()
        self.assertEqual(self.client.deleted, ['/orders/1'])
        self.assertFalse(self.client.posts)

    def test_paper_never_submits(self):
        self.exe.dry_run = True
        self.runner.cycle()
        self.assertFalse(self.client.posts)

    def test_expired_permit_cannot_reopen_on_restart(self):
        data = json.loads((self.path/'mode.json').read_text())
        data['openingPermit']['expiresAt'] = START
        (self.path/'mode.json').write_text(json.dumps(data))
        self.assertEqual(self.runner.cycle()['phase'], 'entries_halted')
        self.assertFalse(self.client.posts)

    def test_no_owned_orders_requires_no_api_cleanup(self):
        def fail(*args, **kwargs):
            raise AssertionError('No API call needed with zero owned orders')
        self.exe.open_orders = fail
        self.runner.cancel_owned()

    def test_cancel_discovery_independent_of_position_endpoint(self):
        self.held()
        self.client.orders = [{'id': 1, 'exchangeId': '3', 'side': 'no', 'action': 'buy',
                               'quantity': 100, 'priceLimit': .77, 'open': True}]
        original = self.client.get
        def get(path, **kwargs):
            if path.endswith('/positions'):
                raise TimeoutError('Broken account reporting')
            return original(path, **kwargs)
        self.client.get = get
        self.runner.cancel_owned()
        self.assertEqual(self.client.deleted, ['/orders/1'])


if __name__ == '__main__':
    unittest.main()
