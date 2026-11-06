from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

from research.engines.engine7_maker import entry, fill_accounting
from research.pilot import opening_proof, trial_scope
from research.trial_health import check, issues, repair_unknown
from test_engine7 import RunnerTests, BOOK, REF, fill, journal, SCOPES, START
from test_pilot import PilotTests

TRIAL_PREFIX = 'E7T-012345abcdef-'


def convert(permit):
    p = deepcopy(permit)
    p.update(version=2, prefix=TRIAL_PREFIX, baselineInventory={'4': 200}, maxCapital=500)
    p['exchanges']['3']['raceExchangeIds'] = ['3', '4']
    return p


class TrialPermitTests(PilotTests):
    def setUp(self):
        super().setUp()

    def trial(self):
        p = convert(self.permit)
        o = dict(self.order, idempotencyKey=TRIAL_PREFIX+'one')
        a = deepcopy(self.account)
        a['positions']['positions'].append({'exchangeId': '4', 'quantity': 200, 'costBasis': 100})
        return p, o, a

    def test_frozen_counterpart_not_charged_to_trial_capital(self):
        p, o, a = self.trial()
        self.assertEqual(opening_proof(o, a, p, self.now)['capitalAfter'], 77)

    def test_changed_counterpart_blocks(self):
        p, o, a = self.trial()
        a['positions']['positions'][0]['quantity'] = 199
        with self.assertRaisesRegex(ValueError, 'baseline'):
            opening_proof(o, a, p, self.now)

    def test_another_run_key_blocked(self):
        p, o, a = self.trial()
        with self.assertRaises(ValueError):
            opening_proof(dict(o, idempotencyKey='E7T-999999999999-one'), a, p, self.now)

    def test_disjoint_race_pending_allowed_but_counts_capital(self):
        p, o, a = self.trial()
        p['exchanges']['5'] = {'side': 'yes', 'maxShares': 100, 'raceExchangeIds': ['5']}
        p['reservedExchangeIds'].append('5')
        a['openOrders'] = [dict(id=8, exchangeId='5', action='buy', side='yes', quantity=100, priceLimit=.5, open=True)]
        self.assertEqual(opening_proof(o, a, p, self.now)['capitalAfter'], 127)
        with self.assertRaises(ValueError):
            opening_proof(o, a, dict(p, maxCapital=126), self.now)

    def test_same_race_pending_blocks(self):
        p, o, a = self.trial()
        a['openOrders'] = [dict(id=8, exchangeId='4', open=True)]
        with self.assertRaises(ValueError):
            opening_proof(o, a, p, self.now)

    def test_unreserved_or_overlapping_baseline_rejected(self):
        p, _, _ = self.trial()
        for change in ({'baselineInventory': {}}, {'reservedExchangeIds': ['3']}, {'prefix': 'E7T-'}):
            with self.assertRaises(ValueError):
                trial_scope(dict(p, **change))


