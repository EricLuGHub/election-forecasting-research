"""E1 inventory recovery: bounded, cost-aware, hedge-preserving reductions only.

The unanchored spread chaser is retired. This runner never opens a position.
Paper is default; --live requires --reduce-only. Existing orders are retained
until expiry, not chased. Unknown contracts and races with foreign orders wait.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import signal
import threading
import time
import uuid

from .client import ROOT
from .e6data import exclude_own_liquidity
from .execution import Executor, TICK
from .monitor import atomic_json, instance_lock
from .pilot import reservations
from .risk import (cost_ceiling, economic_key, finite, floor_safe_quantity,
                   held_mark, inventory, is_reduction, race_groups, settlement_floor)

DIRECTORY = ROOT / 'data/recovery'
PREFIX = 'E1R-'


def utc():
    return datetime.now(timezone.utc).isoformat()


def log(event, **info):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with (DIRECTORY / 'events.jsonl').open('a') as handle:
        handle.write(json.dumps(dict(at=utc(), event=event, **info), allow_nan=False)+'\n')


def order_key(order):
    return economic_key(order)


def position_inventory(client, slug):
    # Read failures propagate. Unknown inventory is never treated as flat.
    return inventory(client.get(f'/tournaments/{slug}/portfolio/positions')['positions'])


def proposal(position, book, group, lot=25, min_gain=0.01):
    """A SELL of the held outcome, profitable even for the most expensive lot."""
    qty = int(position['quantity'])
    if not qty:
        return None
    side = 'yes' if qty > 0 else 'no'
    bids = [(finite(x['price']), finite(x['quantity'])) for x in book['bids']]
    asks = [(finite(x['price']), finite(x['quantity'])) for x in book['asks']]
    if any(not 0 < p < 1 or q <= 0 for p, q in bids+asks):
        raise ValueError('Malformed book')
    if side == 'no':
        bids, asks = [(1-p, q) for p, q in asks], [(1-p, q) for p, q in bids]
    bid = max(bids, default=(0, 0))
    ask = min(asks, default=(1, 0))
    if bid[0] >= ask[0]:
        raise ValueError('Crossed book')
    # Do not manufacture realized gains by dumping a winner below its current
    # account mark. A mark is not a fair-value forecast; this is a recovery guard.
    floor = math.ceil((max(cost_ceiling(position)+min_gain, held_mark(position))-1e-9)/TICK)*TICK
    if floor > 0.995+1e-9 or not asks and not bids:
        return None
    maximum = min(lot, abs(qty))
    if bid[0] >= floor-1e-9:
        price = bid[0]
        maximum = min(maximum, int(bid[1]))
    else:
        price = max(floor, bid[0]+TICK, ask[0]-TICK)
    price = round(math.ceil((price-1e-9)/TICK)*TICK, 3)
    if price > 0.995:
        return None
    maximum = floor_safe_quantity(group, position['exchangeId'], price, maximum)
    if maximum <= 0:
        return None
    return {'exchangeId': str(position['exchangeId']), 'side': side,
            'action': 'sell', 'quantity': maximum, 'price': price}


def check_reduction(order, account, nodes, min_gain=0.01, ignore_id=None, reserved=()):
    positions = account['positions']['positions']
    orders = [o for o in account['openOrders'] if str(o['id']) != str(ignore_id)]
    if order['action'] != 'sell' or not is_reduction(order, positions, orders):
        raise ValueError('Not an inventory-backed SELL')
    eid = str(order['exchangeId'])
    if eid in reserved:
        raise ValueError('Inventory reserved for another engine')
    groups, mapping = race_groups(positions, nodes)
    if eid not in mapping:
        raise ValueError('Unverified race relationship')
    group = groups[mapping[eid]]
    group_eids = {str(p['exchangeId']) for p in group}
    if any(str(o['exchangeId']) not in mapping and str(o['exchangeId']) not in reserved for o in orders):
        raise ValueError('Unmapped pending exposure: cannot verify race reservation')
    if any(str(o['exchangeId']) in group_eids for o in orders):
        raise ValueError('Another pending order reserves this race')
    pos = next(p for p in group if str(p['exchangeId']) == eid)
    if order['side'] != ('yes' if pos['quantity'] > 0 else 'no'):
        raise ValueError('Wrong held outcome')
    price = finite(order.get('priceLimit', order.get('price')))
    if not 0 < price < 1 or price+1e-9 < cost_ceiling(pos)+min_gain:
        raise ValueError('Below conservative lot cost plus profit buffer')
    if price+1e-9 < held_mark(pos):
        raise ValueError('Would sell below the current held-outcome mark')
    if floor_safe_quantity(group, eid, price, order['quantity']) < order['quantity']:
        raise ValueError('Would reduce the race settlement payout floor')
    return {'signedInventory': pos['quantity'], 'costCeiling': cost_ceiling(pos),
            'heldMark': held_mark(pos), 'raceFloorBefore': settlement_floor(group),
            'minimumGainPerShare': min_gain}


class RecoveryRunner:
    def __init__(self, executor, lot=25, max_markets=3, min_gain=0.01, nodes=None, stopping=None):
        self.exe, self.lot, self.max_markets, self.min_gain = executor, lot, max_markets, min_gain
        self.nodes = nodes
        self.stopping = stopping or (lambda: False)

    def definitions(self):
        if self.nodes is not None:
            return self.nodes
        data = json.loads((ROOT / 'data/monitor/metadata.json').read_text())
        if data['slug'] != self.exe.slug:
            raise ValueError('Wrong tournament metadata')
        return data['nodes']

    def cancel_owned(self):
        owned = self.exe.owned_ids(PREFIX)
        if not owned:
            return
        rows = self.exe.open_orders()
        for order in rows:
            if int(order['id']) in owned:
                result = self.exe.cancel_order(order['id'])
                log('cancel', orderId=order['id'], result=result)

    def cycle(self):
        start = utc()
        log('cycle_started', mode='paper' if self.exe.dry_run else 'live_reduce_only')
        tournament = self.exe.preflight()
        account, nodes = self.exe.reconcile(), self.definitions()
        reserved = reservations(self.exe.recovery_path)
        owned = self.exe.owned_ids(PREFIX)
        cancelled = []
        for order in account['openOrders']:
            if int(order['id']) not in owned:
                continue
            try:
                check_reduction(order, account, nodes, self.min_gain, order['id'], reserved)
            except (ValueError, KeyError, TypeError):
                result = self.exe.cancel_order(order['id'])
                cancelled.append(order['id'])
                log('cancel_unsafe', orderId=order['id'], result=result)
        if cancelled:
            account = self.exe.reconcile()
        held = [o for o in account['openOrders'] if int(o['id']) in owned]
        slots = max(0, self.max_markets-len(held))
        positions = account['positions']['positions']
        groups, mapping = race_groups(positions, nodes)
        busy = {mapping.get(str(o['exchangeId'])) for o in account['openOrders']}
        plans, skipped, reads = [], {}, 0
        ranked = sorted(positions, key=lambda p: finite(p.get('unrealizedPnl', 0)), reverse=True)
        for pos in ranked:
            eid = str(pos['exchangeId'])
            key = mapping.get(eid)
            if not slots or reads >= 12 or self.stopping():
                break
            if key is None or key in busy or eid in reserved:
                continue
            read_at = time.monotonic()
            raw = self.exe.client.get(f'/exchanges/{eid}/orderbook',
                                      tournamentId=tournament['id'], depth=50)
            reads += 1
            book = exclude_own_liquidity(dict(raw, exchangeId=eid), account['openOrders'])
            order = proposal(pos, book, groups[key], self.lot, self.min_gain)
            if not order:
                skipped[eid] = 'no_cost_and_hedge_safe_quote'
                continue
            order.update(tournamentId=tournament['id'], idempotencyKey=PREFIX+uuid.uuid4().hex,
                         expirationDate=(datetime.now(timezone.utc)+timedelta(seconds=180)).isoformat())

            def guard(fresh_account):
                if self.stopping():
                    raise RuntimeError('Stopping: new orders blocked')
                if time.monotonic()-read_at > 45:
                    raise ValueError('Orderbook aged beyond 45 seconds during preflight')
                return check_reduction(order, fresh_account, nodes, self.min_gain,
                                       reserved=reservations(self.exe.recovery_path))

            guard(account)
            result = self.exe.submit_single(order, reduce_only=True, guard=guard)
            plans.append({'order': order, 'result': result})
            log('paper' if self.exe.dry_run else 'submit', **plans[-1])
            busy.add(key)
            slots -= 1
            if not self.exe.dry_run:
                account = self.exe.reconcile()
        status = {'startedAt': start, 'at': utc(), 'phase': 'running',
                  'mode': 'paper' if self.exe.dry_run else 'live_reduce_only',
                  'lot': self.lot, 'maxMarkets': self.max_markets, 'minGainPerShare': self.min_gain,
                  'pnl': account['pnl'], 'grossCapital': account['grossCapital'],
                  'heldOrders': held, 'submitted': plans, 'cancelled': cancelled, 'skipped': skipped,
                  'positionShares': sum(abs(q) for q in inventory(account['positions']['positions']).values()),
                  'openOrders': account['openOrders'], 'bookReads': reads}
        atomic_json(DIRECTORY / 'status.json', status)
        log('cycle', mode=status['mode'], pnl=status['pnl'], positionShares=status['positionShares'],
            openOrders=len(status['openOrders']), submitted=len(plans))
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--reduce-only', action='store_true')
    parser.add_argument('--slug', default='midterm-elections')
    parser.add_argument('--interval', type=float, default=30)
    parser.add_argument('--lot', type=int, default=25)
    parser.add_argument('--max-markets', type=int, default=3)
    parser.add_argument('--min-gain', type=float, default=0.01)
    parser.add_argument('--cycles', type=int, default=0, help='0 runs continuously')
    args = parser.parse_args()
    if (args.live and not args.reduce_only or not 1 <= args.lot <= 25
            or not 1 <= args.max_markets <= 3 or finite(args.min_gain) < 0.01
            or finite(args.interval) < 10 or args.cycles < 0):
        parser.error('Require --reduce-only live; lot 1..25; markets 1..3; gain >= .01; interval >= 10')
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    runner = RecoveryRunner(Executor(slug=args.slug, dry_run=not args.live),
                            args.lot, args.max_markets, args.min_gain,
                            stopping=lambda: stop.is_set() or (DIRECTORY / 'stop.request').exists())
    with instance_lock(DIRECTORY):
        cycles = 0
        atomic_json(DIRECTORY / 'status.json', {'at': utc(), 'phase': 'starting',
                    'mode': 'live_reduce_only' if args.live else 'paper',
                    'lot': args.lot, 'maxMarkets': args.max_markets})
        try:
            while not stop.is_set() and not (DIRECTORY / 'stop.request').exists():
                try:
                    runner.cycle()
                except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                    if runner.stopping():
                        break  # finally performs the sole shutdown cleanup
                    atomic_json(DIRECTORY / 'status.json', {'at': utc(), 'phase': 'error',
                                'mode': 'live_reduce_only' if args.live else 'paper', 'error': str(exc)[:500]})
                    log('error', error=str(exc)[:500])
                    if args.live:
                        try:
                            runner.cancel_owned()
                        except Exception as cancel_exc:
                            log('cancel_error', error=str(cancel_exc)[:300])
                cycles += 1
                if args.cycles and cycles >= args.cycles:
                    break
                stop.wait(args.interval)
        finally:
            try:
                if args.live:
                    runner.cancel_owned()
            finally:
                atomic_json(DIRECTORY / 'status.json', {'at': utc(), 'phase': 'stopped',
                            'mode': 'live_reduce_only' if args.live else 'paper', 'cycles': cycles})
                log('stopped', cycles=cycles)


if __name__ == '__main__':
    main()
