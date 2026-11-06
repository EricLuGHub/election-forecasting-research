"""Maintained basket runner (backlog item 28). Replaces /tmp/rot*.py one-shots.

Commands (dry-run default; --live requires standing authorization):
  scan    top-book pair edges from monitor observations (ex-taken filter)
  verify  depth walks at size + $15 rule + venue screen -> fireable intents
  fire    submit intents (dry-run prints; --live submits via Executor)
  recon   reconcile fired intents against fills (remaining quantities)

Ownership: intents carry ROTM- idempotency keys; ledger lives in
data/e2_taken.json (unchanged schema); only Q4/ROT*/NH/SHELF orders managed.
Exit/unwind policy unchanged (whole baskets, E1 owns live exits).
"""
import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from .client import ROOT, Client
from .execution import Executor, build_multileg, round_tick
from .convexit import race_pair, joint_exit
from .reconcile import reconcile

MIN_EDGE = 15.0
PREFIX = 'ROTM-'
CAP_BASKET = 5000.0
CAP_TOTAL = 70000.0


def load_taken():
    path = ROOT / 'data/e2_taken.json'
    return json.loads(path.read_text()) if path.exists() else {}


def pair_universe(client, tid):
    """{(eid_r, eid_d): race} for all R/D pairs in the catalog."""
    mkts = client.pages('/markets', limit=100, tournamentId=tid)
    rmap, dmap = {}, {}
    r_pre, d_pre = 'Will the Republican Party win the ', 'Will the Democratic Party win the '
    for m in mkts:
        t = m.get('title', '')
        ex = (m.get('exchanges') or [{}])[0].get('id')
        if t.startswith(r_pre):
            rmap[t[len(r_pre):]] = str(ex)
        elif t.startswith(d_pre):
            dmap[t[len(d_pre):]] = str(ex)
    out = {}
    for race in set(rmap) & set(dmap):
        out[(rmap[race], dmap[race])] = race
    return out


