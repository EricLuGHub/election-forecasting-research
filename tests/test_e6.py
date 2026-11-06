from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from research.engines.engine6_value import ReferenceValue, ValueConfig, account_risk, levels
from research.e6data import ValueCollector, contract_identity, exclude_own_liquidity
from research.e6run import (PaperStore, liquidate, new_portfolio, read_status,
                            run_cycle, simulate, tournament_open)
from research.e6eval import summarize


NOW = datetime.now(timezone.utc).isoformat()


def stamps():
    return {'receivedAt': NOW, 'requestStartedAt': NOW}


def instrument(eid='10', race='r1'):
    return {'exchangeId': eid, 'marketId': eid, 'title': 'Test market', 'raceKey': race,
            'mappingStatus': 'candidate_requires_settlement_review', 'definition': stamps(),
            'reference': dict(stamps(), bid=.70, ask=.72, bidSize=100, askSize=100,
                              volume24h=1000, status='active', ticker='TEST-26-D'),
            'book': dict(stamps(), bids=[{'price': .49, 'quantity': 100}],
                         asks=[{'price': .50, 'quantity': 100}])}


def state():
    return {'now': NOW, 'account': dict(stamps(), cash=90000, equity=100000, positions=[], orders=[]),
            'raceByExchange': {'10': 'r1'}, 'instruments': [instrument()],
            'paperPositions': {}, 'paperCash': 2000, 'paperBankroll': 2000}


class EngineValueTests(unittest.TestCase):
    def test_yes_entry_clears_all_costs_and_depth(self):
        intent, = ReferenceValue().quote(state())
        self.assertEqual((intent['side'], intent['action'], intent['price']), ('yes', 'buy', .5))
        self.assertAlmostEqual(intent['edge'], .165)
        self.assertLessEqual(intent['quantity'], 100)
        self.assertFalse(intent['executionEligible'])

    def test_no_entry_uses_complement_of_yes_bid(self):
        s = state()
        s['instruments'][0]['reference'].update(bid=.20, ask=.22)
        intent, = ReferenceValue().quote(s)
        self.assertEqual(intent['side'], 'no')
        self.assertAlmostEqual(intent['price'], .51)

    def test_each_marginal_share_must_clear_edge(self):
        s = state()
        s['instruments'][0]['book']['asks'] = [{'price': .5, 'quantity': 7}, {'price': .66, 'quantity': 999}]
        intent, = ReferenceValue().quote(s)
        self.assertEqual(intent['quantity'], 7)
        self.assertEqual(intent['price'], .5)

    def test_stale_future_missing_and_slow_data_fail_closed(self):
        for field in ('account', 'book', 'reference', 'definition'):
            for broken in ('2000-01-01T00:00:00Z', '2099-01-01T00:00:00Z', 'broken', None):
                with self.subTest(field=field, broken=broken):
                    s = state()
                    obj = s['account'] if field == 'account' else s['instruments'][0][field]
                    obj['receivedAt'] = broken
                    self.assertEqual(ReferenceValue().quote(s), [])
        s = state()
        s['instruments'][0]['book']['requestStartedAt'] = '2000-01-01T00:00:00Z'
        self.assertEqual(ReferenceValue().quote(s), [])

    def test_reference_quality_filters(self):
        for bad in ({'bid': float('nan')}, {'ask': 1.1}, {'ask': .9}, {'bidSize': 0},
                    {'askSize': 1}, {'volume24h': 2}, {'status': 'closed'}):
            s = state()
            s['instruments'][0]['reference'].update(bad)
            self.assertEqual(ReferenceValue().quote(s), [], bad)

    def test_malformed_crossed_or_negative_depth_rejected(self):
        for bid in (float('nan'), .8, -1):
            s = state()
            s['instruments'][0]['book']['bids'][0]['price'] = bid
            self.assertEqual(ReferenceValue().quote(s), [])

    def test_signed_positions_ignore_option_label(self):
        a = state()['account']
        a['positions'] = [{'exchangeId': '10', 'option': 'YES', 'quantity': -100, 'costBasis': 40}]
        total, races, shares, occupied = account_risk(a, {'10': 'r1'})
        self.assertEqual((total, races['r1'], shares['10']), (40, 40, 100))
        self.assertIn('10', occupied)

    def test_pending_order_collateral_and_duplicate_exposure(self):
        s = state()
        s['account']['orders'] = [{'exchangeId': '10', 'open': True, 'side': 'yes', 'action': 'sell',
                                   'quantity': 100, 'priceLimit': .80}]
        risk = account_risk(s['account'], s['raceByExchange'])
        self.assertAlmostEqual(risk[0], 20)
        self.assertEqual(ReferenceValue().quote(s), [])

    def test_account_race_and_unknown_race_caps_include_existing_positions(self):
        for eid, cost, mapping in (('11', 500, {'11': 'r1'}), ('11', 500, {}),
                                   ('11', 20000, {'11': 'r2'})):
            s = state()
            s['raceByExchange'].update(mapping)
            s['account']['positions'] = [{'exchangeId': eid, 'quantity': 1000, 'costBasis': cost}]
            self.assertEqual(ReferenceValue().quote(s), [])

    def test_invalid_account_is_not_treated_as_flat(self):
        for bad in ({'positions': None}, {'cash': float('nan')}, {'orders': [{}]}):
            s = state()
            s['account'].update(bad)
            self.assertEqual(ReferenceValue().evaluate(s)['skipped'], {'invalid_account': 1})

    def test_combined_order_reservations_respect_cash_and_race(self):
        s = state()
        s['paperCash'] = 40
        s['instruments'].append(instrument('11'))
        intents = ReferenceValue(ValueConfig(max_race_capital=30)).quote(s)
        self.assertLessEqual(sum(i['quantity']*(i['price']+.005) for i in intents), 30)

    def test_cash_reserved_for_orders_on_other_exchanges(self):
        s = state()
        s['account']['cash'] = 50
        s['raceByExchange']['11'] = 'r2'
        s['account']['orders'] = [{'exchangeId': '11', 'open': True, 'side': 'yes',
                                   'action': 'buy', 'quantity': 100, 'priceLimit': .5}]
        self.assertEqual(ReferenceValue().quote(s), [])

    def test_off_tick_rounding_does_not_overspend(self):
        s = state()
        s['paperCash'] = 10
        s['instruments'][0]['book']['asks'] = [{'price': .5001, 'quantity': 100}]
        intents = ReferenceValue().quote(s)
        self.assertLessEqual(sum(i['quantity']*(i['price']+.005) for i in intents), 10)

    def test_duplicate_books_do_not_duplicate_depth(self):
        s = state()
        s['instruments'] *= 2
        self.assertEqual(len(ReferenceValue().quote(s)), 1)

    def test_paper_exit_only_when_price_exceeds_upper_reference(self):
        s = state()
        s['paperPositions'] = {'10': {'side': 'yes', 'quantity': 20, 'cost': 10, 'raceKey': 'r1'}}
        self.assertEqual(ReferenceValue().quote(s), [])
        s['instruments'][0]['book'].update(bids=[{'price': .80, 'quantity': 10}], asks=[])
        intent, = ReferenceValue().quote(s)
        self.assertEqual((intent['action'], intent['quantity']), ('sell', 10))

    def test_no_exit_of_live_account_position(self):
        s = state()
        s['account']['positions'] = [{'exchangeId': '10', 'quantity': 20, 'costBasis': 10}]
        s['instruments'][0]['book'].update(bids=[{'price': .8, 'quantity': 100}], asks=[])
        self.assertEqual(ReferenceValue().quote(s), [])

    def test_bad_config_rejected(self):
        for kwargs in ({'fee': float('nan')}, {'min_edge': -.1}, {'kelly_fraction': 2},
                       {'max_orders': 1.5}, {'max_shares': True}):
            with self.assertRaises(ValueError):
                ValueConfig(**kwargs)