class TrialRunnerTests(RunnerTests):
    def setUp(self):
        super().setUp()

    def new_runner(self):
        from research.e7run import Runner
        cfg = convert(self.config)
        cfg.update(referenceBuffer=.015, minSpread=.01, compareQuotes=True, minExitDepth=100)
        (self.path/'config.json').write_text(json.dumps(cfg))
        (self.path/'mode.json').write_text(json.dumps({'reduceOnly': True, 'openingPermit': dict(cfg, entryEnabled=True)}))
        self.client.positions = [{'exchangeId': '4', 'quantity': 200, 'costBasis': 100}]
        self.runner = Runner(self.exe, self.path, reference_get=lambda _: {'market': REF})
        return cfg

    def test_trial_entry_leaves_baseline_untouched(self):
        self.new_runner()
        self.runner.cycle()
        self.assertEqual(self.client.posts[0][1]['exchangeId'], '3')
        self.assertTrue(self.client.posts[0][1]['idempotencyKey'].startswith(TRIAL_PREFIX))

    def test_health_halt_prevents_entry(self):
        self.new_runner()
        (self.path/'health-halt.json').write_text('{}')
        self.assertEqual(self.runner.cycle()['phase'], 'entries_halted')
        self.assertFalse(self.client.posts)

    def test_foreign_pending_in_other_reserved_race_blocks(self):
        cfg = self.new_runner()
        self.client.orders = [dict(id=99, exchangeId='4', open=True, action='sell', side='yes', quantity=5, priceLimit=.5)]
        with self.assertRaisesRegex(ValueError, 'Foreign'):
            self.runner.cycle()
        self.assertFalse(self.client.posts)

    def test_frozen_baseline_changed_in_preflight_blocks(self):
        self.new_runner()
        original, calls = self.exe.preflight, []
        def preflight():
            calls.append(1)
            if len(calls) == 2:
                self.client.positions[0]['quantity'] = 199
            return original()
        self.exe.preflight = preflight
        with self.assertRaises(ValueError):
            self.runner.cycle()
        self.assertFalse(self.client.posts)

    def test_read_only_audit_does_not_submit_or_change_permit(self):
        from research.trial_review import audit
        self.new_runner()
        before = (self.path/'mode.json').read_text()
        result = audit(self.exe, self.path)
        self.assertTrue(result['flat'])
        self.assertTrue(result['baselineInventoryUnchanged'])
        self.assertFalse(result['strategyValidated'])
        self.assertFalse(result['issues'])
        self.assertFalse(self.client.posts)
        self.assertEqual(before, (self.path/'mode.json').read_text())

    def test_audit_separates_partial_fill_and_pending_order(self):
        from research.trial_review import audit
        self.new_runner()
        own = journal()['E7M-buy']
        (self.path/'journal.json').write_text(json.dumps({TRIAL_PREFIX+'buy': own}))
        self.client.fills = [fill(qty=-30)]
        self.client.positions.append({'exchangeId': '3', 'quantity': -30, 'costBasis': 23.1})
        self.client.orders = [dict(id=1, exchangeId='3', side='no', action='buy', quantity=70, priceLimit=.77, open=True)]
        result = audit(self.exe, self.path)
        self.assertFalse(result['flat'])
        self.assertEqual(result['actualTrialInventory']['3'], -30)
        self.assertEqual(result['actualFillRecords'], 1)
        self.assertEqual(result['openOrders'][0]['quantity'], 70)
        self.assertFalse(self.client.posts)

    def test_finish_requires_expiry_and_flat_then_releases_reservations(self):
        from research.trial_finish import finish
        cfg = self.new_runner()
        with self.assertRaisesRegex(ValueError, 'not finished'):
            finish(self.exe, self.path, True)
        cfg['expiresAt'] = START
        (self.path/'config.json').write_text(json.dumps(cfg))
        data = json.loads((self.path/'mode.json').read_text())
        data['openingPermit']['expiresAt'] = START
        (self.path/'mode.json').write_text(json.dumps(data))
        result = finish(self.exe, self.path, True)
        self.assertTrue(result['flat'])
        self.assertTrue((self.path/'shutdown.request').exists())
        after = json.loads((self.path/'mode.json').read_text())
        self.assertTrue(after['reduceOnly'])
        self.assertNotIn('openingPermit', after)
        self.assertFalse(self.client.posts)

    def test_finish_cannot_abandon_open_inventory(self):
        from research.trial_finish import finish
        cfg = self.new_runner()
        cfg['expiresAt'] = START
        (self.path/'config.json').write_text(json.dumps(cfg))
        self.client.positions.append({'exchangeId': '3', 'quantity': -1, 'costBasis': .77})
        with self.assertRaisesRegex(ValueError, 'inventory'):
            finish(self.exe, self.path, True)
        self.assertFalse((self.path/'completed.json').exists())

    def test_finish_cannot_abandon_pending_orders(self):
        from research.trial_finish import finish
        cfg = self.new_runner()
        cfg['expiresAt'] = START
        (self.path/'config.json').write_text(json.dumps(cfg))
        self.client.orders = [dict(id=1, exchangeId='3', side='no', action='buy', quantity=100, priceLimit=.77, open=True)]
        with self.assertRaisesRegex(ValueError, 'pending'):
            finish(self.exe, self.path, True)
        self.assertFalse((self.path/'shutdown.request').exists())


