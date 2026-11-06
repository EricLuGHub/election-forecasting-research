"""E7 durable passive-entry pilot, real fills only; paper/default never submits.

One bounded entry while flat, then close the attributable inventory. Entries
require an expiring permit in the shared executor. No automatic size increases.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import signal
import threading
import time
import uuid

from .client import ROOT
from .e6data import contract_identity, exclude_own_liquidity
from .engines.engine7_maker import entry, exit_order, fill_accounting, liquidation_value, reference
from .execution import Executor
from .external import event_for_title, public_get
from .monitor import atomic_json, instance_lock
from .pilot import PREFIX, instant, mode, opening_proof, trial_scope, verify_baseline
from .risk import cost_ceiling, finite, inventory, is_reduction

DIRECTORY = ROOT/'data/e7'


def utc():
    return datetime.now(timezone.utc).isoformat()


def recent_fills(client, since, slug='midterm-elections'):
    result, seen, cursor = [], set(), None
    for _ in range(20):
        page = client.get(f'/tournaments/{slug}/portfolio/fills', limit=200, cursor=cursor)
        if not page.get('coverage', {}).get('complete'):
            raise ValueError('Fill reporting coverage incomplete')
        rows = page['data']
        dates = [instant(r['filledAt']) for r in rows]
        if dates != sorted(dates, reverse=True):
            raise ValueError('Fill history not newest-first')
        result.extend(r for r in rows if instant(r['filledAt']) >= instant(since))
        if not page['pagination']['hasMore'] or dates and dates[-1] < instant(since):
            return result
        cursor = page['pagination']['nextCursor']
        if not cursor or cursor in seen:
            raise ValueError('Missing or repeated fill cursor')
        seen.add(cursor)
    raise ValueError('Fill history exceeds bounded reconciliation window')


class Runner:
    def __init__(self, executor, directory=DIRECTORY, reference_get=public_get, stopping=None):
        self.exe, self.directory, self.reference_get = executor, Path(directory), reference_get
        self.config = json.loads((self.directory/'config.json').read_text())
        self.prefix = self.config['prefix']
        self.rotation = 0
        self.stopping = stopping or (lambda: False)
        if self.config.get('version') == 2:
            trial_scope(self.config)
        elif self.prefix != PREFIX:
            raise ValueError('Wrong pilot prefix')
        if self.config['slug'] != executor.slug:
            raise ValueError('Wrong pilot configuration')

    def log(self, event, **data):
        with (self.directory/'events.jsonl').open('a') as handle:
            handle.write(json.dumps(dict(at=utc(), event=event, **data), allow_nan=False)+'\n')

    def status(self, **data):
        result = dict(at=utc(), mode='live_pilot' if not self.exe.dry_run else 'paper_preview',
                      strategyValidated=False, **data)
        atomic_json(self.directory/'status.json', result)
        return result

    def cancel_owned(self, account=None):
        owned = self.exe.owned_ids(self.prefix)
        if not owned:
            return
        orders = account['openOrders'] if account is not None else self.exe.open_orders()
        for order in orders:
            if int(order['id']) in owned:
                result = self.exe.cancel_order(order['id'])
                self.log('cancel', orderId=order['id'], result=result)

    def halt_entries(self, reason):
        path = self.directory/'halt.json'
        if not path.exists():
            atomic_json(path, {'at': utc(), 'reason': reason})

    def cycle(self):
        cfg, exe = self.config, self.exe
        t = exe.preflight()
        account = exe.reconcile(include_pnl=False)
        fills = recent_fills(exe.client, cfg['startedAt'], exe.slug)
        journal = exe.journal()
        ledger = fill_accounting(fills, journal, cfg['exchanges'], cfg['startedAt'], self.prefix)
        atomic_json(self.directory/'fills.json', {'at': utc(), 'fills': fills, 'accounting': ledger})
        quantities = inventory(account['positions']['positions'])
        reserved, scopes = set(cfg['reservedExchangeIds']), cfg['exchanges']
        if any(quantities.get(eid, 0) != ledger['signedInventory'].get(eid, 0) for eid in scopes):
            self.cancel_owned(account)
            return self.status(phase='reconciliation_wait', reason='Positions and fill ledger differ',
                               accounting=ledger, actualInventory={e: quantities.get(e, 0) for e in scopes})
        baseline = verify_baseline(cfg, quantities)
        owned = exe.owned_ids(self.prefix)
        if any(str(o['exchangeId']) in reserved and int(o['id']) not in owned for o in account['openOrders']):
            raise ValueError('Foreign pending order in reserved race')
        if any(r['status'] != 'confirmed' for k, r in journal.items() if k.startswith(self.prefix)):
            raise ValueError('Ambiguous pilot placement')
        permit = mode(exe.recovery_path).get('openingPermit', {})
        if exe.dry_run and cfg.get('version') == 2:
            permit = dict(cfg, entryEnabled=True)
        if permit and permit.get('prefix') != self.prefix:
            raise ValueError('Opening permit belongs to another run')
        if exe.dry_run and not permit:
            permit = dict(cfg, version=1, entryEnabled=True, maxCapital=cfg['maxCapital'])
        observations, liquidation = {}, ledger['cashFlow']
        for eid, spec in scopes.items():
            # Reference failure blocks entries, but cannot prevent inventory exits.
            observation = {'startedAt': utc()}
            try:
                raw = self.reference_get('/markets/'+spec['ticker'])['market']
                if raw['ticker'] != spec['ticker']:
                    raise ValueError('Wrong reference ticker')
                reference(raw, spec['side'])
                observation['reference'] = raw
                observation['referenceAt'] = utc()
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                observation['referenceError'] = str(exc)[:300]
            book_started = time.monotonic()
            raw_book = exe.client.get(f'/exchanges/{eid}/orderbook', tournamentId=t['id'], depth=50)
            if str(raw_book['exchangeId']) != eid or str(raw_book['marketId']) != spec['marketId']:
                raise ValueError('Wrong SIG book identity')
            observation.update(book=exclude_own_liquidity(raw_book, account['openOrders']),
                               bookAt=utc(), bookStartedMonotonic=book_started)
            value, residual = liquidation_value(observation['book'], spec['side'], abs(quantities.get(eid, 0)))
            liquidation += value
            observation['unpricedInventory'] = residual
            observations[eid] = observation
        atomic_json(self.directory/'latest-inputs.json', {'at': utc(), 'observations': observations,
                    'account': account, 'accounting': ledger})
        with (self.directory/'observations.jsonl').open('a') as handle:
            handle.write(json.dumps({'at': utc(), 'observations': observations, 'accounting': ledger},
                                    allow_nan=False)+'\n')
        if liquidation <= -cfg['lossStop']:
            self.halt_entries('Executable liquidation P&L breached pilot stop')
        disabled = (self.stopping() or (self.directory/'halt.json').exists()
                    or (self.directory/'health-halt.json').exists()
                    or (self.directory/'stop.request').exists()
                    or not permit.get('entryEnabled')
                    or datetime.now(timezone.utc) >= instant(permit.get('expiresAt', cfg['expiresAt'])))
        plans, held = [], []
        ids = list(scopes)
        ids = ids[self.rotation % len(ids):]+ids[:self.rotation % len(ids)]
        self.rotation += 1
        # Inventory exits and outstanding orders take priority over new entries.
        ids.sort(key=lambda e: (not bool(quantities.get(e)), not any(str(o['exchangeId']) == e for o in account['openOrders'])))
        elapsed = (datetime.now(timezone.utc)-instant(cfg['startedAt'])).total_seconds()
        variant = ('join' if int(elapsed//300) % 2 == 0 else 'improve') if cfg.get('compareQuotes') else 'improve'
        for eid in ids:
            spec = scopes[eid]
            observation, quantity = observations[eid], abs(quantities.get(eid, 0))
            book, ref = observation['book'], observation.get('reference')
            orders = [o for o in account['openOrders'] if str(o['exchangeId']) == eid]
            lots = ledger['lots'].get(eid, [])
            old = bool(lots and (datetime.now(timezone.utc)-instant(lots[0]['at'])).total_seconds() >= cfg['maxHoldSeconds'])
            if len(orders) > 1:
                raise ValueError('Multiple pending orders in pilot instrument')
            if orders:
                order = orders[0]
                original_row = next(r for k, r in journal.items() if k.startswith(self.prefix)
                                    and str((r.get('response') or {}).get('orderId')) == str(order['id']))
                original = original_row['body']
                invalid = False
                if original['action'] == 'buy':
                    invalid = disabled or quantity > 0 or not ref
                    if ref and reference(ref, spec['side'])[0]-finite(order['priceLimit']) < cfg.get('referenceBuffer', .035)-1e-9:
                        invalid = True
                else:
                    others = [o for o in account['openOrders'] if o['id'] != order['id']]
                    invalid = (not is_reduction(order, account['positions']['positions'], others)
                               or ((old or disabled) and not (original_row.get('riskProof') or {}).get('urgent')))
                if invalid:
                    exe.cancel_order(order['id'])
                    self.log('cancel_reconcile', orderId=order['id'])
                else:
                    held.append(order['id'])
                # Never cancel-and-replace on an old inventory snapshot.
                continue
            # Reading several markets can be slow. Refresh this order's book
            # immediately before planning; never submit from the first stale book.
            if time.monotonic()-observation['bookStartedMonotonic'] > 20:
                book_started = time.monotonic()
                raw_book = exe.client.get(f'/exchanges/{eid}/orderbook', tournamentId=t['id'], depth=50)
                if str(raw_book['exchangeId']) != eid or str(raw_book['marketId']) != spec['marketId']:
                    raise ValueError('Wrong refreshed book identity')
                book = exclude_own_liquidity(raw_book, account['openOrders'])
                observation.update(book=book, bookAt=utc(), bookStartedMonotonic=book_started)
            if quantity:
                pos = next(p for p in account['positions']['positions'] if str(p['exchangeId']) == eid)
                proposal = exit_order(book, spec['side'], quantity, cost_ceiling(pos), urgent=old or disabled)
            else:
                proposal = entry(book, spec['side'], ref, spec['maxShares'],
                                 cfg.get('referenceBuffer', .035), cfg.get('minSpread', .02), variant) if ref and not disabled else None
                if proposal and cfg.get('minExitDepth'):
                    _, missing = liquidation_value(book, spec['side'], cfg['minExitDepth'])
                    if missing:
                        proposal = None
            if not proposal:
                continue
            evidence = proposal.pop('evidence')
            order = dict(proposal, tournamentId=t['id'], idempotencyKey=self.prefix+uuid.uuid4().hex,
                         expirationDate=(datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat())
            urgent = proposal['action'] == 'sell' and (old or disabled)
            if proposal['action'] == 'buy':
                order['expirationDate'] = min(instant(order['expirationDate']), instant(permit['expiresAt'])).isoformat()

            def guard(fresh):
                if self.stopping():
                    raise RuntimeError('Stopping; no new submission')
                if time.monotonic()-observation['bookStartedMonotonic'] > 45:
                    raise ValueError('Book aged beyond 45 seconds in preflight')
                actual = inventory(fresh['positions']['positions'])
                if any(actual.get(e, 0) != ledger['signedInventory'].get(e, baseline.get(e, 0)) for e in reserved):
                    raise ValueError('Inventory changed during preflight')
                race_ids = set(spec.get('raceExchangeIds', reserved))
                if any(str(o['exchangeId']) in race_ids or (str(o['exchangeId']) in reserved and int(o['id']) not in owned)
                       for o in fresh['openOrders']):
                    raise ValueError('Pending order raced pilot preflight')
                if order['action'] == 'sell':
                    if not is_reduction(order, fresh['positions']['positions'], fresh['openOrders']):
                        raise ValueError('Pilot exit is not inventory-backed')
                    return dict(evidence, attributedInventory=actual.get(eid), urgent=urgent)
                if any((self.directory/name).exists() for name in ('halt.json', 'stop.request', 'health-halt.json')):
                    raise ValueError('Pilot entries halted')
                if (datetime.now(timezone.utc)-instant(observation['referenceAt'])).total_seconds() > 120:
                    raise ValueError('Reference aged during preflight')
                if any(actual.get(e, 0) and time.monotonic()-o['bookStartedMonotonic'] > 90 for e, o in observations.items()):
                    raise ValueError('Inventory risk marks aged during preflight')
                current_permit = permit if exe.dry_run else mode(exe.recovery_path)['openingPermit']
                return dict(evidence, **opening_proof(order, fresh, current_permit))

            guard(account)
            result = exe.submit_single(order, reduce_only=order['action'] == 'sell', guard=guard)
            plans.append({'order': order, 'result': result, 'evidence': evidence, 'urgent': urgent})
            self.log('preview' if exe.dry_run else 'submit', **plans[-1])
            break  # fresh account and fill reconciliation before the next order
        return self.status(phase='entries_halted' if disabled else 'running', heldOrders=held,
                           proposals=plans, accounting=ledger, liquidationGross=round(liquidation, 6),
                           configuredMaxCapital=permit.get('maxCapital'), expiresAt=cfg['expiresAt'], quoteVariant=variant)


def initialize(executor, directory, snapshot, exchange_id, side, shares=100, capital=100, hours=4):
    directory = Path(directory)
    if (directory/'config.json').exists():
        raise ValueError('Pilot already initialized; do not reset its history or deadline')
    if not 1 <= shares <= 100 or not 0 < capital <= 100 or not 0 < hours <= 4:
        raise ValueError('Initial pilot limited to 100 shares/capital and four hours')
    snap = json.loads(Path(snapshot).read_text())
    market = next(m for m in snap['markets'] if any(str(e['id']) == exchange_id for e in m['exchanges']))
    mapping = event_for_title(market['title'])
    if not mapping or mapping[0].startswith('CONTROL'):
        raise ValueError('Unsupported pilot market')
    node = executor.client.get(f"/markets/{market['id']}/nodes")
    identity = contract_identity(market, node)
    if not identity:
        raise ValueError('Unverified pilot race identity')
    related = [m for m in snap['markets'] if (event_for_title(m['title']) or (None,))[0] == mapping[0]]
    reserved = []
    for sibling in related:
        sibling_node = node if sibling['id'] == market['id'] else executor.client.get(f"/markets/{sibling['id']}/nodes")
        other = contract_identity(sibling, sibling_node)
        if not other or other['raceKey'] != identity['raceKey']:
            raise ValueError('Cannot reserve exact same-race counterparts')
        reserved.extend(str(e['id']) for e in sibling['exchanges'])
    with executor.locked():
        t = executor.preflight()
        account = executor.reconcile(include_pnl=False)
        if t['id'] != snap['tournament']['id']:
            raise ValueError('Wrong snapshot tournament')
        if any(inventory(account['positions']['positions']).get(e) for e in reserved):
            raise ValueError('Pilot requires an entirely flat race')
        if any(str(o['exchangeId']) in reserved for o in account['openOrders']):
            raise ValueError('Pilot race has pending orders')
        recovery = mode(executor.recovery_path)
        if recovery.get('openingPermit'):
            raise ValueError('Do not overwrite an existing opening permit')
        start = datetime.now(timezone.utc)
        config = {'version': 1, 'prefix': PREFIX, 'slug': executor.slug, 'startedAt': start.isoformat(),
                  'expiresAt': (start+timedelta(hours=hours)).isoformat(),
                  'maxCapital': capital,
                  'reservedExchangeIds': reserved, 'lossStop': 10, 'maxHoldSeconds': 1800,
                  'exchanges': {exchange_id: {'side': side, 'maxShares': shares, 'marketId': str(market['id']),
                                             'ticker': identity['ticker'], 'raceKey': identity['raceKey']}}}
        atomic_json(directory/'config.json', config)
        atomic_json(directory/'baseline.json', {'at': utc(), 'account': account, 'node': node})
        if not executor.dry_run:
            permit = dict(version=1, prefix=PREFIX, entryEnabled=True, maxCapital=capital,
                          expiresAt=config['expiresAt'], exchanges=config['exchanges'], reservedExchangeIds=reserved)
            atomic_json(executor.recovery_path, dict(recovery, reduceOnly=True, openingPermit=permit))
        return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'run'], nargs='?', default='run')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--snapshot', type=Path, default=ROOT/'data/top20/opportunity-snapshot.json')
    parser.add_argument('--exchange', default='1004')
    parser.add_argument('--side', choices=['yes', 'no'], default='no')
    parser.add_argument('--cycles', type=int, default=0)
    parser.add_argument('--interval', type=float, default=30)
    args = parser.parse_args()
    if args.interval < 15 or args.cycles < 0:
        parser.error('Require interval >=15 and cycles >=0')
    exe = Executor(dry_run=not args.live, max_basket_capital=100, max_total_capital=20000)
    with instance_lock(args.directory):
        if args.command == 'init':
            print(json.dumps(initialize(exe, args.directory, args.snapshot, args.exchange, args.side)))
            return
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        runner = Runner(exe, args.directory, stopping=stop.is_set)
        cycle, failures = 0, 0
        try:
            while not stop.is_set():
                try:
                    result = runner.cycle()
                    failures = 0
                    print(json.dumps(result, allow_nan=False), flush=True)
                except (OSError, RuntimeError, ValueError, KeyError, TypeError, StopIteration) as exc:
                    failures += 1
                    runner.status(phase='error', error=str(exc)[:400], consecutiveFailures=failures)
                    runner.log('error', error=str(exc)[:400])
                    if args.live:
                        try:
                            runner.cancel_owned()
                        except Exception as cancel_exc:
                            runner.log('cancel_error', error=str(cancel_exc)[:300])
                cycle += 1
                if args.cycles and cycle >= args.cycles:
                    break
                stop.wait(min(300, args.interval*2**min(failures, 4)))
        finally:
            if args.live:
                runner.cancel_owned()
            runner.status(phase='stopped', cycles=cycle)


if __name__ == '__main__':
    main()