class PaperValueTests(unittest.TestCase):
    def test_evaluation_counts_errors_and_does_not_claim_validation(self):
        summary = summarize([{'completedAt': NOW, 'phase': 'error', 'errors': ['network']}])
        self.assertEqual(summary['cyclesWithErrors'], 1)
        self.assertEqual(summary['successfulCycles'], 0)
        self.assertFalse(summary['liveValidated'])

    def test_round_trip_and_partial_exit_accounting(self):
        s, p, cfg = state(), new_portfolio(2000), ValueConfig()
        intent, = ReferenceValue().quote(s)
        book = {'10': s['instruments'][0]['book']}
        entry = simulate(p, [intent], book, NOW, cfg)[0]
        q = entry['quantity']
        self.assertAlmostEqual(p['cash'], 2000-q*.505)
        book['10'].update(bids=[{'price': .8, 'quantity': 3}], asks=[])
        sell = dict(intent, action='sell', price=.8)
        exit_row = simulate(p, [sell], book, NOW, cfg)[0]
        self.assertEqual(exit_row['quantity'], 3)
        self.assertAlmostEqual(p['positions']['10']['cost'], (q-3)*.505)
        self.assertAlmostEqual(p['realizedPnl'], 3*(.8-.005-.505))
        self.assertFalse(exit_row['actualFill'])

    def test_stale_and_insufficient_liquidation_are_unknown(self):
        p = new_portfolio(2000)
        p['positions']['10'] = {'side': 'no', 'quantity': 100, 'cost': 30, 'raceKey': 'r1'}
        missing = liquidate(p, {}, NOW, ValueConfig())
        self.assertIsNone(missing['liquidationEquity'])
        book = instrument()['book']
        book['asks'][0]['quantity'] = 5
        partial = liquidate(p, {'10': book}, NOW, ValueConfig())
        self.assertIsNone(partial['liquidationPnl'])
        self.assertEqual(partial['insufficientDepth'], ['10'])

    def test_store_restart_and_duplicate_cycle_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp)/'history.sqlite3', 2000)
            p = store.load()
            p['cash'] = 1900
            cycle = {'id': 'one', 'completedAt': NOW}
            store.commit(p, cycle)
            p['cash'] = 1800
            with self.assertRaises(sqlite3.IntegrityError):
                store.commit(p, cycle)
            self.assertEqual(store.load()['cash'], 1900)
            store.db.close()
            restarted = PaperStore(Path(tmp)/'history.sqlite3', 999)
            self.assertEqual(restarted.load()['initialCash'], 2000)
            self.assertEqual(restarted.load()['cash'], 1900)
            restarted.db.close()

    def test_stale_status_hides_intents(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'status.json'
            p.write_text(json.dumps({'completedAt': '2000-01-01T00:00:00+00:00',
                                     'phase': 'running', 'decision': {'intents': [1]}}))
            self.assertEqual(read_status(tmp)['decision']['intents'], [])

    def test_tournament_bounds_strict(self):
        t = {'status': 'active', 'startDate': '2026-10-01T16:00:00Z', 'endDate': '2026-11-04T17:00:00Z'}
        self.assertTrue(tournament_open(t, '2026-10-02T00:00:00Z'))
        self.assertFalse(tournament_open(t, t['endDate']))
        self.assertFalse(tournament_open(dict(t, status='closed'), '2026-10-02T00:00:00Z'))

    def test_drawdown_brake_blocks_new_entries(self):
        class Collector:
            def collect(self, paper, config):
                s = state()
                s.update(startedAt=NOW, books={'10': s['instruments'][0]['book']}, coverage={}, errors=[],
                         limitations=[], tournament={'status': 'active', 'startDate': '2020-01-01T00:00:00Z',
                                                      'endDate': '2099-01-01T00:00:00Z'})
                s['account']['pnl'] = {}
                s['paperCash'] = paper['cash']
                return s
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp)/'test.db', 2000)
            paper = store.load()
            paper['cash'] = 1800
            store.commit(paper, {'id': 'seed', 'completedAt': NOW})
            result = run_cycle(Collector(), store, ValueConfig(), 100)
            self.assertTrue(result['paper']['entryHalted'])
            self.assertEqual(result['assumedExecutions'], [])
            store.db.close()


