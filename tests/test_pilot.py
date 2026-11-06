from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from research.execution import Executor, build_single
from research.pilot import PREFIX, opening_proof, reservations
from test_execution import FakeClient


def permit(now):
    return {'version': 1, 'prefix': PREFIX, 'entryEnabled': True, 'maxCapital': 100,
            'expiresAt': (now+timedelta(hours=1)).isoformat(), 'reservedExchangeIds': ['3', '4'],
            'exchanges': {'3': {'side': 'no', 'maxShares': 100}}}


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.permit = permit(self.now)
        self.order = dict(build_single('3', 'no', 'buy', 100, .77, 'tid'),
                          idempotencyKey=PREFIX+'unit', expirationDate=(self.now+timedelta(seconds=120)).isoformat())
        self.account = {'positions': {'positions': []}, 'openOrders': []}

    def test_exact_scope_opening(self):
        self.assertEqual(opening_proof(self.order, self.account, self.permit, self.now)['capitalAfter'], 77)

    def test_expired_disabled_wrong_version(self):
        for changes in ({'expiresAt': self.now.isoformat()}, {'entryEnabled': False}, {'version': 2}):
            with self.assertRaises(ValueError):
                opening_proof(self.order, self.account, dict(self.permit, **changes), self.now)

    def test_size_side_target_action_key_expiry(self):
        changes = [{'quantity': 101}, {'side': 'yes'}, {'exchangeId': '4'}, {'action': 'sell'},
                   {'idempotencyKey': 'E1-unit'}, {'expirationDate': (self.now+timedelta(hours=2)).isoformat()}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                opening_proof(dict(self.order, **change), self.account, self.permit, self.now)

    def test_no_adding_inventory_or_other_race_holding(self):
        for eid in ('3', '4'):
            account = deepcopy(self.account)
            account['positions']['positions'] = [{'exchangeId': eid, 'quantity': -1, 'costBasis': .77}]
            with self.assertRaises(ValueError):
                opening_proof(self.order, account, self.permit, self.now)

    def test_pending_reservation_capital(self):
        account = dict(self.account, openOrders=[dict(id=1, exchangeId='4', open=True)])
        with self.assertRaises(ValueError):
            opening_proof(self.order, account, self.permit, self.now)
        with self.assertRaises(ValueError):
            opening_proof(self.order, self.account, dict(self.permit, maxCapital=76), self.now)

    def test_reservation_survives_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'mode.json'
            path.write_text(json.dumps({'openingPermit': dict(self.permit, expiresAt=self.now.isoformat())}))
            self.assertEqual(reservations(path), {'3', '4'})

    def test_executor_scoped_exception_not_blanket_rearm(self):
        with tempfile.TemporaryDirectory() as d:
            mode = Path(d)/'mode.json'
            mode.write_text(json.dumps({'reduceOnly': True, 'openingPermit': self.permit}))
            client = FakeClient('active')
            exe = Executor(client=client, dry_run=False, journal_path=Path(d)/'journal.json', recovery_path=mode)
            with self.assertRaises(RuntimeError):
                exe.submit_single(self.order)  # must have a lifecycle guard
            with self.assertRaises(RuntimeError):
                exe.submit_single(self.order, reduce_only=True, guard=lambda _: {})
            with self.assertRaises(ValueError):
                exe.submit_single(dict(self.order, idempotencyKey='other'), guard=lambda _: {})
            result = exe.submit_single(self.order, guard=lambda _: {'tested': True})
            self.assertEqual(result['orderId'], 123)
            self.assertEqual(len(client.posts), 1)


if __name__ == '__main__':
    unittest.main()
