import copy
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from research import e1run
from research import risk
from research import e2watch
from research.execution import Executor
from research.exit import closing_order
from research.recovery import exposure_changes, legacy_ids
from test_execution import FakeClient


def pos(eid='1', qty=100, cost=.4):
    return dict(exchangeId=eid, marketId=eid, quantity=qty, costBasis=abs(qty)*cost,
                marketValue=abs(qty)*cost,
                option='YES', unrealizedPnl=1,
                lots=[dict(entryPrice=cost, quantity=abs(qty))])


def node(party='D', race='race'):
    return {'root': {'contract_details': dict(resolutionType='Party Winner', raceId=race,
                    stageId='stage', electionDate='2026-11-03', raceStage='General', winnerName=party)}}


def book(bid=.5, ask=.6, size=100):
    return dict(bids=[dict(price=bid, quantity=size)], asks=[dict(price=ask, quantity=size)])


def order(eid='1', side='yes', action='sell', qty=25, price=.5):
    return dict(exchangeId=eid, side=side, action=action, quantity=qty, price=price)


class RecoveryTests(unittest.TestCase):
    def test_quantity_is_already_signed_not_option_multiplied(self):
        self.assertEqual(risk.inventory([dict(pos(qty=-20), option='NO')]), {'1': -20})

    def test_canonicalized_sell_matches_complement_buy(self):
        a = order(side='yes', price=.045)
        b = dict(order(side='no', action='buy'), priceLimit=.955)
        self.assertEqual(e1run.order_key(a), e1run.order_key(b))
        self.assertNotEqual(e1run.order_key(a), e1run.order_key(order(action='buy', price=.045)))

    def test_position_failure_not_flat(self):
        class Bad:
            def get(self, *_):
                raise RuntimeError('API down')
        with self.assertRaises(RuntimeError):
            e1run.position_inventory(Bad(), 'x')

    def test_reserve_complement_buys_against_sell_quantity(self):
        pending = dict(order(side='no', action='buy', qty=80, price=.6), open=True)
        self.assertFalse(risk.is_reduction(order(), [pos()], [pending]))
        self.assertTrue(risk.is_reduction(order(qty=20), [pos()], [pending]))

    def test_pending_negative_quantity_is_rejected(self):
        pending = dict(order(qty=-20), open=True)
        with self.assertRaises(ValueError):
            risk.is_reduction(order(), [pos()], [pending])

    def test_highest_fifo_cost_not_average(self):
        p = dict(pos(), lots=[dict(entryPrice=.7), dict(entryPrice=.1)])
        self.assertEqual(risk.cost_ceiling(p), .7)
        result = e1run.proposal(p, book(), [p])
        self.assertGreaterEqual(result['price'], .71)

    def test_yes_sale_capped_at_visible_bid_depth(self):
        p = pos()
        result = e1run.proposal(p, book(size=7), [p])
        self.assertEqual(result, order(qty=7))

    def test_no_sale_uses_complement_of_yes_ask(self):
        p = pos(qty=-100, cost=.3)
        result = e1run.proposal(p, book(size=9), [p])
        self.assertEqual(result, order(side='no', qty=9, price=.4))

    def test_no_ask_depth_makes_passive_quote_not_market_order(self):
        p = pos()
        result = e1run.proposal(p, dict(bids=[], asks=[dict(price=.6, quantity=100)]), [p])
        self.assertEqual(result['price'], .595)
        self.assertEqual(result['action'], 'sell')

    def test_prices_above_payout_or_empty_book_do_not_quote(self):
        p = pos(cost=.99)
        self.assertIsNone(e1run.proposal(p, book(), [p]))
        p = pos()
        self.assertIsNone(e1run.proposal(p, dict(bids=[], asks=[]), [p]))

    def test_does_not_dump_profitable_winner_below_mark(self):
        p = dict(pos(qty=-100, cost=.075), marketValue=14.3)
        result = e1run.proposal(p, book(.80, .91), [p])
        self.assertGreaterEqual(result['price'], .143)
        self.assertEqual(result['side'], 'no')

    def test_crossed_or_nonfinite_book_rejected(self):
        p = pos()
        for b in (book(.7, .6), book(float('nan'), .6)):
            with self.assertRaises(ValueError):
                e1run.proposal(p, b, [p])

    def test_paired_no_basket_not_unwound_one_leg(self):
        group = [pos('1', -100), pos('2', -100)]
        self.assertEqual(risk.settlement_floor(group), 100)
        self.assertEqual(risk.floor_safe_quantity(group, '1', .995, 25), 0)

    def test_excess_leg_can_reduce_without_breaking_basket(self):
        group = [pos('1', -125), pos('2', -100)]
        self.assertEqual(risk.floor_safe_quantity(group, '1', .8, 25), 25)

    def test_floor_includes_unlisted_winner(self):
        self.assertEqual(risk.settlement_floor([pos('1', 100), pos('2', 100)]), 0)

    def test_floor_safe_quantity_is_exact_brute_force(self):
        rng = random.Random(9)
        for _ in range(300):
            group = [pos(str(i), rng.choice([-1, 1])*rng.randint(1, 25)) for i in range(3)]
            price = rng.randint(1, 199)*.005
            before = risk.settlement_floor(group)
            maximum = min(20, abs(group[0]['quantity']))
            safe = []
            for q in range(maximum+1):
                after = copy.deepcopy(group)
                after[0]['quantity'] -= q if group[0]['quantity'] > 0 else -q
                if risk.settlement_floor(after)+price*q >= before-1e-9:
                    safe.append(q)
            self.assertEqual(risk.floor_safe_quantity(group, '0', price, maximum), max(safe))

    def test_unknown_and_duplicate_party_groups_skipped(self):
        group = [pos('1'), pos('2')]
        self.assertEqual(risk.race_groups(group, {})[0], {})
        self.assertEqual(risk.race_groups(group, {'1': node(), '2': node()})[0], {})
        self.assertEqual(len(risk.race_groups(group, {'1': node('D'), '2': node('R')})[0]), 1)

    def test_guard_blocks_other_pending_leg_in_race(self):
        account = dict(positions={'positions': [pos('1'), pos('2')]},
                       openOrders=[dict(order('2'), id=9, open=True)])
        with self.assertRaisesRegex(ValueError, 'pending order'):
            e1run.check_reduction(order(), account, {'1': node('D'), '2': node('R')})

    def test_guard_rechecks_cost_after_positions_change(self):
        account = dict(positions={'positions': [pos(cost=.6)]}, openOrders=[])
        with self.assertRaisesRegex(ValueError, 'cost'):
            e1run.check_reduction(order(), account, {'1': node()})

    def test_guard_ignores_only_own_existing_order_id(self):
        current = dict(order(), id=9, open=True)
        account = dict(positions={'positions': [pos()]}, openOrders=[current])
        e1run.check_reduction(current, account, {'1': node()}, ignore_id=9)
        with self.assertRaises(ValueError):
            e1run.check_reduction(current, account, {'1': node()})

    def test_legacy_exit_closes_signed_no_by_selling_no(self):
        result = closing_order(pos(qty=-10), .5, .5)
        self.assertEqual(result, order(side='no', qty=5))

    def test_legacy_log_provenance_only_successful_submits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'log'
            path.write_text('ERROR "orderId": 3\nSUBMIT X -> {"orderId": 8}\nCANCEL 5\n')
            self.assertEqual(legacy_ids(path), {8})

    def test_audit_distinguishes_reductions_new_positions_and_flips(self):
        changes = exposure_changes([pos('1', -20), pos('2', 20), pos('4', 8)],
                                   [pos('1', -10), pos('2', -5), pos('3', 1)])
        flags = {x['exchangeId']: x['increasedOrFlipped'] for x in changes}
        self.assertEqual(flags, {'1': False, '2': True, '3': True, '4': False})


