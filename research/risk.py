"""Shared, pure accounting for signed tournament positions and binary orders."""
import math


def finite(value):
    if isinstance(value, bool):
        raise ValueError('Boolean financial value')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Non-finite financial value')
    return value


def inventory(positions):
    result = {}
    for pos in positions:
        if pos.get('settled'):
            continue
        # Tournament quantity is already signed YES. option can say YES on a NO holding.
        qty = finite(pos['quantity'])
        if qty != int(qty):
            raise ValueError('Fractional tournament position')
        eid = str(pos['exchangeId'])
        result[eid] = result.get(eid, 0) + int(qty)
    return result


def direction(order):
    if order['side'] not in ('yes', 'no') or order['action'] not in ('buy', 'sell'):
        raise ValueError('Invalid order direction')
    return 1 if (order['side'] == 'yes') == (order['action'] == 'buy') else -1


def economic_key(order):
    price = finite(order.get('priceLimit', order.get('price')))
    if not 0 < price < 1:
        raise ValueError('Require a bounded limit order')
    yes_price = price if order['side'] == 'yes' else 1-price
    return str(order['exchangeId']), direction(order), round(yes_price, 8)


def order_capital(order):
    direction(order)
    qty = finite(order['quantity'])
    if qty <= 0:
        raise ValueError('Nonpositive order quantity')
    value = order.get('priceLimit', order.get('price'))
    # Market orders reserve full payout collateral until they are reconciled.
    if value is None or finite(value) in (0, 1):
        return qty
    price = finite(value)
    if not 0 < price < 1:
        raise ValueError('Invalid limit price')
    return qty*(price if order['action'] == 'buy' else 1-price)


def pending_reductions(eid, signed_quantity, orders):
    total = 0
    for order in orders:
        if order.get('open'):
            qty = finite(order['quantity'])
            if qty <= 0 or qty != int(qty):
                raise ValueError('Malformed pending quantity')
            if str(order['exchangeId']) == str(eid) and direction(order)*signed_quantity < 0:
                total += qty
    return total


def is_reduction(order, positions, orders):
    eid = str(order['exchangeId'])
    qty = inventory(positions).get(eid, 0)
    return (direction(order)*qty < 0
            and finite(order['quantity']) <= abs(qty)-pending_reductions(eid, qty, orders))


def gross_capital(positions, orders):
    inventory(positions)  # validate even if a malformed position reports zero cost
    used = 0.0
    for pos in positions:
        if not pos.get('settled'):
            cost = finite(pos['costBasis'])
            if cost < 0:
                raise ValueError('Negative position cost')
            used += cost
    return used + sum(order_capital(o) for o in orders if o.get('open'))


def cost_ceiling(position):
    qty = abs(finite(position['quantity']))
    if not qty:
        raise ValueError('Empty position')
    # Selling is FIFO. The average alone could promise a gain while closing a
    # more expensive lot. Quote above every surviving lot's cost instead.
    return max([finite(position['costBasis'])/qty]
               + [finite(lot['entryPrice']) for lot in position.get('lots', [])])


def held_mark(position):
    """API marketValue is already in the held outcome, including signed NO lots."""
    mark = finite(position['marketValue']) / abs(finite(position['quantity']))
    if not 0 <= mark <= 1:
        raise ValueError('Invalid held-outcome mark')
    return mark


def race_groups(positions, nodes):
    groups, mapping, unknown, parties, invalid = {}, {}, [], {}, set()
    for pos in positions:
        if pos.get('settled') or not finite(pos['quantity']):
            continue
        d = nodes.get(str(pos['marketId']), {}).get('root', {}).get('contract_details', {})
        if (d.get('resolutionType') != 'Party Winner' or not d.get('raceId')
                or not d.get('stageId') or not d.get('winnerName')):
            unknown.append(pos)
            continue
        key = tuple(d.get(k) for k in ('raceId', 'stageId', 'electionDate', 'raceStage'))
        if None in key or d['winnerName'] in parties.setdefault(key, set()):
            invalid.add(key)
        parties[key].add(d['winnerName'])
        mapping[str(pos['exchangeId'])] = key
        groups.setdefault(key, []).append(pos)
    # Unknown contracts may hedge any other holding; do not trade them. Duplicate
    # party contracts invalidate exclusivity proof for their entire race.
    for key in invalid:
        for pos in groups.pop(key):
            mapping.pop(str(pos['exchangeId']), None)
    return groups, mapping


def settlement_floor(positions):
    quantities = [finite(p['quantity']) for p in positions]
    no_total = sum(max(0, -q) for q in quantities)
    return min([no_total] + [no_total+q for q in quantities])


def floor_safe_quantity(group, eid, sell_price, maximum, fee=0):
    """Sale cash + remaining exclusive-winner floor must not reduce the floor.

    Includes the unlisted-winner scenario; never assumes R/D exhaustiveness.
    Caller must establish identical contest/stage and unique parties first.
    """
    before = settlement_floor(group)
    target = next(p for p in group if str(p['exchangeId']) == str(eid))
    lo, hi = 0, min(int(maximum), abs(int(target['quantity'])))
    while lo < hi:
        qty = (lo+hi+1)//2
        after = [dict(p, quantity=p['quantity']-(qty if p['quantity'] > 0 else -qty))
                 if str(p['exchangeId']) == str(eid) else p for p in group]
        if settlement_floor(after)+qty*(sell_price-fee) >= before-1e-9:
            lo = qty
        else:
            hi = qty-1
    return lo
