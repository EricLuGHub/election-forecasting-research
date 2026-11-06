"""Bounded quoter v4. Paper default; --live quotes tiny with guards.

v4 rules from Phase-1 decomposition (cycle 106, 283 attributed fills):
- allowlist venues by at-fill edge (ban 987/994/890/885/1070/936/863/861...);
- HOLD working quotes, hard-cancel at --max-age (default 120s). Instant-take
  fills (<30s, -5.5c) are toxic; rested 30-120s quotes earn (+6.9c); stale kills;
- bid-side only by default (sells donate -7.1c); no wide-spread ban (wide earns).
Built on the hardened rails: Executor, risk helpers, Gate. Paper + live ledger.
Selection gate (venue suppress after bad fills) ships next cycle.
"""
import argparse
import json
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .client import ROOT, Client
from .execution import Executor
from .gate import Gate, GateClosed
from . import risk


def tick(price, up=False):
    return round((math.ceil((price - 1e-9) / 0.005) if up else math.floor((price + 1e-9) / 0.005)) * 0.005, 3)


def quote_pair(bid, ask, inv_shares, lot, skew_per_share=0.000025, offset=0.005):
    """(bid_px, ask_px) improving touch, skewed against inventory. None if bad."""
    if not (0 < bid < ask < 1) or ask - bid < 0.02:
        return None
    skew = skew_per_share * inv_shares
    qb = tick(min(max(bid + offset - skew, 0.005), 0.995))
    qa = tick(min(max(ask - offset - skew, 0.005), 0.995))
    if qa - qb <= 0:
        return None
    return qb, qa


def quote_age_ok(submit_ts, now, max_age):
    """True if a resting quote may stay. False forces cancel/replace.

    Timestamps are wall-clock (time.time()) so ages survive restarts via
    the journal; differences only, never absolute wall time.
    """
    if max_age is not None and max_age > 0 and (now - submit_ts) > max_age:
        return False
    return True


def recover_state(open_orders, journal, now=None):
    """Rebuild (born, submitted) for our Q4 orders after a restart.

    born: economic_key -> wall-clock submit time from journal `at`
    (unknown-age orders are treated as EXPIRED-old, never newborn: the
    audit's restart-evasion fix — born.get(key, now) made orphans immortal).
    submitted: orderId -> order body for gate attribution.
    Returns (born, submitted, recovered_count).
    """
    import datetime
    now = time.time() if now is None else now
    born, submitted, count = {}, {}, 0
    entries = journal if isinstance(journal, dict) else {}
    for order in open_orders or []:
        try:
            if not str(order.get('idempotencyKey', '')).startswith('Q4-'):
                continue
            key = risk.economic_key(order)
        except (ValueError, KeyError, TypeError):
            continue
        ts = None
        try:
            rec = entries.get(str(order.get('idempotencyKey', ''))) or {}
            ts = datetime.datetime.fromisoformat(rec.get('at', '')).timestamp()
        except (ValueError, TypeError):
            ts = None
        born[key] = ts if ts else 0.0  # unknown age = oldest: cancel-first
        try:
            oid = order.get('id')
            if oid is not None:
                submitted[oid] = dict(order)
                count += 1
        except (AttributeError, TypeError):
            continue
    return born, submitted, count


def load_cursor(path=None):
    try:
        return json.load(open(path or str(ROOT / 'data/quoter_cursor.json')))
    except (OSError, ValueError):
        return {}


def save_cursor(state, path=None):
    try:
        Path(path or str(ROOT / 'data/quoter_cursor.json')).write_text(json.dumps(state))
    except OSError:
        pass


V4_ALLOW = frozenset(
    '871 951 884 1061 1074 889 881 883 937 875 892 961 915 860 869 964 '
    '1050 862 945'.split())  # HISTORICAL reference only (cycle 106, raw signs).
# Item-7 normalized recompute: all venues ±1c noise, no venue shows real edge.
# Do NOT treat this as an allowlist without fresh sign-normalized evidence.


def gate_suppress(suppress, eid, edge, now, thresh=-0.03, minutes=15.0):
    """Record a bad fill; returns True if the venue is now suppressed."""
    if edge < thresh:
        suppress[eid] = now + minutes * 60.0
        return True
    return False


def gate_active(suppress, eid, now):
    """True if venue suppressed; prunes expired entries."""
    for key in [k for k, until in suppress.items() if until <= now]:
        suppress.pop(key, None)
    return eid in suppress


def approx_edge(fill, mids, order=None):
    """Signed per-share edge vs CURRENT mids (live approximation; scoring
    uses honest at-fill mids — see markout.py). Requires the originating
    order: raw fill signs lie after canonicalization (item 1). None when
    unscorable — skipped, never forced."""
    from .fillnorm import normalize, edge_vs
    if order is None:
        order = {}
    try:
        mid = mids.get(str(fill.get('exchangeId')))
    except AttributeError:
        return None
    return edge_vs(normalize(fill, order), mid)


def strategy_budget_ok(open_capital, intended, cap):
    """True if own open-order capital + intended fits the strategy budget."""
    try:
        return float(open_capital) + float(intended) <= float(cap)
    except (TypeError, ValueError):
        return False