class LoopClient(FakeClient):
    def get(self, path, **params):
        if path.endswith('/orderbook'):
            return book(.3, .6)
        return super().get(path, **params)

    def post(self, path, body):
        self.posts.append((path, body))
        oid = 100+len(self.posts)
        self.orders.append(dict(body, id=oid, priceLimit=body['price'], open=True))
        return {'orderId': oid}

    def delete(self, path):
        super().delete(path)
        self.orders = [o for o in self.orders if str(o['id']) != path.rsplit('/', 1)[1]]
        return {'ok': True}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        patcher = patch.object(e1run, 'DIRECTORY', self.directory)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = LoopClient('active')
        self.client.positions = [pos()]
        self.exe = Executor(dry_run=False, client=self.client,
                            journal_path=self.directory/'journal.json', recovery_path=self.directory/'mode.json')
        self.runner = e1run.RecoveryRunner(self.exe, nodes={'1': node()})

    def test_two_cycles_keep_same_owned_order_without_churn(self):
        first = self.runner.cycle()
        second = self.runner.cycle()
        self.assertEqual(len(first['submitted']), 1)
        self.assertEqual(len(second['submitted']), 0)
        self.assertEqual(len(second['heldOrders']), 1)
        self.assertFalse(self.client.deleted)
        self.assertEqual(self.client.posts[0][1]['action'], 'sell')
        self.assertIn('expirationDate', self.client.posts[0][1])

    def test_restart_recovers_owned_order(self):
        self.runner.cycle()
        replacement = e1run.RecoveryRunner(self.exe, nodes={'1': node()})
        self.assertEqual(len(replacement.cycle()['submitted']), 0)
        replacement.cancel_owned()
        self.assertEqual(self.client.deleted, ['/orders/101'])

    def test_inventory_disappears_cancel_before_new_order(self):
        self.runner.cycle()
        self.client.positions = []
        self.runner.cycle()
        self.assertEqual(self.client.deleted, ['/orders/101'])
        self.assertEqual(len(self.client.posts), 1)

    def test_foreign_order_never_cancelled_or_replaced(self):
        self.client.orders = [dict(order(), id=999, open=True, priceLimit=.5)]
        result = self.runner.cycle()
        self.runner.cancel_owned()
        self.assertFalse(result['submitted'])
        self.assertFalse(self.client.posts)
        self.assertFalse(self.client.deleted)

    def test_paper_posts_nothing(self):
        self.exe.dry_run = True
        result = self.runner.cycle()
        self.assertTrue(result['submitted'][0]['result']['dry_run'])
        self.assertFalse(self.client.posts)
        self.assertEqual(self.exe.journal(), {})

    def test_one_quote_per_race(self):
        self.client.positions = [pos('1'), pos('2')]
        self.runner.nodes['2'] = node('R')
        self.assertEqual(len(self.runner.cycle()['submitted']), 1)

    def test_stop_during_account_refresh_blocks_placement(self):
        checks = []
        def stopping():
            checks.append(1)
            return len(checks) >= 3  # loop, paper guard, then fresh pre-POST guard
        self.runner.stopping = stopping
        with self.assertRaisesRegex(RuntimeError, 'Stopping'):
            self.runner.cycle()
        self.assertFalse(self.client.posts)
        self.assertFalse(self.exe.journal())

    def test_e2_recovery_hold_does_not_construct_executor(self):
        path = self.directory/'data/recovery'
        path.mkdir(parents=True)
        (path/'mode.json').write_text(json.dumps({'reduceOnly': True}))
        with patch.object(e2watch, 'ROOT', self.directory), patch.object(e2watch, 'beat') as beat, \
                patch.object(e2watch, 'Executor') as executor:
            e2watch.run_once({}, SimpleNamespace(live=True))
            self.assertEqual(beat.call_args.args[0]['phase'], 'recovery_hold')
            executor.assert_not_called()

    def test_pilot_reservation_skips_recovery_inventory(self):
        self.exe.recovery_path.write_text(json.dumps({'reduceOnly': True,
                    'openingPermit': {'reservedExchangeIds': ['1']}}))
        result = self.runner.cycle()
        self.assertEqual(result['submitted'], [])
        self.assertFalse(self.client.posts)


if __name__ == '__main__':
    unittest.main()
