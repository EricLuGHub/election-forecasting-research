from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest
from research.campaign import measure, run


def board():
    return {'period': 'all', 'activeGroupId': None, 'offset': 0, 'sort': 'pnl', 'total': 100,
            'myRank': 50, 'leaderboard': [{'rank': r, 'pnl': 10000-r*100} for r in range(1, 31)]}


def pnl(value):
    return {'period': 'all', 'periodPnl': value}


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.end = self.now+timedelta(hours=48)

    def test_gap_uses_twentieth_not_first(self):
        r = measure(board(), pnl(2000), self.end, self.now)
        self.assertEqual(r['top20CutoffPnl'], 8000)
        self.assertEqual(r['gapToCurrentCutoff'], 6000)
        self.assertEqual(r['requiredCatchUpPerHourAtFixedCutoff'], 125)
        self.assertFalse(r['paceValidated'])

    def test_tied_rank_skips_twentieth(self):
        b = board()
        b['leaderboard'][19].update(rank=19, pnl=8100)
        self.assertEqual(measure(b, pnl(0), self.end, self.now)['top20CutoffPnl'], 8100)

    def test_scope_and_sort_fail_closed(self):
        for change in ({'period':'1d'}, {'activeGroupId':'X'}, {'offset':20}, {'sort':'volume'}):
            with self.assertRaises(ValueError):
                measure(dict(board(), **change), pnl(0), self.end, self.now)

    def test_pnl_period_matches_rank_period(self):
        with self.assertRaisesRegex(ValueError, 'all-time'):
            measure(board(), {'period': 'quarter', 'periodPnl': 0}, self.end, self.now)

    def test_null_all_time_uses_labeled_fixed_bankroll_difference(self):
        r = measure(board(), {'period': 'all', 'periodPnl': None, 'totalAccountValue': 100473.61},
                    self.end, self.now, {'slug': 'midterm-elections', 'initialBalance': 100000})
        self.assertEqual(r['ownPnl'], 473.61)
        self.assertEqual(r['ownPnlSource'], 'account_value_minus_tournament_initial_balance')

    def test_missing_all_time_does_not_become_zero(self):
        with self.assertRaises(ValueError):
            measure(board(), {'period': 'all', 'periodPnl': None}, self.end, self.now)

    def test_unranked_is_not_success(self):
        b = dict(board(), myRank=None)
        self.assertFalse(measure(b, pnl(9000), self.end, self.now)['observedTop20'])

    def test_rank_not_own_mark_estimate_establishes_top20(self):
        b = dict(board(), myRank=20)
        self.assertTrue(measure(b, pnl(7999), self.end, self.now)['observedTop20'])

    def test_deadline_not_reset_by_restart(self):
        class Client:
            def get(self, path, **kw):
                return board() if path.endswith('leaderboard') else pnl(10)
        with tempfile.TemporaryDirectory() as d:
            run(Path(d), self.end.isoformat(), Client())
            with self.assertRaisesRegex(ValueError, 'silently reset'):
                run(Path(d), (self.end+timedelta(hours=1)).isoformat(), Client())
            self.assertEqual(run(Path(d), client=Client())['deadline'], self.end.isoformat())

    def test_deadline_passed_is_persisted_without_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(Path(d), (self.now-timedelta(hours=2)).isoformat(), object())
            self.assertEqual(r['phase'], 'deadline_passed')
            self.assertEqual(json.loads((Path(d)/'campaign-status.json').read_text()), r)


if __name__ == '__main__':
    unittest.main()
