import unittest
import json
from pathlib import Path
import tempfile
from research import execution as ex


class FakeClient:
    def __init__(self, status='draft'):
        self.status = status
        self.posts = []
        self.orders = []
        self.positions = []
        self.fail_post = False
        self.deleted = []

    def get(self, path, **params):
        if path.startswith('/tournaments/') and path.endswith(('positions', 'pnl')) or '/portfolio/' in path:
            return {'positions': self.positions} if path.endswith('positions') else {'periodPnl': 0}
        if path == '/orders':
            return {'data': []}
        return {'id': 'tid', 'slug': 'midterm-elections', 'status': self.status,
                'startDate': '2020-01-01T00:00:00Z', 'endDate': '2099-01-01T00:00:00Z',
                'myBalance': 100000}

    def pages(self, path, **params):
        assert path == '/orders' and params['tournamentId'] == 'tid'
        return self.orders

    def post(self, path, body):
        self.posts.append((path, body))
        if self.fail_post:
            raise RuntimeError('Timeout after POST: ambiguous response')
        return {'orderId': 123}

    def delete(self, path):
        self.deleted.append(path)
        return {'ok': True}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def executor(self, **kwargs):
        return ex.Executor(journal_path=self.directory/'journal.json',
                           recovery_path=self.directory/'mode.json', **kwargs)

    def test_tick_rounding(self):
        self.assertEqual(ex.round_tick(0.922), 0.92)
        self.assertEqual(ex.round_tick(0.923), 0.925)

    def test_off_tick_rejected(self):
        with self.assertRaises(ValueError):
            ex.validate_leg({'exchangeId': '1075', 'side': 'no', 'action': 'buy',
                             'quantity': 10, 'price': 0.922})

    def test_market_order_encoding_allowed(self):
        ex.validate_leg({'exchangeId': '1075', 'side': 'yes', 'action': 'buy',
                         'quantity': 10, 'price': 1})
        ex.validate_leg({'exchangeId': '1075', 'side': 'yes', 'action': 'sell',
                         'quantity': 10, 'price': 0})

    def test_duplicate_exchange_rejected(self):
        legs = [{'exchangeId': '1075', 'side': 'no', 'action': 'buy', 'quantity': 5},
                {'exchangeId': '1075', 'side': 'no', 'action': 'buy', 'quantity': 5}]
        with self.assertRaises(ValueError):
            ex.build_multileg(legs)

    def test_too_many_legs_rejected(self):
        legs = [{'exchangeId': str(i), 'side': 'no', 'action': 'buy', 'quantity': 1}
                for i in range(11)]
        with self.assertRaises(ValueError):
            ex.build_multileg(legs)

    def test_dry_run_posts_nothing(self):
        exe = self.executor(dry_run=True, client=FakeClient())
        order = ex.build_single('1075', 'no', 'buy', 10, price=0.92)
        result = exe.submit_single(order)
        self.assertTrue(result['dry_run'])
        self.assertEqual(exe.client.posts, [])

    def test_live_blocked_when_draft(self):
        exe = self.executor(dry_run=False, client=FakeClient(status='draft'))
        order = ex.build_single('1075', 'no', 'buy', 10, price=0.92)
        with self.assertRaises(RuntimeError):
            exe.submit_single(order, expected_capital=9.2)
        self.assertEqual(exe.client.posts, [])

    def test_basket_cap_enforced(self):
        exe = self.executor(dry_run=False, client=FakeClient(status='open'),
                          max_basket_capital=100.0)
        basket = ex.build_multileg(
            [{'exchangeId': '1075', 'side': 'no', 'action': 'buy', 'quantity': 1000},
             {'exchangeId': '1042', 'side': 'no', 'action': 'buy', 'quantity': 1000}], tournament_id='tid')
        with self.assertRaises(ValueError):
            exe.submit_basket(basket, expected_capital=970.0)

    def test_price_limit_and_inventory_count_toward_cap(self):
        client = FakeClient('active')
        client.positions = [{'exchangeId': '1', 'quantity': -10, 'costBasis': 8}]
        client.orders = [dict(id=9, exchangeId='2', side='no', action='buy', quantity=5,
                              priceLimit=.8, open=True)]
        exe = self.executor(client=client, dry_run=False, max_total_capital=13)
        self.assertEqual(exe.reconcile()['grossCapital'], 12)
        with self.assertRaisesRegex(ValueError, 'total cap'):
            exe.submit_single(ex.build_single('3', 'yes', 'buy', 5, .5, 'tid'))
        self.assertFalse(client.posts)

    def test_half_cent_reservation_not_rounded_away(self):
        client = FakeClient('active')
        client.orders = [dict(id=9, exchangeId='2', side='yes', action='buy', quantity=1,
                              priceLimit=.005, open=True)]
        exe = self.executor(client=client)
        self.assertEqual(exe.reconcile()['openOrderCapital'], .005)

    def test_explicit_tournament_required(self):
        exe = self.executor(client=FakeClient('active'), dry_run=False)
        with self.assertRaisesRegex(ValueError, 'tournamentId'):
            exe.submit_single(ex.build_single('3', 'yes', 'buy', 5, .5))

    def test_hold_blocks_new_exposure(self):
        (self.directory/'mode.json').write_text(json.dumps({'reduceOnly': True}))
        exe = self.executor(client=FakeClient('active'), dry_run=False)
        with self.assertRaisesRegex(RuntimeError, 'reduce-only'):
            exe.submit_single(ex.build_single('3', 'yes', 'buy', 5, .5, 'tid'))
        self.assertFalse(exe.client.posts)

    def test_reduce_no_holdings_above_gross_cap(self):
        client = FakeClient('active')
        client.positions = [{'exchangeId': '3', 'quantity': -10, 'costBasis': 8}]
        exe = self.executor(client=client, dry_run=False, max_total_capital=1)
        order = ex.build_single('3', 'no', 'sell', 5, .9, 'tid')
        self.assertEqual(exe.submit_single(order, reduce_only=True)['orderId'], 123)
        self.assertEqual(exe.submit_single(order, reduce_only=True)['orderId'], 123)
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(exe.owned_ids('exe-'), {123})

    def test_pending_reductions_prevent_oversell(self):
        client = FakeClient('active')
        client.positions = [{'exchangeId': '3', 'quantity': -10, 'costBasis': 8}]
        client.orders = [dict(id=9, exchangeId='3', side='yes', action='buy', quantity=8,
                              priceLimit=.1, open=True)]
        exe = self.executor(client=client, dry_run=False)
        with self.assertRaisesRegex(RuntimeError, 'reduce-only'):
            exe.submit_single(ex.build_single('3', 'no', 'sell', 5, .9, 'tid'), reduce_only=True)
        self.assertFalse(client.posts)

    def test_unknown_post_halts_next_and_restart(self):
        client = FakeClient('active')
        client.fail_post = True
        exe = self.executor(client=client, dry_run=False)
        order = ex.build_single('3', 'yes', 'buy', 5, .5, 'tid')
        with self.assertRaises(RuntimeError):
            exe.submit_single(order)
        restarted = self.executor(client=client, dry_run=False)
        with self.assertRaisesRegex(RuntimeError, 'Unresolved'):
            restarted.submit_single(order)
        with self.assertRaisesRegex(RuntimeError, 'Unresolved'):
            restarted.submit_single(ex.build_single('4', 'yes', 'buy', 5, .5, 'tid'))
        self.assertEqual(len(client.posts), 1)

    def test_key_cannot_be_reused_for_new_order(self):
        exe = self.executor(client=FakeClient('active'), dry_run=False)
        order = ex.build_single('3', 'yes', 'buy', 5, .5, 'tid')
        exe.submit_single(order)
        with self.assertRaisesRegex(ValueError, 'changed payload'):
            exe.submit_single(dict(order, quantity=10))

    def test_custom_guard_sees_fresh_account_before_write(self):
        exe = self.executor(client=FakeClient('active'), dry_run=False)
        def reject(account):
            self.assertIn('positions', account)
            raise ValueError('Race risk')
        with self.assertRaisesRegex(ValueError, 'Race risk'):
            exe.submit_single(ex.build_single('3', 'yes', 'buy', 5, .5, 'tid'), guard=reject)
        self.assertFalse(exe.client.posts)
        self.assertFalse(exe.journal())

    def test_out_of_scope_cancel_no_mutation(self):
        exe = self.executor(client=FakeClient('active'), dry_run=False)
        exe.cancel_order(999)
        self.assertFalse(exe.client.deleted)
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            exe.cancel_all('wrong')

    def test_nonfinite_price_rejected(self):
        for value in (float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                ex.build_single('3', 'yes', 'buy', 5, value, 'tid')


if __name__ == '__main__':
    unittest.main()
