from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from research.execution import Executor
from research.reconcile_order import matching, resolve


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.start = (now-timedelta(hours=1)).isoformat()
        self.expiry = now-timedelta(minutes=57)
        self.body = {'exchangeId': '3', 'side': 'no', 'action': 'sell', 'quantity': 25,
                     'price': .145, 'tournamentId': 'tid', 'idempotencyKey': 'E1R-test',
                     'expirationDate': self.expiry.isoformat()}
        self.order = dict(self.body, id=9, priceLimit=.145, open=False,
                          createdAt=(now-timedelta(minutes=59, seconds=30)).isoformat(),
                          expirationDate=self.expiry.isoformat(timespec='milliseconds'))
        self.fills = {'orderId': 9, 'exchangeId': '3', 'tournamentId': 'tid',
                      'coverage': {'complete': True}, 'totalQuantityFilled': 0, 'avgFillPrice': None}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)/'journal.json'
        self.path.write_text(json.dumps({'E1R-test': {'status': 'unknown', 'route': '/orders',
                                                    'body': self.body, 'at': self.start}}))
        test = self
        class Client:
            def get(self, path, **kw):
                if path == '/orders/9': return test.order
                if path == '/orders/9/fills': return test.fills
                return {'id': 'tid'}
            def pages(self, path, **kw):
                return [test.order]
            def post(self, *a): raise AssertionError('Never replay placement')
            def delete(self, *a): raise AssertionError('Never mutate venue')
        self.exe = Executor(client=Client(), journal_path=self.path)

    def test_exact_match_tolerates_only_millisecond_truncation(self):
        self.assertTrue(matching(self.body, self.start, self.order))
        self.assertFalse(matching(self.body, self.start, dict(self.order, expirationDate=(self.expiry+timedelta(seconds=1)).isoformat())))

    def test_dry_run_preserves_unknown(self):
        self.assertFalse(resolve(self.exe, 'E1R-test', 9)['placementReplayed'])
        self.assertEqual(self.exe.journal()['E1R-test']['status'], 'unknown')

    def test_apply_preserves_body_and_adds_evidence(self):
        resolve(self.exe, 'E1R-test', 9, True)
        row = self.exe.journal()['E1R-test']
        self.assertEqual(row['body'], self.body)
        self.assertEqual(row['status'], 'confirmed')
        self.assertIn('resolution', row)

    def test_ambiguous_match_rejected(self):
        self.exe.client.pages = lambda *a, **kw: [self.order, dict(self.order, id=10)]
        with self.assertRaises(ValueError): resolve(self.exe, 'E1R-test', 9, True)

    def test_open_wrong_price_scope_side_and_fill_rejected(self):
        for patch in ({'open': True}, {'priceLimit': .14}, {'side': 'yes'}, {'tournamentId': 'other'}):
            self.assertFalse(matching(self.body, self.start, dict(self.order, **patch)))
        self.fills['totalQuantityFilled'] = -30
        with self.assertRaises(ValueError): resolve(self.exe, 'E1R-test', 9, True)


if __name__ == '__main__':
    unittest.main()
