"""Resolve an unknown single placement from uniquely matching CLOSED history.

Never replays a POST, cancels an order, deletes a journal entry, or guesses from
price alone. Default is read-only; --apply records verified ownership/evidence.
"""
import argparse
from datetime import datetime, timezone
import json

from .execution import Executor
from .monitor import atomic_json
from .pilot import instant
from .risk import finite


def matching(body, started_at, order):
    try:
        if (order['open'] or str(order['exchangeId']) != str(body['exchangeId'])
                or str(order['tournamentId']) != str(body['tournamentId'])
                or order['side'] != body['side'] or order['action'] != body['action']
                or finite(order['quantity']) != body['quantity']
                or abs(finite(order['priceLimit'])-finite(body['price'])) > 1e-9):
            return False
        # Reporting stores millisecond timestamps; require the exact same
        # millisecond expiry, which distinguishes repeated same-price quotes.
        expiry = instant(body['expirationDate'])
        actual_expiry = instant(order['expirationDate'])
        if expiry.replace(microsecond=expiry.microsecond//1000*1000) != actual_expiry.replace(microsecond=actual_expiry.microsecond//1000*1000):
            return False
        created = instant(order['createdAt'])
        return 0 <= (created-instant(started_at)).total_seconds() <= 120 and created < expiry
    except (KeyError, TypeError, ValueError):
        return False


def resolve(executor, key, order_id, apply=False):
    with executor.locked():
        journal = executor.journal()
        row = journal[key]
        if row['status'] != 'unknown' or row['route'] != '/orders':
            raise ValueError('Require an unresolved single-order placement')
        body = row['body']
        t = executor.client.get(f'/tournaments/{executor.slug}')
        if str(t['id']) != str(body['tournamentId']):
            raise ValueError('Wrong tournament')
        if instant(body['expirationDate']) >= datetime.now(timezone.utc):
            raise ValueError('Only expired, closed order ambiguities can be reconciled here')
        rows = executor.client.pages('/orders', status='all', exchangeId=body['exchangeId'],
                                     tournamentId=t['id'], limit=200)
        matches = [o for o in rows if matching(body, row['at'], o)]
        if len(matches) != 1 or str(matches[0]['id']) != str(order_id):
            raise ValueError('Require one exact closed-history match with the requested order ID')
        if any(str((r.get('response') or {}).get('orderId')) == str(order_id) for k, r in journal.items() if k != key):
            raise ValueError('Order already belongs to another journal entry')
        order = executor.client.get(f'/orders/{order_id}')
        if str(order['id']) != str(order_id) or not matching(body, row['at'], order):
            raise ValueError('Order detail does not confirm history match')
        fills = executor.client.get(f'/orders/{order_id}/fills', limit=1)
        if (str(fills['orderId']) != str(order_id) or str(fills['exchangeId']) != str(body['exchangeId'])
                or str(fills['tournamentId']) != str(t['id']) or not fills['coverage']['complete']):
            raise ValueError('Fill identity/coverage mismatch')
        qty = finite(fills['totalQuantityFilled'])
        if abs(qty) > body['quantity'] or qty and (qty > 0) != (body['side'] == 'yes'):
            raise ValueError('Fill quantity mismatch')
        if qty:
            price = finite(fills['avgFillPrice'])
            if body['action'] == 'buy' and price > body['price']+1e-9 or body['action'] == 'sell' and price < body['price']-1e-9:
                raise ValueError('Fill beyond original limit')
        evidence = {'at': datetime.now(timezone.utc).isoformat(), 'method': 'unique_closed_history_and_lifecycle',
                    'order': order, 'fills': fills, 'apply': apply, 'previousStatus': row['status'],
                    'placementReplayed': False}
        if apply:
            row['resolution'] = evidence
            row['response'] = {'orderId': int(order_id), 'exchangeId': body['exchangeId'], 'open': False,
                               'reconciledFromHistory': True}
            row['status'] = 'confirmed'
            atomic_json(executor.journal_path, journal)
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', required=True)
    parser.add_argument('--order-id', required=True, type=int)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(resolve(Executor(), args.key, args.order_id, args.apply), indent=2))


if __name__ == '__main__':
    main()
