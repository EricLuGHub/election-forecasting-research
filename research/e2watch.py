"""Engine2 basket research watcher. Live placement is disabled.

The venue's multi-leg atomicity covers placement, NOT all-or-none execution.
Live use requires a tested partial-fill, hedge and expiry lifecycle first.

Loop (intended for cron every few minutes, NOT a tight loop):
1. Read monitor status.json confirmedCandidates (fresh: bookReadStartedAt age OK).
2. For each exclusive_no candidate not already taken (ledger), re-verify depth
   with a fresh strength check, enforce min edge + per-basket/total caps.
3. Preview ONE multi-leg basket via Executor(dry_run), then
   record the fill/ledger entry. Never retries the same basket twice:
   idempotency keys + taken ledger in data/e2_taken.json.

Default caps keep the worst case small. Paper mode (default) logs what WOULD
fire without submitting. --live records an independent safety hold.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from .client import ROOT, Client
from .execution import Executor, build_multileg, round_tick
from .engines.engine2_baskets import NoBasket


def fresh(status, candidate, max_age=60.0):
    try:
        started = datetime.fromisoformat(candidate['bookReadStartedAt'])
        return 0 <= (datetime.now(timezone.utc) - started).total_seconds() <= max_age
    except (KeyError, ValueError, TypeError):
        return False


def taken_ledger():
    path = ROOT / 'data/e2_taken.json'
    return json.loads(path.read_text()) if path.exists() else {}


def mark_taken(cid, info):
    path = ROOT / 'data/e2_taken.json'
    ledger = taken_ledger()
    ledger[cid] = info
    path.write_text(json.dumps(ledger, indent=2) + '\n')


def verify_candidates(args, limit=3):
    """Paper-only: re-verify recent exclusive_no candidates with fresh depth.

    Reads recent candidates from monitor history (any state), refreshes catalog,
    and runs a full depth confirmation per candidate. Logs VERIFY-WOULD-FIRE
    for anything holding edge at executable depth. Never submits.
    """
    import sqlite3
    import types
    from .monitor import Monitor
    history_path = ROOT / 'data/monitor/history.sqlite3'
    if not history_path.exists():
        print('no monitor history')
        return []
    db = sqlite3.connect(str(history_path))
    rows = db.execute('SELECT payload FROM candidate_state').fetchall()
    cands = []
    for (payload,) in rows:
        try:
            state = json.loads(payload)
        except ValueError:
            continue
        cand = state.get('candidate')
        if not cand or state.get('state') == 'cleared':
            continue
        legs = cand.get('legs', [])
        if not legs or any(x.get('side') != 'no' for x in legs):
            continue
        cands.append(cand)
    cands.sort(key=lambda c: float(c.get('minimumNetPayoutMinusCost', 0)), reverse=True)
    cfg = types.SimpleNamespace(slug='midterm-elections', fee=0.0, max_quote_age=90.0,
                                max_confirmation_span=10.0, min_profit=0.0, min_edge=0.0,
                                directory=str(ROOT / 'data/e2verify'),
                                discovery_interval=60.0, metadata_ttl=900.0,
                                metadata_per_cycle=5)
    mon = Monitor.__new__(Monitor)
    mon.args = cfg
    mon.directory = ROOT / 'data/e2verify'
    mon.directory.mkdir(parents=True, exist_ok=True)
    mon.client = Client()
    mon.markets, mon.nodes, mon.node_times = [], {}, {}
    mon.catalog_at = 0.0
    mon.cycles = 0
    mon.history = None
    mon.tournament = None
    from .monitor import History
    mon.history = History(mon.directory / 'history.sqlite3')
    mon.refresh_catalog()
    out = []
    for cand in cands[:limit]:
        try:
            result = mon.confirm(cand)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            result = {'state': 'unknown', 'reason': str(exc)[:150]}
        row = {'race': cand.get('race'), 'state': result['state'],
               'edge': cand.get('minimumNetPayoutMinusCost'),
               'qty': cand.get('quantityEach'), 'cost': cand.get('cost'),
               'edge_per_unit': round(float(cand.get('minimumNetPayoutMinusCost', 0)) / max(1, float(cand.get('quantityEach', 1))), 4),
               'reason': result.get('reason')}
        out.append(row)
        print('VERIFY', json.dumps(row)[:220])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--min-edge', type=float, default=0.5)
    parser.add_argument('--max-capital', type=float, default=500.0)
    parser.add_argument('--lot', type=int, default=100,
                        help='Shares per leg; candidates scaled down to this size')
    parser.add_argument('--loop', type=float, default=0,
                        help='Seconds between checks; 0 = single run')
    parser.add_argument('--verify', action='store_true',
                        help='Paper only: re-verify recent candidates with fresh depth, log what would fire')
    args = parser.parse_args()
    if args.verify:
        verify_candidates(args)
        return
    if args.loop > 0:
        last_cycle = None
        while True:
            try:
                status = json.loads((ROOT / 'data/monitor/status.json').read_text())
                if status.get('cycle') != last_cycle:
                    last_cycle = status.get('cycle')
                    run_once(status, args)
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                beat({'error': str(exc)[:200], 'live': args.live})
            time.sleep(args.loop)
    else:
        status = json.loads((ROOT / 'data/monitor/status.json').read_text())
        run_once(status, args)


def beat(info):
    with (ROOT / 'data/e2watch.log').open('a') as handle:
        handle.write(json.dumps(info) + '\n')


def run_once(status, args):
    mode = ROOT / 'data/recovery/mode.json'
    if mode.exists() and json.loads(mode.read_text()).get('reduceOnly'):
        beat({'at': datetime.now(timezone.utc).isoformat(), 'live': args.live,
              'phase': 'recovery_hold', 'fired': 0})
        return
    if args.live:
        beat({'at': datetime.now(timezone.utc).isoformat(), 'live': True,
              'phase': 'partial_fill_lifecycle_missing', 'fired': 0})
        return
    ledger = taken_ledger()
    engine = NoBasket()
    exe = Executor(dry_run=not args.live, max_basket_capital=args.max_capital,
                   max_total_capital=args.max_capital)
    fired = []
    seen = 0
    for cand in status.get('confirmedCandidates', []):
        if cand.get('kind') != 'exclusive_no':
            continue
        seen += 1
        cid = cand.get('id') or json.dumps(cand.get('legs'))
        if cid in ledger or not fresh(status, cand):
            continue
        if float(cand.get('minimumNetPayoutMinusCost', 0)) < args.min_edge:
            continue
        if float(cand.get('cost', 0)) > args.max_capital:
            continue
        size = int(min(int(cand.get('quantityEach', 0)), args.lot))
        if size <= 0:
            continue
        scaled = dict(cand, quantityEach=size,
                      cost=round(float(cand.get('cost', 0)) * size / int(cand.get('quantityEach', size)), 4),
                      minimumNetPayoutMinusCost=round(float(cand.get('minimumNetPayoutMinusCost', 0)) * size / int(cand.get('quantityEach', size)), 4))
        if scaled['minimumNetPayoutMinusCost'] < args.min_edge:
            continue
        # Limits bound each individual fill price. They do NOT lock the basket
        # edge when only some legs fill; placement atomicity is not fill atomicity.
        legs = []
        for leg, fill in zip(scaled['legs'], scaled.get('fills', [])):
            legs.append({'exchangeId': str(leg['exchangeId']), 'side': leg['side'],
                         'action': 'buy', 'quantity': size,
                         'price': round_tick(float(fill.get('worstPrice')))})
        if len(legs) != len(scaled['legs']):
            continue
        tid = exe.client.get('/tournaments/midterm-elections')['id']
        basket = build_multileg(legs, tournament_id=tid)
        intent = {'engine': 'E2', 'basket': basket, 'expected_capital': scaled['cost'],
                  'race': scaled.get('race')}
        result = exe.submit_basket(intent['basket'], expected_capital=intent['expected_capital'])
        mark_taken(cid, {'at': datetime.now(timezone.utc).isoformat(),
                         'race': cand.get('race'), 'live': args.live,
                         'result': result})
        fired.append({'race': cand.get('race'), 'result': result})
        break  # one basket per run; next run handles the rest
    heartbeat = {'at': datetime.now(timezone.utc).isoformat(), 'live': args.live,
                 'board': seen, 'fired': len(fired)}
    beat_json = json.dumps(heartbeat)
    with (ROOT / 'data/e2watch.log').open('a') as handle:
        handle.write(beat_json + '\n')
    print(json.dumps({'fired': fired, 'live': args.live}, indent=2, default=str)[:3000])


if __name__ == '__main__':
    main()
