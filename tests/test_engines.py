import unittest
import tempfile
from pathlib import Path
from research.engines.engine1_mm import MarketMaker
from research.engines.engine2_baskets import NoBasket
from research.engines.engine4_conditional import ConditionalYes
from research.engines.engine5_chamber import ChamberAggregation
from research.allocator import Allocator, ENGINES
from research.gate import Gate, GateClosed


class FakeClient:
    def __init__(self, status='draft'):
        self.status = status

    def get(self, path, **params):
        return {'id': 'tid', 'slug': 'midterm-elections', 'status': self.status,
                'startDate': '2026-10-01T16:00:00.000Z', 'endDate': '2026-11-04T17:00:00.000Z'}


def mm_state():
    return {'books': [{'exchangeId': '1075', 'yesBid': 0.04, 'yesAsk': 0.12}],
            'fair': {'1075': 0.08}}


class EngineTests(unittest.TestCase):
    def test_mm_quotes_inside_spread(self):
        mm = MarketMaker(lot=10)
        intents = mm.quote(mm_state())
        self.assertEqual(len(intents), 2)
        bid = next(i for i in intents if i['action'] == 'buy')
        ask = next(i for i in intents if i['action'] == 'sell')
        self.assertLess(bid['price'], ask['price'])

    def test_mm_skips_thin_spread(self):
        mm = MarketMaker(min_spread=0.02)
        state = {'books': [{'exchangeId': '1', 'yesBid': 0.5, 'yesAsk': 0.51}]}
        self.assertEqual(mm.quote(state), [])

    def test_mm_respects_position_limit(self):
        mm = MarketMaker(max_position=5)
        mm.inventory = {'1075': 5}
        self.assertEqual(mm.quote(mm_state()), [])

    def test_mm_skew_moves_with_inventory(self):
        long = MarketMaker(max_position=5000)
        long.inventory = {'1075': 1000}
        short = MarketMaker(max_position=5000)
        short.inventory = {'1075': -1000}
        lb = [i for i in long.quote(mm_state()) if i['action'] == 'buy'][0]['price']
        sb = [i for i in short.quote(mm_state()) if i['action'] == 'buy'][0]['price']
        self.assertLess(lb, sb)

    def test_basket_builds_atomic_payload(self):
        eng = NoBasket()
        cand = {'race': 'U.S. Senate Delaware', 'quantityEach': 100, 'cost': 97.0,
                'legs': [{'exchangeId': '1075', 'side': 'no'},
                         {'exchangeId': '1042', 'side': 'no'}]}
        intents = eng.quote({'no_baskets': [cand]})
        self.assertEqual(len(intents), 1)
        self.assertIn('legs', intents[0]['basket'])
        self.assertEqual(len(intents[0]['basket']['legs']), 2)

    def test_conditional_flagged_assumption(self):
        eng = ConditionalYes()
        cand = {'race': 'X', 'quantityEach': 10, 'cost': 9.0,
                'legs': [{'exchangeId': '1', 'side': 'yes'}]}
        intents = eng.quote({'conditional_baskets': [cand]})
        self.assertIn('not guaranteed', intents[0]['assumption'])

    def test_chamber_stub_empty(self):
        self.assertEqual(ChamberAggregation().quote({}), [])


class AllocatorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ledger = Path(directory.name) / 'ledger.json'

    def test_weights_sum_bounded(self):
        a = Allocator(ledger_path=self.ledger)
        a.record('E1', 100.0, 10.0)
        a.record('E2', -600.0, 10.0)
        w = a.update()
        self.assertLess(w['E2'], w['E1'])
        for v in w.values():
            self.assertGreaterEqual(v, 0.05 - 1e-9)
            self.assertLessEqual(v, 0.40 + 1e-9)

    def test_drawdown_cooldown(self):
        a = Allocator(drawdown_halt=-100.0, cooldown_cycles=5, ledger_path=self.ledger)
        a.record('E3', -500.0, 10.0)
        a.update()
        self.assertGreater(a.cooldown['E3'], 0)
        self.assertEqual(a.weights['E3'], round(1/len(ENGINES) - 0.1, 4))

    def test_live_zero_until_open(self):
        a = Allocator(ledger_path=self.ledger)
        a.update()
        alloc = a.allocate(10000.0)
        self.assertEqual(sum(alloc.values()), 0.0)

    def test_e6_never_receives_live_capital(self):
        a = Allocator(ledger_path=self.ledger)
        a.live_open = True
        a.record('E6', 1000, 1)
        a.update()
        self.assertEqual(a.allocate(10000)['E6'], 0)


class GateTests(unittest.TestCase):
    def test_draft_blocked(self):
        g = Gate(FakeClient('draft'))
        with self.assertRaises(GateClosed):
            g.check()

    def test_open_window_passes(self):
        from datetime import datetime, timezone
        for status in ('open', 'active'):
            g = Gate(FakeClient(status))
            now = datetime(2026, 10, 15, tzinfo=timezone.utc)
            self.assertEqual(g.check(now=now)['status'], status)

    def test_ended_blocked(self):
        from datetime import datetime, timezone
        g = Gate(FakeClient('open'))
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        with self.assertRaises(GateClosed):
            g.check(now=now)


if __name__ == '__main__':
    unittest.main()