class TrialPureTests(unittest.TestCase):
    def test_join_and_improve_never_cross(self):
        join = entry(BOOK, 'no', REF, 100, .015, .01, 'join')
        improve = entry(BOOK, 'no', REF, 100, .015, .01, 'improve')
        self.assertEqual(join['price'], .765)
        self.assertEqual(improve['price'], .77)
        self.assertLess(improve['price'], .79)
        with self.assertRaises(ValueError):
            entry(BOOK, 'no', REF, 100, .005, .01, 'improve')

    def test_new_run_does_not_attribute_old_run_fill(self):
        with self.assertRaisesRegex(ValueError, 'Foreign'):
            fill_accounting([fill()], journal(), SCOPES, START, TRIAL_PREFIX)

    def test_stale_and_errors_halt_no_automatic_clear(self):
        now = datetime.now(timezone.utc)
        cfg = {'startedAt': (now-timedelta(minutes=5)).isoformat()}
        self.assertTrue(issues(cfg, {}, now))
        self.assertTrue(issues(cfg, dict(at=cfg['startedAt']), now))
        self.assertTrue(issues(cfg, dict(at=now.isoformat(), consecutiveFailures=3), now))
        self.assertFalse(issues(cfg, dict(at=now.isoformat()), now))

    def test_unexpired_unknown_never_replayed_or_repaired(self):
        from test_execution import FakeClient
        class Exe:
            client = FakeClient()
        row = dict(route='/orders', body={'expirationDate': (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()})
        with patch('research.trial_health.resolve') as resolver:
            self.assertIsNone(repair_unknown(Exe(), TRIAL_PREFIX+'x', row, True, datetime.now(timezone.utc)))
            resolver.assert_not_called()

    def test_inflight_write_ahead_does_not_falsely_halt(self):
        from research.execution import Executor
        from test_execution import FakeClient
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)
            (path/'config.json').write_text(json.dumps({'prefix': TRIAL_PREFIX, 'startedAt': now.isoformat()}))
            (path/'journal.json').write_text(json.dumps({TRIAL_PREFIX+'x': {
                'status': 'unknown', 'route': '/orders', 'at': now.isoformat(),
                'body': {'expirationDate': (now+timedelta(seconds=120)).isoformat()}}}))
            exe = Executor(client=FakeClient(), journal_path=path/'journal.json')
            result = check(exe, path, apply=True)
            self.assertFalse(result['alerts'])
            self.assertEqual(len(result['awaitingPlacement']), 1)
            self.assertFalse((path/'health-halt.json').exists())

    def test_completed_shutdown_is_not_a_stale_active_runner(self):
        from research.execution import Executor
        from test_execution import FakeClient
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)
            (path/'config.json').write_text(json.dumps({'prefix': TRIAL_PREFIX, 'startedAt': START}))
            (path/'completed.json').write_text('{}')
            (path/'shutdown.request').write_text('{}')
            result = check(Executor(client=FakeClient(), journal_path=path/'journal.json'), path, apply=True)
            self.assertTrue(result['completed'])
            self.assertTrue(result['entryHalted'])
            self.assertFalse(result['alerts'])

    def test_ambiguous_expired_match_stays_blocked(self):
        from research.execution import Executor
        from test_execution import FakeClient
        now = datetime.now(timezone.utc)
        row = dict(route='/orders', at=(now-timedelta(minutes=5)).isoformat(),
                   body={'expirationDate': (now-timedelta(minutes=3)).isoformat(),
                         'exchangeId': '3', 'tournamentId': 'tid'})
        exe = Executor(client=FakeClient())
        with patch('research.trial_health.resolve') as resolver:
            self.assertIsNone(repair_unknown(exe, TRIAL_PREFIX+'x', row, True, now))
            resolver.assert_not_called()


if __name__ == '__main__':
    unittest.main()
