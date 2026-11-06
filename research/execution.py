"""Execution layer with guardrails. Dry-run by default; live requires --live.

Nothing here submits orders unless dry_run is False AND the tournament is open.
Single-leg POST /orders, atomic baskets via POST /orders/multi-leg (<=10 legs,
all-or-none persisted, NOT all-or-none fills), fan-out via POST /orders/batch (<=50, best-effort),
kill switch via POST /orders/cancel-all. See data/openapi.json.

Limit prices must sit on the 0.005 tick within [0.005, 0.995]; price 1 (buy) and
0 (sell), or an omitted price, encode market orders.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import uuid
from .client import Client, ROOT
from .monitor import atomic_json
from .risk import finite, gross_capital, is_reduction, order_capital
from .pilot import opening_proof

TICK = 0.005
MIN_PRICE = 0.005
MAX_PRICE = 0.995
MAX_MULTILEG = 10
MAX_BATCH = 50


def round_tick(price):
    return round(round(price / TICK) * TICK, 3)


def validate_leg(leg):
    eid = str(leg['exchangeId'])
    if not eid.isdigit():
        raise ValueError(f'Bad exchangeId {eid!r}')
    if leg['side'] not in ('yes', 'no'):
        raise ValueError(f"Bad side {leg['side']!r}")
    if leg['action'] not in ('buy', 'sell'):
        raise ValueError(f"Bad action {leg['action']!r}")
    qty = leg['quantity']
    if type(qty) is not int or qty <= 0:
        raise ValueError(f'Quantity must be a positive int, got {qty!r}')
    if 'price' in leg and leg['price'] is not None:
        price = finite(leg['price'])
        if price in (0.0, 1.0):
            if price != (1.0 if leg['action'] == 'buy' else 0.0):
                raise ValueError('Wrong market-order encoding for action')
            return
        if not MIN_PRICE <= price <= MAX_PRICE:
            raise ValueError(f'Limit price {price} outside [{MIN_PRICE}, {MAX_PRICE}]')
        if abs(round_tick(price) - price) > 1e-9:
            raise ValueError(f'Limit price {price} off the 0.005 tick; use {round_tick(price)}')


def build_single(exchange_id, side, action, quantity, price=None, tournament_id=None):
    leg = {'exchangeId': str(exchange_id), 'side': side, 'action': action,
           'quantity': quantity}
    if price is not None:
        leg['price'] = price
    if tournament_id:
        leg['tournamentId'] = tournament_id
    validate_leg(leg)
    return {'idempotencyKey': f'exe-{uuid.uuid4().hex[:16]}', **leg}


def build_multileg(legs, relationship_id=None, tournament_id=None):
    if not 1 <= len(legs) <= MAX_MULTILEG:
        raise ValueError(f'Multi-leg needs 1-{MAX_MULTILEG} legs, got {len(legs)}')
    seen = set()
    clean = []
    for leg in legs:
        validate_leg(leg)
        key = (str(leg['exchangeId']), str(leg.get('tournamentId') or tournament_id or ''))
        if key in seen:
            raise ValueError(f'Duplicate exchange in basket: {key[0]}')
        seen.add(key)
        item = dict(leg)
        if tournament_id and 'tournamentId' not in item:
            item['tournamentId'] = tournament_id
        clean.append(item)
    body = {'idempotencyKey': f'basket-{uuid.uuid4().hex[:16]}', 'legs': clean}
    if relationship_id:
        body['relationshipConstraint'] = {'relationshipId': str(relationship_id)}
    return body


class Executor:
    def __init__(self, slug='midterm-elections', dry_run=True, client=None,
                 max_basket_capital=2000.0, max_total_capital=20000.0,
                 journal_path=None, recovery_path=None):
        self.slug = slug
        self.dry_run = dry_run
        self.client = client or Client()
        self.max_basket_capital = max_basket_capital
        self.max_total_capital = max_total_capital
        self.tournament = None
        self.journal_path = Path(journal_path or ROOT / 'data/execution_journal.json')
        self.recovery_path = Path(recovery_path or ROOT / 'data/recovery/mode.json')
        if min(finite(max_basket_capital), finite(max_total_capital)) < 0:
            raise ValueError('Negative capital cap')

    @contextmanager
    def locked(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.with_suffix('.lock').open('a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def journal(self):
        return json.loads(self.journal_path.read_text()) if self.journal_path.exists() else {}

    def owned_ids(self, prefix):
        return {int(row['response']['orderId']) for key, row in self.journal().items()
                if key.startswith(prefix) and (row.get('response') or {}).get('orderId') is not None}

    def preflight(self):
        t = self.client.get(f'/tournaments/{self.slug}')
        self.tournament = t
        if t.get('status') not in ('open', 'active'):
            raise RuntimeError(f"Tournament status is {t.get('status')!r}; live orders blocked")
        now = datetime.now(timezone.utc)
        start = datetime.fromisoformat(t['startDate'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(t['endDate'].replace('Z', '+00:00'))
        if not start <= now < end:
            raise RuntimeError('Outside tournament trading window')
        return t

    def _check_caps(self, capital, book=None):
        capital = finite(capital)
        if capital < 0:
            raise ValueError('Negative expected capital')
        if capital > self.max_basket_capital:
            raise ValueError(f'Basket capital {capital} exceeds cap {self.max_basket_capital}')
        book = book or self.reconcile()
        used = book['grossCapital']
        if used + capital > self.max_total_capital:
            raise ValueError(f'Used {used} + {capital} exceeds total cap {self.max_total_capital}')

    def _submit(self, route, body, legs, expected_capital, reduce_only=False, guard=None):
        for leg in legs:
            validate_leg(leg)
        key = body.get('idempotencyKey')
        if not isinstance(key, str) or not key:
            raise ValueError('A durable idempotency key is required')
        expected_capital = finite(expected_capital)
        if expected_capital < 0:
            raise ValueError('Negative expected capital')
        if self.dry_run:
            return {'dry_run': True, 'route': 'POST '+route,
                    'order' if route == '/orders' else 'basket': body}
        with self.locked():
            journal = self.journal()
            prior = journal.get(key)
            if prior:
                if prior['body'] != body or prior['route'] != route:
                    raise ValueError('Idempotency key reused with changed payload')
                if prior['status'] == 'confirmed':
                    return prior['response']
                raise RuntimeError('Unresolved placement; manual reconciliation required before continuing')
            if any(r['status'] == 'unknown' for r in journal.values()):
                raise RuntimeError('Unresolved placement in shared journal; new orders blocked')
            tournament = self.preflight()
            for leg in legs:
                if str(leg.get('tournamentId', body.get('tournamentId'))) != str(tournament['id']):
                    raise ValueError('Explicit matching tournamentId required')
                if leg.get('expirationDate'):
                    expiry = datetime.fromisoformat(leg['expirationDate'].replace('Z', '+00:00'))
                    if expiry <= datetime.now(timezone.utc):
                        raise ValueError('Order expired during preflight')
            book = self.reconcile(include_pnl=False)
            recovery = json.loads(self.recovery_path.read_text()) if self.recovery_path.exists() else {}
            recovering = recovery.get('reduceOnly', False)
            all_reducing = all(is_reduction(leg, book['positions']['positions'], book['openOrders']) for leg in legs)
            if reduce_only and not all_reducing:
                raise RuntimeError('Recovery/reduce-only mode blocks new or unreserved exposure')
            if recovering and not all_reducing:
                if route != '/orders' or len(legs) != 1 or not guard or not recovery.get('openingPermit'):
                    raise RuntimeError('Recovery/reduce-only mode blocks new or unreserved exposure')
                opening_proof(body, book, recovery['openingPermit'])
            risk_proof = guard(book) if guard else None
            if not all_reducing:
                capital = max(expected_capital, sum(order_capital(leg) for leg in legs))
                self._check_caps(capital, book)
                if capital+book['openOrderCapital'] > finite(tournament['myBalance']):
                    raise ValueError('Insufficient cash after reserving pending orders')
            journal[key] = {'route': route, 'body': body, 'status': 'unknown',
                            'at': datetime.now(timezone.utc).isoformat(), 'riskProof': risk_proof}
            atomic_json(self.journal_path, journal)  # write-ahead, including on ambiguous HTTP failures
            response = self.client.post(route, body)
            if route == '/orders' and (not isinstance(response, dict) or response.get('orderId') is None):
                raise RuntimeError('Missing orderId: ambiguous placement, new orders blocked')
            journal[key].update(status='confirmed', response=response)
            atomic_json(self.journal_path, journal)
            return response

    def submit_single(self, order, expected_capital=0.0, reduce_only=False, guard=None):
        return self._submit('/orders', order, [order], expected_capital, reduce_only, guard)

    def submit_basket(self, basket, expected_capital=0.0):
        # Revalidate the structural constraints at the submission boundary too.
        build_multileg(basket['legs'], tournament_id=basket.get('tournamentId'))
        return self._submit('/orders/multi-leg', basket, basket['legs'], expected_capital)

    def cancel_order(self, order_id):
        if self.dry_run:
            return {'dry_run': True, 'route': f'DELETE /orders/{order_id}'}
        with self.locked():
            t = self.client.get(f'/tournaments/{self.slug}')
            self.tournament = t
            rows = self.client.pages('/orders', status='open', limit=100, tournamentId=t['id'])
            if not any(str(o['id']) == str(order_id) for o in rows):
                return {'alreadyClosedOrOutOfScope': True}
            try:
                return self.client.delete(f'/orders/{order_id}')
            except RuntimeError as exc:
                # A fill/expiry may race the scoped lookup. Verify, do not guess.
                if 'HTTP 409' not in str(exc):
                    raise
                rows = self.client.pages('/orders', status='open', limit=100, tournamentId=t['id'])
                if any(str(o['id']) == str(order_id) for o in rows):
                    raise
                return {'alreadyClosed': True}

    def cancel_all(self, tournament_id=None):
        if tournament_id is None:
            if self.dry_run:
                return {'dry_run': True, 'route': 'POST /orders/cancel-all', 'slug': self.slug}
            tournament_id = self.client.get(f'/tournaments/{self.slug}')['id']
        body = {'tournamentId': tournament_id}
        if self.dry_run:
            return {'dry_run': True, 'route': 'POST /orders/cancel-all', 'body': body}
        with self.locked():
            t = self.client.get(f'/tournaments/{self.slug}')
            if str(tournament_id) != str(t['id']):
                raise ValueError('Cancel-all tournament scope mismatch')
            return self.client.post('/orders/cancel-all', body)

    def reconcile(self, include_pnl=True):
        self.tournament = self.tournament or self.client.get(f'/tournaments/{self.slug}')
        rows = self.open_orders()
        positions = self.client.get(f'/tournaments/{self.slug}/portfolio/positions')
        pnl = self.client.get(f'/tournaments/{self.slug}/portfolio/pnl') if include_pnl else None
        used = gross_capital(positions['positions'], rows)
        open_cap = sum(order_capital(o) for o in rows if o.get('open'))
        return {'openOrders': rows, 'openOrderCapital': round(open_cap, 6),
                'grossCapital': round(used, 6),
                'positions': positions, 'pnl': pnl,
                'tournamentStatus': (self.tournament or {}).get('status')}

    def open_orders(self):
        """Scoped cancellation discovery need not depend on a positions read."""
        self.tournament = self.tournament or self.client.get(f'/tournaments/{self.slug}')
        return self.client.pages('/orders', status='open', limit=100, tournamentId=self.tournament['id'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slug', default='midterm-elections')
    parser.add_argument('--live', action='store_true', help='Actually submit; default is dry-run')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('cancel-all')
    args = parser.parse_args()
    exe = Executor(slug=args.slug, dry_run=not args.live)
    if args.command == 'status':
        print(json.dumps(exe.reconcile(), indent=2, default=str)[:4000])
    elif args.command == 'cancel-all':
        print(json.dumps(exe.cancel_all(), indent=2, default=str)[:2000])


if __name__ == '__main__':
    main()