def latest_tops(history_path, since_hours=2.0):
    """eid -> (at, bestBid, bestAsk) from recent monitor observations."""
    from datetime import timedelta
    db = sqlite3.connect(f'file:{history_path}?mode=ro', uri=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    latest = {}
    for at, resource, payload in db.execute(
            "SELECT at, resource, payload FROM observations WHERE at > ?",
            (cutoff,)):
        try:
            p = json.loads(payload)
            eid = str(p.get('exchangeId', resource))
            bid, ask = float(p['bestBid']), float(p['bestAsk'])
        except (ValueError, KeyError, TypeError):
            continue
        if eid not in latest or at > latest[eid][0]:
            latest[eid] = (at, bid, ask)
    db.close()
    return latest


def scan_pairs(client, tid, taken_eids, history_path, min_edge=0.015):
    """Top-book shortlist ex-taken. Returns [(edge, race, rm, dm, rb, db)]."""
    tops = latest_tops(history_path)
    rows = []
    for (rm, dm), race in pair_universe(client, tid).items():
        if rm in taken_eids or dm in taken_eids:
            continue
        r = tops.get(rm)
        d = tops.get(dm)
        if not r or not d:
            continue
        edge = r[1] + d[1] - 1.0
        if edge >= min_edge:
            rows.append((edge, race, rm, dm, r[1], d[1]))
    rows.sort(reverse=True)
    return rows


SKEW_LIMIT = 60.0  # max seconds between the two legs' book reads
FRESH_LIMIT = 180.0  # max age of either leg read at fire time


def book_at(book):
    """Epoch seconds of a book read, or None when unstamped."""
    try:
        return datetime.fromisoformat(
            book.get('asOf', {}).get('at', '').replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def walk_cost(client, tid, eid, size):
    """(cost, worst_no_price, filled, read_at) buying size NO via YES bids.

    Escalating depth (item 25): shallow fetch first, deepen only until the
    size fills. Identical results to a direct depth-50 read.
    """
    from .depthacq import acquire_book
    book, _ = acquire_book(client, tid, eid, size=size)
    need, cost, worst = size, 0.0, None
    for x in book.get('bids', []):
        take = min(need, float(x['quantity']))
        cost += take * (1.0 - float(x['price']))
        worst = 1.0 - float(x['price'])
        need -= take
        if need <= 0:
            break
    return round(cost, 2), worst, need <= 0, book_at(book)


def verify(client, tid, shortlist, size=1000, min_edge=MIN_EDGE, avoid=(),
             skew_limit=SKEW_LIMIT, fresh_limit=FRESH_LIMIT, now=None):
    """Depth-verify shortlist into fireable intents. Never submits.

    avoid: exchange IDs their reducer works (shared-liquidity screen).
    Freshness (item 27): a pair is never fresher than its oldest leg read.
    Legs read more than skew_limit apart trigger one re-read of the older
    leg; reads older than fresh_limit at decision time reject the pair as
    stale_pair even if each leg once passed. now: epoch override for tests.
    """
    now = time.time() if now is None else now
    intents = []
    avoid = {str(e) for e in avoid}
    for edge_top, race, rm, dm, rb, db in shortlist:
        if str(rm) in avoid or str(dm) in avoid:
            yield {'basket': race, 'verified': False, 'reason': 'shared_venue',
                   'edge': round(edge_top * size, 2)}
            continue
        legs, total, ok = [], 0.0, True
        stamps = {}
        for eid in (rm, dm):
            try:
                cost, worst, filled, at = walk_cost(client, tid, eid, size)
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                ok = {'error': str(exc)[:120]}
                break
            if not filled:
                ok = False
                break
            total += cost
            stamps[eid] = at
            legs.append({'exchangeId': eid, 'side': 'no', 'action': 'buy',
                         'quantity': size, 'price': round_tick(worst)})
        if ok is not True:
            yield {'race': race, 'verified': False,
                   'reason': ok.get('error', 'thin') if isinstance(ok, dict) else 'thin'}
            continue
        ages = [now - a for a in stamps.values() if a is not None]
        if len(ages) == 2 and abs(ages[0] - ages[1]) > skew_limit:
            # One re-read of the older leg, then re-evaluate (item 27).
            older = rm if stamps.get(rm, now) < stamps.get(dm, now) else dm
            try:
                cost, worst, filled, at = walk_cost(client, tid, older, size)
            except (RuntimeError, OSError, ValueError, KeyError):
                filled = False
            if not filled:
                yield {'basket': race, 'verified': False, 'reason': 'thin'}
                continue
            # rebuild totals cleanly from re-walked legs
            total = 0.0
            legs = []
            stamps = {}
            ok2 = True
            for eid in (rm, dm):
                try:
                    cost2, worst2, filled2, at2 = walk_cost(client, tid, eid, size)
                except (RuntimeError, OSError, ValueError, KeyError):
                    ok2 = False
                    break
                if not filled2:
                    ok2 = False
                    break
                total += cost2
                stamps[eid] = at2
                legs.append({'exchangeId': eid, 'side': 'no', 'action': 'buy',
                             'quantity': size, 'price': round_tick(worst2)})
            if not ok2:
                yield {'basket': race, 'verified': False, 'reason': 'thin'}
                continue
            ages = [now - a for a in stamps.values() if a is not None]
        if any(a is None or a > fresh_limit for a in ages) or len(ages) < 2:
            yield {'basket': race, 'verified': False, 'reason': 'stale_pair',
                   'edge': round(size - total, 2)}
            continue
        edge = size - total
        if edge < min_edge:
            yield {'basket': race, 'verified': False, 'reason': 'below_rule',
                   'edge': round(edge, 2)}
            continue
        yield {'basket': race, 'verified': True, 'legs': legs,
               'cost': round(total, 2), 'edge': round(edge, 2), 'size': size,
               'read_ages': [round(a, 1) for a in ages]}


def fire(client, intents, live=False, tag=None, executor=None, tid=None):
    """Submit verified intents. dry-run default; returns per-basket results."""
    tag = tag or datetime.now(timezone.utc).strftime('%Y%m%d')
    exe = executor or Executor(slug='midterm-elections', dry_run=not live,
                               max_basket_capital=CAP_BASKET, max_total_capital=CAP_TOTAL)
    journal = exe.journal()
    if any(r.get('status') == 'unknown' for r in journal.values()):
        raise RuntimeError('Unresolved placements block firing')
    if tid is None:
        tid = exe.client.get('/tournaments', slug='midterm-elections')['data'][0]['id']
    out = []
    for intent in intents:
        if not intent.get('verified'):
            out.append({'basket': intent.get('basket'), 'skipped': True,
                        'reason': intent.get('reason')})
            continue
        basket = build_multileg(intent['legs'], tournament_id=tid)
        basket['idempotencyKey'] = '%s%s-%s' % (
            PREFIX, intent['basket'].upper().replace(' ', '')[:12], tag)
        try:
            resp = exe.submit_basket(basket, expected_capital=intent['cost'])
            if live:
                det = [(r.get('data', {}).get('orderId'),
                        r.get('data', {}).get('quantityTraded'),
                        r.get('data', {}).get('remainingQuantity'))
                       for r in resp.get('results', [])]
            else:
                det = 'dry_run:%s' % basket['idempotencyKey']
            out.append({'basket': intent['basket'], 'orders': det,
                        'cost': intent['cost'], 'edge': intent['edge']})
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            out.append({'basket': intent['basket'], 'error': str(exc)[:200]})
    return out


def exit_intents(client, tid, ledger, positions, min_edge=MIN_EDGE,
                 per_share=0.005, min_abs=5.0):
    """Paper exit intents for baskets: joint proceeds on paired qty.

    Returns [{basket, exited_qty, proceeds, cost, edge, per_share, reason}].
    reasons: bankable | hold | depleted | unresolved | thin.
    Re-entry rule (enforced at fire time, recorded here): a re-entry counts
    as a NEW basket (fresh $15 verify) and no basket may exceed 2 exits per
    7 days (round_trips ledger counter). Live exits are REFUSED by policy:
    E1 owns all live reductions; use --live only with regime sign-off.
    """
    intents = []
    paired_map = {r['basket']: r for r in
                  reconcile(ledger, positions, lambda race: race_pair(client, tid, race))}
    for name, info in ledger.items():
        race = str(info.get('race', ''))
        cost = info.get('cost')
        if cost is None or 'floor' not in info:
            continue
        size = None
        for token in race.split():
            if token.startswith('x') and token[1:].isdigit():
                size = int(token[1:])
        if not size:
            continue
        pair = race_pair(client, tid, race)
        if not pair:
            intents.append({'basket': name, 'reason': 'unresolved'})
            continue
        rec = paired_map.get(name, {})
        q = min(rec.get('paired', 0), size)
        if q <= 0:
            intents.append({'basket': name, 'reason': 'depleted'})
            continue
        try:
            proceeds = joint_exit(client, tid, pair[0], pair[1], q)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            intents.append({'basket': name, 'reason': 'error',
                            'detail': str(exc)[:120]})
            continue
        if proceeds is None:
            intents.append({'basket': name, 'reason': 'thin'})
            continue
        pcost = float(cost) * q / size
        edge = proceeds - pcost
        ps = edge / (2 * q)
        trips = int(info.get('round_trips', 0))
        if edge >= min_edge and ps >= per_share and trips < 2:
            reason = 'bankable'
        elif trips >= 2:
            reason = 'hold_roundtrip_cap'
        else:
            reason = 'hold'
        intents.append({'basket': name, 'reason': reason, 'exited_qty': q,
                        'proceeds': round(proceeds, 2),
                        'cost': round(pcost, 2), 'edge': round(edge, 2),
                        'per_share': round(ps, 4),
                        'round_trips': trips})
    return intents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cmd', choices=['scan', 'verify', 'fire', 'recon', 'exit'])
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--size', type=int, default=1000)
    parser.add_argument('--min-edge', type=float, default=MIN_EDGE)
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--avoid', default='1044,1047',
                        help='Comma-separated exchange IDs their reducer works '
                        '(shared-liquidity screen)')
    args = parser.parse_args()
    client = Client()
    tid = client.get('/tournaments', slug='midterm-elections')['data'][0]['id']
    if args.cmd == 'recon':
        from .reconcile import reconcile
        ledger = load_taken()
        positions = client.get('/tournaments/midterm-elections/portfolio/positions')
        positions = positions.get('positions', positions)
        rows = reconcile(ledger, positions if isinstance(positions, list) else [],
                         lambda race: race_pair(client, tid, race))
        for row in rows:
            print(json.dumps(row)[:260], flush=True)
        return
    if args.cmd == 'exit':
        # Paper intents only: E1 owns all live reductions. --live is refused.
        if args.live:
            raise SystemExit('baskets exit --live refused: E1 owns live exits')
        ledger = load_taken()
        positions = client.get('/tournaments/midterm-elections/portfolio/positions')
        positions = positions.get('positions', positions)
        for intent in exit_intents(
                client, tid, ledger,
                positions if isinstance(positions, list) else []):
            print(json.dumps(intent)[:260], flush=True)
        return
    taken = set()
    for info in load_taken().values():
        race = str(info.get('race', ''))
        pair = race_pair(client, tid, race)
        if pair:
            taken.update(pair)
    history = str(ROOT / 'data/monitor/history.sqlite3')
    shortlist = scan_pairs(client, tid, taken, history)[:args.limit]
    if args.cmd == 'scan':
        for row in shortlist:
            print(json.dumps({'edge': round(row[0], 4), 'race': row[1],
                              'legs': [row[2], row[3]]})[:200], flush=True)
        return
    avoid = {e.strip() for e in args.avoid.split(',') if e.strip()}
    intents = list(verify(client, tid, shortlist, size=args.size,
                          min_edge=args.min_edge, avoid=avoid))
    if args.cmd == 'verify':
        for intent in intents:
            print(json.dumps(intent)[:300], flush=True)
        return
    for result in fire(client, intents, live=args.live):
        print(json.dumps(result)[:300], flush=True)


if __name__ == '__main__':
    main()
