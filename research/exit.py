"""Legacy exit diagnostics. Live execution moved to research.e1run.

Loop: for every open position, value the full-quantity exit at executable depth
(YES longs into YES bids; shorts/NO via complements), then:
  - take-profit: exit --fraction when exit value >= cost * (1 + --take-profit);
  - endgame: inside --endgame-hours of tournament end, flatten everything;
  - --flatten-all: one-shot cancel-all + flatten (the panic button).
No generic stop-loss on hedges: exits here only bank gains or obey the clock.
Read-only: use the cost-aware, hedge-preserving E1 recovery runner for live exits.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from .client import ROOT, Client
from .execution import Executor, round_tick
from .gate import Gate, GateClosed


def depth_proceeds(book, side, quantity):
    """Net proceeds of selling quantity into displayed bids (YES-normalized)."""
    if side == 'yes':
        levels = [(float(x['price']), float(x['quantity'])) for x in book.get('bids', [])]
    else:
        levels = [(1.0 - float(x['price']), float(x['quantity'])) for x in book.get('asks', [])]
    filled, proceeds = 0.0, 0.0
    for price, size in sorted(levels, reverse=True):
        take = min(size, quantity - filled)
        filled += take
        proceeds += take * price
        if filled >= quantity:
            break
    return proceeds if filled >= quantity else None


def cool():
    path = ROOT / 'data/exit_cool.json'
    return json.loads(path.read_text()) if path.exists() else {}


def mark_cool(eid, minutes):
    path = ROOT / 'data/exit_cool.json'
    ledger = cool()
    ledger[str(eid)] = (datetime.now(timezone.utc).timestamp() + minutes * 60)
    path.write_text(json.dumps(ledger) + '\n')


def closing_order(position, price, fraction):
    qty = abs(int(position['quantity']))
    if not qty or not 0 < fraction <= 1:
        raise ValueError('Require a nonempty position and fraction in (0, 1]')
    n = max(1, int(qty * fraction))
    return {'exchangeId': str(position['exchangeId']),
            'side': 'yes' if position['quantity'] > 0 else 'no',
            'action': 'sell', 'quantity': n, 'price': round_tick(price)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--loop', type=float, default=0)
    parser.add_argument('--take-profit', type=float, default=0.5)
    parser.add_argument('--fraction', type=float, default=0.5)
    parser.add_argument('--cooldown-min', type=float, default=15.0)
    parser.add_argument('--endgame-hours', type=float, default=0.0)
    parser.add_argument('--flatten-all', action='store_true')
    parser.add_argument('--slug', default='midterm-elections')
    args = parser.parse_args()
    if args.live:
        parser.error('Standalone live exits retired: use research.e1run --live --reduce-only')
    client = Client()
    gate = Gate(client, args.slug)
    exe = Executor(slug=args.slug, dry_run=not args.live)

    def cycle():
        try:
            tournament = gate.check()
        except GateClosed as exc:
            log(f'GATE {exc}')
            return
        end = datetime.fromisoformat(tournament['endDate'].replace('Z', '+00:00'))
        endgame = (end - datetime.now(timezone.utc)).total_seconds() < args.endgame_hours * 3600
        positions = client.get(f'/tournaments/{args.slug}/portfolio/positions').get('positions', [])
        cooled = cool()
        now_ts = datetime.now(timezone.utc).timestamp()
        for position in positions:
            if float(position.get('quantity', 0)) == 0:
                continue
            side = 'yes' if position['quantity'] > 0 else 'no'
            eid = str(position['exchangeId'])
            if cooled.get(eid, 0) > now_ts and not args.flatten_all:
                continue
            book = client.get(f'/exchanges/{eid}/orderbook', tournamentId=tournament['id'], depth=50)
            qty = abs(int(position['quantity']))
            proceeds = depth_proceeds(book, side, qty)
            if proceeds is None:
                log(f'THIN {eid} cannot exit {qty} at depth')
                continue
            cost = float(position.get('costBasis', 0)) or 1e-9
            take = proceeds >= cost * (1 + args.take_profit)
            if args.flatten_all or endgame or take:
                px = float(book['bids'][0]['price']) if side == 'yes' else 1-float(book['asks'][0]['price'])
                order = closing_order(position, px, 1.0 if (args.flatten_all or endgame) else args.fraction)
                order['tournamentId'] = tournament['id']
                import uuid
                order['idempotencyKey'] = f'EXIT-{uuid.uuid4().hex[:12]}'
                if args.live:
                    try:
                        result = exe.submit_single(order, expected_capital=qty)
                    except RuntimeError as exc:
                        log(f'EXIT-FAIL {eid} {str(exc)[:150]}')
                        continue
                    log(f"EXIT {eid} {order['action']} {order['side']} {order['quantity']}@{order['price']} -> {json.dumps(result)[:150]}")
                    mark_cool(eid, args.cooldown_min)
                else:
                    log(f"PAPER-EXIT {eid} {order['action']} {order['side']} {order['quantity']}@{order['price']} value={proceeds:.2f} cost={cost:.2f}")

    def log(msg):
        line = f'{datetime.now(timezone.utc).isoformat()} {msg}'
        with (ROOT / 'data/exit.log').open('a') as handle:
            handle.write(line + '\n')

    # bind log before first use (defined late to keep top readable)
    global_log = log
    if args.loop > 0:
        while True:
            try:
                cycle()
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                log(f'ERROR {type(exc).__name__}: {str(exc)[:200]}')
            time.sleep(args.loop)
    else:
        cycle()


if __name__ == '__main__':
    main()