def v4_legs(bid_only):
    if bid_only:
        return (('yes', 'buy'),)
    return (('yes', 'buy'), ('yes', 'sell'))


def log(msg, live):
    line = f'{datetime.now(timezone.utc).isoformat()} {"LIVE" if live else "PAPER"} {msg}'
    with (ROOT / 'data/quoter.log').open('a') as handle:
        handle.write(line + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--slug', default='midterm-elections')
    parser.add_argument('--interval', type=float, default=20.0)
    parser.add_argument('--lot', type=int, default=5)
    parser.add_argument('--max-markets', type=int, default=3)
    parser.add_argument('--max-position', type=int, default=600)
    parser.add_argument('--max-capital', type=float, default=2000.0)
    parser.add_argument('--cycles', type=int, default=0)
    parser.add_argument('--deny', default='',
                        help='Comma-separated exchangeIds to never quote (adverse-selection venues)')
    parser.add_argument('--allow', default='',
                        help='Comma-separated exchangeIds to quote (empty = all '
                        'non-denied). The historical V4_ALLOW list showed no edge '
                        'after sign-normalized recompute (item 7): restrict only '
                        'with fresh evidence.')
    parser.add_argument('--no-allow', action='store_true',
                        help='Disable the allowlist (quote any non-denied venue)')
    parser.add_argument('--max-age', type=float, default=0.0,
                        help='Hard-cancel own quotes older than this (seconds); 0 disables '
                        '(default off: the 120s rule lost its evidence in item 7)')
    parser.add_argument('--bid-only', dest='bid_only', action='store_true', default=False,
                        help='Quote bid side only (default off: normalized data shows '
                        'both sides ~breakeven; two-sided is the neutral default)')
    parser.add_argument('--two-sided', dest='bid_only', action='store_false',
                        help='Restore two-sided quoting (ablation)')
    parser.add_argument('--no-gate', action='store_true',
                        help='Disable the selection gate (ablation)')
    parser.add_argument('--gate-minutes', type=float, default=15.0)
    parser.add_argument('--expiry-secs', type=float, default=600.0,
                        help='Venue-side expiration for new quotes (seconds); '
                        '0 disables. Bounds staleness even across restarts.')
    parser.add_argument('--gate-thresh', type=float, default=-0.03)
    args = parser.parse_args()
    if args.live and not (1 <= args.lot <= 25 and 1 <= args.max_markets <= 3 and args.interval >= 10):
        parser.error('Live bounds: lot 1..25, markets 1..3, interval >= 10')
    client = Client()
    gate = Gate(client, args.slug)
    exe = Executor(slug=args.slug, dry_run=not args.live,
                   max_basket_capital=args.max_capital)
    tid = gate.tournament()['id']
    denied = {e.strip() for e in args.deny.split(',') if e.strip()}
    allowed = None if (args.no_allow or not args.allow.strip()) else \
        {e.strip() for e in args.allow.split(',') if e.strip()}
    born = {}  # economic_key -> wall-clock submit time (restart-safe)
    suppress = {}  # eid -> monotonic timestamp until which venue is gated
    submitted = {}  # own orderId -> order body this session (gate attribution)
    gate_checked = None
    try:
        rec = exe.reconcile(include_pnl=False)
        born, submitted, recovered = recover_state(
            rec.get('openOrders', []), exe.journal())
        gate_checked = load_cursor().get('gate_checked')
        log(f'recover orders={recovered} cursor={gate_checked is not None}', args.live)
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        log(f'RECOVER-FAIL {str(exc)[:120]}', args.live)
    held = set()
    grace = {}
    cycles = 0
    log(f'start lot={args.lot} max_markets={args.max_markets}', args.live)
    while True:
        try:
            tournament = gate.check()
            from .mdache import get_or_fetch
            markets, _, _ = get_or_fetch(
                'catalog:' + tid, 300.0,
                lambda: client.pages('/markets', limit=100, tournamentId=tid))
            eids = [str(e['id']) for m in markets if m.get('status') == 'open'
                    for e in m.get('exchanges', [])]
            books = {}
            for offset in range(0, len(eids), 100):
                resp = client.get('/exchanges/prices', ids=','.join(eids[offset:offset + 100]),
                                  tournamentId=tid)
                for q in resp.get('data', resp):
                    if q.get('bestBid') is not None and q.get('bestAsk') is not None:
                        books[str(q['exchangeId'])] = (float(q['bestBid']), float(q['bestAsk']))
            ranked = sorted(((a - b, eid) for eid, (b, a) in books.items() if a - b >= 0.02),
                            reverse=True)
            if args.live and not args.no_gate:
                try:
                    fresh = client.get(f'/tournaments/{args.slug}/portfolio/fills', limit=20)
                    rows = fresh.get('data', fresh) if isinstance(fresh, dict) else fresh
                    mids = {eid: (b + a) / 2 for eid, (b, a) in books.items()}
                    for fill in rows if isinstance(rows, list) else []:
                        oid = fill.get('orderId')
                        if oid not in submitted:
                            continue
                        if gate_checked is not None and str(fill.get('filledAt', '')) <= gate_checked:
                            continue
                        edge = approx_edge(fill, mids, submitted.get(oid))
                        if edge is not None and gate_suppress(
                                suppress, str(fill.get('exchangeId')), edge,
                                time.monotonic(), args.gate_thresh, args.gate_minutes):
                            log(f"GATE-SUPPRESS {fill.get('exchangeId')} edge={edge:.4f}", True)
                    if rows:
                        gate_checked = max(str(r.get('filledAt', '')) for r in rows)
                except (RuntimeError, OSError, ValueError, KeyError) as exc:
                    log(f'GATE-ERR {str(exc)[:120]}', args.live)
            now_gate = time.monotonic()
            ranked = [(s, eid) for s, eid in ranked
                      if eid not in denied and (allowed is None or eid in allowed)
                      and not gate_active(suppress, eid, now_gate)]
            alive = {eid for _, eid in ranked}
            for eid in list(held):
                if eid in alive:
                    grace.pop(eid, None)
                else:
                    grace[eid] = grace.get(eid, 0) + 1
                    if grace[eid] >= 3:
                        held.discard(eid)
                        grace.pop(eid, None)
            picks = [eid for _, eid in ranked if eid in held]
            for _, eid in ranked:
                if len(picks) >= args.max_markets:
                    break
                if eid not in held:
                    picks.append(eid)
                    held.add(eid)
            positions = client.get(f'/tournaments/{args.slug}/portfolio/positions').get('positions', [])
            inv = risk.inventory(positions)
            open_orders = exe.reconcile()['openOrders']
            ours = {}
            for order in open_orders:
                if not str(order.get('idempotencyKey', '')).startswith('Q4-'):
                    continue  # never touch other traders' orders (single-trader rule)
                try:
                    ours[risk.economic_key(order)] = order
                except ValueError:
                    continue
            want = set()
            for eid in picks:
                bid, ask = books[eid]
                my_inv = inv.get(eid, 0)
                if abs(my_inv) >= args.max_position:
                    held.discard(eid)
                    continue
                pair = quote_pair(bid, ask, my_inv, args.lot)
                if not pair:
                    continue
                qb, qa = pair
                legs = [(side, action, qb if action == 'buy' else qa)
                        for side, action in v4_legs(args.bid_only)]
                for side, action, price in legs:
                    key = (eid, 1 if action == 'buy' else -1, round(price, 8))
                    want.add(key)
                    if key in ours:
                        continue
                    # Hysteresis: keep a resting quote within two ticks of
                    # fresh instead of churning cancel/replace on every move.
                    if args.live:
                        near = [k for k in ours
                                if k[0] == eid and k[1] == key[1] and abs(k[2] - price) <= 0.0100001]
                    else:
                        near = []
                    if near:
                        want.update(near)
                        continue
                    order = {'exchangeId': eid, 'side': side, 'action': action,
                             'quantity': args.lot, 'price': price, 'tournamentId': tid,
                             'idempotencyKey': f'Q4-{uuid.uuid4().hex[:12]}'}
                    if args.expiry_secs and args.expiry_secs > 0:
                        order['expirationDate'] = (
                            datetime.now(timezone.utc) +
                            timedelta(seconds=args.expiry_secs)).isoformat()
                    if args.live:
                        try:
                            own_open = sum(risk.order_capital(o) for o in ours.values()
                                           if o.get('open'))
                        except (ValueError, KeyError, TypeError):
                            own_open = 0.0
                        if not strategy_budget_ok(own_open, args.lot, args.max_capital):
                            log(f'SKIP-CAP {eid} open={own_open:.2f} cap={args.max_capital}', True)
                            continue
                        try:
                            result = exe.submit_single(order, expected_capital=args.lot)
                        except RuntimeError as exc:
                            log(f'HALT {str(exc)[:200]}', True)
                            return
                        born[key] = time.time()
                        oid = (result or {}).get('orderId') if isinstance(result, dict) else None
                        if oid is not None:
                            submitted[oid] = dict(order)
                        log(f"SUBMIT {eid} {action} {args.lot}@{price} id={oid if oid is not None else '?'}", True)
                    else:
                        log(f'QUOTE {eid} {action} {args.lot}@{price}', False)
            if args.live:
                now = time.time()
                for key, order in ours.items():
                    if not order.get('open'):
                        born.pop(key, None)
                        continue
                    if key not in want or not quote_age_ok(born.get(key, 0.0), now, args.max_age):
                        try:
                            exe.cancel_order(order['id'])
                            born.pop(key, None)
                            log(f"CANCEL {key[0]}", True)
                        except (RuntimeError, OSError, ValueError, KeyError) as exc:
                            log(f'CANCEL-FAIL {str(exc)[:120]}', True)
            cycles += 1
            if gate_checked is not None:
                save_cursor({'gate_checked': gate_checked})
            if args.cycles and cycles >= args.cycles:
                break
        except GateClosed as exc:
            log(f'GATE {exc}', args.live)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            log(f'ERROR {type(exc).__name__}: {str(exc)[:200]}', args.live)
            if 'ambigu' in str(exc).lower():
                return
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
