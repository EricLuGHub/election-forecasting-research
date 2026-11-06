"""E7 one-sided passive-entry pilot. No theoretical maker fills are booked."""
from collections import defaultdict
from datetime import datetime, timezone
import math

from .engine6_value import levels
from research.pilot import PREFIX, instant
from research.risk import finite


def tick(price, up=False):
    return round((math.ceil((price-1e-9)/.005) if up else math.floor((price+1e-9)/.005))*.005, 3)


def reference(raw, side):
    bid, ask = finite(raw['yes_bid_dollars']), finite(raw['yes_ask_dollars'])
    if (raw['status'] != 'active' or not 0 < bid <= ask < 1 or ask-bid > .06+1e-9
            or min(finite(raw['yes_bid_size_fp']), finite(raw['yes_ask_size_fp'])) < 20
            or finite(raw['volume_24h_fp']) < 100):
        raise ValueError('Reference quality gate')
    return (bid, ask) if side == 'yes' else (1-ask, 1-bid)


def entry(book, side, ref, quantity, buffer=.035, min_spread=.02, variant='improve'):
    if not .015 <= buffer <= .1 or not .01 <= min_spread <= .1 or variant not in ('join', 'improve'):
        raise ValueError('Unsafe maker entry parameters')
    bids, asks = levels(book, side, 'sell'), levels(book, side, 'buy')
    if not bids or not asks:
        return None
    bid, ask = bids[0][0], asks[0][0]
    lower, _ = reference(ref, side)
    # 2.5 points of reference/model uncertainty plus 1 point entry edge.
    price = tick(min(bid+(.005 if variant == 'improve' else 0), ask-.005, lower-buffer))
    # Join existing best price when improving it would consume the buffer.
    # Queue priority is unknown; only reported fills will count.
    if ask-bid < min_spread-1e-9 or price < bid-1e-9 or not .005 <= price <= .995:
        return None
    return {'exchangeId': str(book['exchangeId']), 'side': side, 'action': 'buy',
            'price': price, 'quantity': quantity,
            'evidence': {'referenceLower': lower, 'referenceGap': round(lower-price, 6),
                         'externalBid': bid, 'externalAsk': ask, 'referenceBuffer': buffer,
                         'quoteVariant': variant, 'actuallyImproved': price > bid+1e-9,
                         'makerFillAssumed': False}}


def exit_order(book, side, quantity, lot_ceiling, urgent=False):
    bids, asks = levels(book, side, 'sell'), levels(book, side, 'buy')
    if not bids:
        return None
    bid, depth = bids[0]
    if urgent or bid >= lot_ceiling+.01-1e-9:
        price, quantity = bid, min(quantity, int(depth))
    else:
        ask = asks[0][0] if asks else .995
        price = tick(max(lot_ceiling+.01, ask-.005, bid+.005), up=True)
    if quantity < 1 or not .005 <= price <= .995:
        return None
    return {'exchangeId': str(book['exchangeId']), 'side': side, 'action': 'sell',
            'price': price, 'quantity': quantity,
            'evidence': {'urgent': urgent, 'lotCeiling': lot_ceiling, 'externalBid': bid}}


def fill_accounting(fills, journal, scopes, started_at, prefix=PREFIX):
    owned = {str(r['response']['orderId']): r['body'] for key, r in journal.items()
             if key.startswith(prefix) and r['status'] == 'confirmed'}
    lots, quantities, per_order = defaultdict(list), defaultdict(int), defaultdict(int)
    cash, realized, count, bought, sold, seen = 0.0, 0.0, 0, 0, 0, set()
    for row in sorted(fills, key=lambda f: (instant(f['filledAt']), int(f['id']))):
        if instant(row['filledAt']) < instant(started_at):
            continue
        eid = str(row['exchangeId'])
        if eid not in scopes:
            continue
        if row['id'] in seen:
            raise ValueError('Duplicate fill ID')
        seen.add(row['id'])
        order = owned.get(str(row['orderId']))
        if not order:
            raise ValueError('Foreign fill in reserved pilot instrument')
        side, qty, price = row['side'], abs(finite(row['quantity'])), finite(row['price'])
        if (side != scopes[eid]['side'] or order['side'] != side or qty != int(qty) or qty <= 0
                or str(order['exchangeId']) != eid or not 0 < price < 1
                or (finite(row['quantity']) > 0) != (side == 'yes')):
            raise ValueError('Invalid fill identity/quantity/side')
        qty = int(qty)
        per_order[str(row['orderId'])] += qty
        if per_order[str(row['orderId'])] > order['quantity']:
            raise ValueError('Filled more than submitted')
        buying = order['action'] == 'buy'
        if (buying and price > order['price']+1e-9) or (not buying and price < order['price']-1e-9):
            raise ValueError('Fill outside bounded limit')
        if buying:
            lots[eid].append({'quantity': qty, 'price': price, 'at': row['filledAt']})
            quantities[eid] += qty
            cash -= qty*price
            bought += qty
        else:
            if quantities[eid] < qty:
                raise ValueError('Sell exceeds attributable inventory')
            quantities[eid] -= qty
            cash += qty*price
            sold += qty
            remaining = qty
            while remaining:
                lot = lots[eid][0]
                take = min(remaining, lot['quantity'])
                realized += take*(price-lot['price'])
                lot['quantity'] -= take
                remaining -= take
                if not lot['quantity']:
                    lots[eid].pop(0)
        count += 1
    return {'cashFlow': cash, 'realizedGross': realized, 'fillCount': count,
            'boughtShares': bought, 'soldShares': sold, 'quantities': dict(quantities),
            'lots': dict(lots), 'filledByOrder': dict(per_order),
            'signedInventory': {eid: qty*(1 if scopes[eid]['side'] == 'yes' else -1)
                                for eid, qty in quantities.items()}}


def liquidation_value(book, side, quantity):
    value, remaining = 0.0, quantity
    for price, size in levels(book, side, 'sell'):
        take = min(remaining, size)
        value += take*price
        remaining -= take
        if not remaining:
            break
    # Missing depth is worth zero for the pilot stop, never the midpoint.
    return value, remaining