class CollectorValueTests(unittest.TestCase):
    def test_own_opposite_side_orders_are_removed_from_depth(self):
        book = dict(instrument()['book'], exchangeId='10')
        order = {'exchangeId': '10', 'open': True, 'side': 'no', 'action': 'buy',
                 'priceLimit': .5, 'quantity': 80}
        clean = exclude_own_liquidity(book, [order])
        self.assertEqual(clean['asks'][0]['quantity'], 20)
        self.assertEqual(book['asks'][0]['quantity'], 100)
        order.update(side='no', action='sell', priceLimit=.51, quantity=150)
        clean = exclude_own_liquidity(book, [order])
        self.assertEqual(clean['bids'], [])
        self.assertIsNone(clean['bestBid'])

    def test_chamber_and_party_mismatches_excluded(self):
        m = {'title': 'Will the Republican Party win the Arizona Governor?', 'exchanges': [{'id': '1'}]}
        node = {'root': {'node_type': 'contract', 'contract_details': {
            'resolutionType': 'Party Winner', 'electionDate': '2026-11-03', 'raceStage': 'General',
            'raceId': '1', 'stageId': '2', 'winnerName': 'Republican Party'}}}
        self.assertEqual(contract_identity(m, node)['ticker'], 'GOVPARTYAZ-26-R')
        node['root']['contract_details']['winnerName'] = 'Democratic Party'
        self.assertIsNone(contract_identity(m, node))
        self.assertIsNone(contract_identity(m, {'root': {'node_type': 'freeform'}}))

    def test_reference_pagination_and_no_unrequested_tickers(self):
        calls = []
        def get(path, **params):
            calls.append(params)
            if 'cursor' not in params:
                return {'markets': [{'ticker': 'UNREQUESTED', 'status': 'active'}], 'cursor': 'next'}
            return {'markets': [{'ticker': 'SENATETX-26-D', 'status': 'active'}], 'cursor': ''}
        collector = ValueCollector(object(), reference_get=get)
        refs, raw, errors, count = collector.references([{'title': 'Will the Democratic Party win the Texas Senate?'}])
        self.assertEqual(set(refs), {'SENATETX-26-D'})
        self.assertEqual(calls[1]['cursor'], 'next')
        self.assertEqual(errors, [])

    def test_partial_reference_response_not_reused_on_failure(self):
        def get(path, **params):
            return {'markets': [{'ticker': 'SENATETX-26-D', 'status': 'active'}], 'cursor': 'repeat'}
        collector = ValueCollector(object(), reference_get=get)
        refs, raw, errors, _ = collector.references([{'title': 'Will the Democratic Party win the Texas Senate?'}])
        self.assertEqual(refs, {})
        self.assertTrue(errors)


if __name__ == '__main__':
    unittest.main()
