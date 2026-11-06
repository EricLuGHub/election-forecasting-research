"""E6 shadow runner and persistent counterfactual taker portfolio.

Only GET requests are made. There is deliberately no --live option: provisional
contract mappings and the legacy shared execution lifecycle need validation.
Paper purchases assume the observed depth remains available; these are not fills.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import sqlite3
import threading
import uuid

from .client import Client, ROOT
from .e6data import ValueCollector, utc
from .engines.engine6_value import ReferenceValue, ValueConfig, fresh, levels, number
from .monitor import atomic_json, instance_lock

DIRECTORY = ROOT / 'data/e6'


def new_portfolio(cash):
    if number(cash) <= 0:
        raise ValueError('Paper starting cash must be positive')
    return {'initialCash': cash, 'cash': cash, 'positions': {}, 'realizedPnl': 0.0,
            'assumedExecutions': 0, 'highWaterEquity': cash, 'entryHalted': False}


def liquidate(portfolio, books, now, config):
    """Mark to sellable depth. Missing/depleted books never become optimistic marks."""
    proceeds, missing, partial = 0.0, [], []
    for eid, pos in portfolio['positions'].items():
        book = books.get(eid, {})
        if not fresh(book, now, config.max_book_age):
            missing.append(eid)
            continue
        try:
            depth = levels(book, pos['side'], 'sell')
        except (ValueError, KeyError, TypeError):
            missing.append(eid)
            continue
        left = pos['quantity']
        for price, qty in depth:
            take = min(left, int(qty))
            proceeds += take*max(0, price-config.fee-config.slippage)
            left -= take
            if not left:
                break
        if left:
            partial.append(eid)
    floor = portfolio['cash']+proceeds
    complete = not missing and not partial
    equity = round(floor, 6) if complete else None
    return {'liquidationEquity': equity,
            'liquidationPnl': round(equity-portfolio['initialCash'], 6) if complete else None,
            'cashPlusVisibleLiquidation': round(floor, 6),
            'missingBooks': missing, 'insufficientDepth': partial,
            'openPositions': len(portfolio['positions']), 'cash': round(portfolio['cash'], 6),
            'realizedPnl': round(portfolio['realizedPnl'], 6),
            'assumedExecutions': portfolio['assumedExecutions']}


def simulate(portfolio, intents, books, now, config):
    """Counterfactual taker sweep at observed depth, with explicit cost stress.

    No credit for quote touches, future prices, or hypothetical maker fills.
    Cost stress is a separate debit, not a fill outside the order limit.
    """
    executions = []
    for intent in intents:
        eid, side, action = intent['exchangeId'], intent['side'], intent['action']
        book = books.get(eid, {})
        if not fresh(book, now, config.max_book_age):
            continue
        position = portfolio['positions'].get(eid)
        if action == 'buy' and (position or portfolio['entryHalted']):
            continue
        if action == 'sell' and (not position or position['side'] != side):
            continue
        target = intent['quantity']
        if action == 'sell':
            target = min(target, position['quantity'])
        qty, value = 0, 0.0
        for price, available in levels(book, side, action):
            if (action == 'buy' and price > intent['price']+1e-9
                    or action == 'sell' and price < intent['price']-1e-9):
                break
            take = min(int(available), target-qty)
            if action == 'buy':
                cash_left = portfolio['cash']-value-qty*(config.fee+config.slippage)
                take = min(take, max(0, int((cash_left+1e-9)/(price+config.fee+config.slippage))))
            if take > 0:
                qty += take
                value += take*price
            if qty >= target:
                break
        if not qty:
            continue
        stress = qty*(config.fee+config.slippage)
        if action == 'buy':
            cost = value+stress
            portfolio['cash'] -= cost
            portfolio['positions'][eid] = {'quantity': qty, 'side': side, 'cost': cost,
                                           'raceKey': intent['raceKey'], 'title': intent['title'],
                                           'enteredAt': now, 'referenceTicker': intent['referenceTicker']}
            realized = None
        else:
            cost = position['cost']*qty/position['quantity']
            realized = value-stress-cost
            portfolio['cash'] += value-stress
            portfolio['realizedPnl'] += realized
            position['quantity'] -= qty
            position['cost'] -= cost
            if not position['quantity']:
                del portfolio['positions'][eid]
        portfolio['assumedExecutions'] += 1
        executions.append({'exchangeId': eid, 'side': side, 'action': action, 'quantity': qty,
                           'observedVwap': value/qty, 'costStress': stress,
                           'realizedPnl': realized, 'actualFill': False,
                           'assumption': 'Observed depth remains available to a hypothetical taker.'})
    return executions


class PaperStore:
    """One transaction commits cycle evidence and portfolio, preventing double replay."""
    def __init__(self, path, cash):
        self.db = sqlite3.connect(path)
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cycles (id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS cycles_at ON cycles(at);
        ''')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO portfolio VALUES(1, ?)',
                            (json.dumps(new_portfolio(cash)),))

    def load(self):
        return json.loads(self.db.execute('SELECT payload FROM portfolio WHERE id=1').fetchone()[0])

    def commit(self, portfolio, cycle):
        with self.db:
            self.db.execute('INSERT INTO cycles VALUES(?,?,?)',
                            (cycle['id'], cycle['completedAt'], json.dumps(cycle, allow_nan=False)))
            self.db.execute('UPDATE portfolio SET payload=? WHERE id=1',
                            (json.dumps(portfolio, allow_nan=False),))
            self.db.execute("DELETE FROM cycles WHERE at < strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')")


def tournament_open(tournament, now):
    try:
        current = datetime.fromisoformat(now.replace('Z', '+00:00'))
        start = datetime.fromisoformat(tournament['startDate'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(tournament['endDate'].replace('Z', '+00:00'))
        return tournament['status'] in ('open', 'active') and start <= current < end
    except (ValueError, KeyError, TypeError):
        return False


def run_cycle(collector, store, config, max_drawdown):
    paper = store.load()
    state = collector.collect(paper, config)
    before = liquidate(paper, state['books'], state['now'], config)
    equity = before['liquidationEquity']
    if equity is not None:
        paper['highWaterEquity'] = max(paper['highWaterEquity'], equity)
        if paper['highWaterEquity']-equity >= max_drawdown:
            paper['entryHalted'] = True
    result = ReferenceValue(config).evaluate(state)
    if not tournament_open(state['tournament'], state['now']):
        result['intents'] = []
        result['skipped']['tournament_closed'] = 1
    # Incomplete liquidation marks cannot establish remaining risk capacity.
    if equity is None or paper['entryHalted']:
        result['intents'] = [i for i in result['intents'] if i['action'] == 'sell']
        result['skipped']['paper_drawdown_or_unknown_liquidation'] = 1
    executions = simulate(paper, result['intents'], state['books'], state['now'], config)
    mark = liquidate(paper, state['books'], state['now'], config)
    # Apply the brake immediately after a new assumed fill too.
    if mark['liquidationEquity'] is not None and paper['highWaterEquity']-mark['liquidationEquity'] >= max_drawdown:
        paper['entryHalted'] = True
    status = {'id': uuid.uuid4().hex, 'engine': 'E6', 'mode': 'shadow', 'phase': 'running',
              'startedAt': state['startedAt'], 'completedAt': utc(),
              'executionEligible': False, 'coverage': state['coverage'], 'errors': state['errors'],
              'screening': state.get('screening', {}),
              'accountPnl': state['account']['pnl'], 'decision': result,
              'paper': dict(mark, entryHalted=paper['entryHalted'],
                            initialCash=paper['initialCash'], maxDrawdown=max_drawdown),
              'assumedExecutions': executions, 'limitations': state['limitations'] + [
                  'Paper results assume fills at observed depth; they do not demonstrate live profitability.',
                  'All mappings remain provisional; E6 has no live submission route.']}
    # Full inputs are archived for reproducibility, including both settlement texts.
    store.commit(paper, dict(status, inputs=state))
    return status


def read_status(directory=DIRECTORY):
    path = Path(directory) / 'status.json'
    if not path.exists():
        return {'engine': 'E6', 'mode': 'shadow', 'phase': 'never_started', 'executionEligible': False}
    status = json.loads(path.read_text())
    try:
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(status['completedAt'])).total_seconds()
        status['ageSeconds'] = round(age, 1)
        status['stale'] = age < 0 or age > status.get('staleAfterSeconds', 180)
    except (KeyError, TypeError, ValueError):
        status['stale'] = True
    if status['stale'] or status.get('phase') != 'running':
        status.get('decision', {})['intents'] = []
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'status'), nargs='?', default='run')
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--slug', default='midterm-elections')
    parser.add_argument('--cycles', type=int, default=1, help='0 runs until interrupted; default one scan')
    parser.add_argument('--interval', type=float, default=60)
    parser.add_argument('--max-books', type=int, default=12, help='New candidates; held paper positions always refreshed')
    parser.add_argument('--paper-cash', type=float, default=2000)
    parser.add_argument('--max-drawdown', type=float, default=100)
    parser.add_argument('--uncertainty', type=float, default=0.03)
    parser.add_argument('--min-edge', type=float, default=0.02)
    parser.add_argument('--fee', type=float, default=0)
    parser.add_argument('--slippage', type=float, default=0.005)
    args = parser.parse_args()
    if args.command == 'status':
        print(json.dumps(read_status(args.directory), indent=2))
        return
    try:
        if args.cycles < 0 or args.max_books < 1 or number(args.interval) < 10 or number(args.max_drawdown) <= 0:
            raise ValueError('Require cycles >= 0, books >= 1, interval >= 10 and drawdown > 0')
        new_portfolio(args.paper_cash)
        config = ValueConfig(uncertainty=args.uncertainty, min_edge=args.min_edge,
                             fee=args.fee, slippage=args.slippage)
    except ValueError as exc:
        parser.error(str(exc))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with instance_lock(args.directory):
        collector = ValueCollector(Client(), args.slug, args.max_books)
        store = PaperStore(args.directory / 'history.sqlite3', args.paper_cash)
        cycle = 0
        try:
            while not stop.is_set() and (args.cycles == 0 or cycle < args.cycles):
                try:
                    status = run_cycle(collector, store, config, args.max_drawdown)
                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                    status = {'id': uuid.uuid4().hex, 'engine': 'E6', 'mode': 'shadow', 'phase': 'error',
                              'completedAt': utc(), 'executionEligible': False,
                              'errors': [{'error': str(exc)[:400]}], 'decision': {'intents': []}}
                    store.commit(store.load(), status)
                status['staleAfterSeconds'] = max(180, args.interval*3)
                atomic_json(args.directory / 'status.json', status)
                print(json.dumps({k: status.get(k) for k in ('completedAt', 'phase', 'coverage', 'paper', 'errors')}), flush=True)
                cycle += 1
                if args.cycles == 0 or cycle < args.cycles:
                    stop.wait(args.interval)
        finally:
            store.db.close()
            if stop.is_set():
                status = read_status(args.directory)
                status.update(phase='stopped')
                status.get('decision', {})['intents'] = []
                atomic_json(args.directory / 'status.json', status)


if __name__ == '__main__':
    main()
