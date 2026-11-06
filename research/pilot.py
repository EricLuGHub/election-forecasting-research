"""Narrow opening permit for the E7 maker pilot; recovery stays on globally."""
from datetime import datetime, timedelta, timezone
import json
import re

from .risk import finite, inventory, order_capital

PREFIX = 'E7M-'


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc)


def mode(path):
    return json.loads(path.read_text()) if path.exists() else {}


def reservations(path):
    # Ownership survives permit expiry: E1 must not take over E7 inventory.
    return set(mode(path).get('openingPermit', {}).get('reservedExchangeIds', []))


def trial_scope(permit):
    """Validate v2's immutable per-race reservations and frozen legacy holdings."""
    if not re.fullmatch(r'E7T-[0-9a-f]{12}-', permit.get('prefix', '')):
        raise ValueError('Invalid trial prefix')
    scopes, reserved = permit['exchanges'], set(permit['reservedExchangeIds'])
    baseline = permit.get('baselineInventory', {})
    if (not isinstance(baseline, dict)
            or set(baseline) != reserved-set(scopes)):
        raise ValueError('Invalid trial prefix/baseline scope')
    groups = []
    for eid, spec in scopes.items():
        group = set(spec['raceExchangeIds'])
        if eid not in group or not group <= reserved or group & (set(scopes)-{eid}):
            raise ValueError('Invalid trial race reservation')
        if any(group & other for other in groups):
            raise ValueError('Trial races must be disjoint')
        groups.append(group)
    if set().union(*groups) != reserved or any(type(q) is not int for q in baseline.values()):
        raise ValueError('Invalid frozen inventory')
    return baseline


def verify_baseline(permit, quantities):
    baseline = trial_scope(permit) if permit.get('version') == 2 else {
        e: 0 for e in set(permit['reservedExchangeIds'])-set(permit['exchanges'])}
    if any(quantities.get(e, 0) != q for e, q in baseline.items()):
        raise ValueError('Other race holding changed from frozen baseline')
    return baseline


def opening_proof(order, account, permit, now=None):
    now = now or datetime.now(timezone.utc)
    prefix = permit.get('prefix', '')
    if (permit.get('version') not in (1, 2) or (permit['version'] == 1 and prefix != PREFIX)
            or not permit.get('entryEnabled') or now >= instant(permit['expiresAt'])):
        raise ValueError('Pilot opening permit disabled or expired')
    if not prefix or not order.get('idempotencyKey', '').startswith(prefix) or order['action'] != 'buy':
        raise ValueError('Not a permitted pilot opening')
    eid = str(order['exchangeId'])
    scopes = permit['exchanges']
    if not 1 <= len(scopes) <= 3 or eid not in scopes or order['side'] != scopes[eid]['side']:
        raise ValueError('Outside pilot instrument/side scope')
    expiry = instant(order['expirationDate'])
    if not now < expiry <= min(instant(permit['expiresAt']), now+timedelta(seconds=180)):
        raise ValueError('Pilot orders require short expiry within permit')
    maximum = finite(permit['maxCapital'])
    if not 0 < maximum <= 1000 or not 1 <= order['quantity'] <= min(200, scopes[eid]['maxShares']):
        raise ValueError('Invalid pilot size/capital bounds')
    positions, orders = account['positions']['positions'], account['openOrders']
    quantities = inventory(positions)
    reserved = set(permit['reservedExchangeIds'])
    if not set(scopes) <= reserved:
        raise ValueError('Pilot scopes must reserve their instruments')
    verify_baseline(permit, quantities)
    busy_scope = set(scopes[eid]['raceExchangeIds']) if permit['version'] == 2 else reserved
    if any(str(o['exchangeId']) in busy_scope for o in orders if o['open']):
        raise ValueError('Pending order already reserves pilot race')
    if quantities.get(eid, 0):
        raise ValueError('Pilot opening requires flat instrument')
    for e, spec in scopes.items():
        if not 1 <= spec['maxShares'] <= 500 or spec['side'] not in ('yes', 'no'):
            raise ValueError('Invalid pilot scope')
        qty = quantities.get(e, 0)
        if abs(qty) > spec['maxShares'] or qty and (qty > 0) != (spec['side'] == 'yes'):
            raise ValueError('Pilot inventory outside scope')
    used = sum(finite(p['costBasis']) for p in positions if not p.get('settled') and str(p['exchangeId']) in scopes)
    used += sum(order_capital(o) for o in orders if o['open'] and str(o['exchangeId']) in scopes)
    if used+order_capital(order) > maximum+1e-9:
        raise ValueError('Pilot capital cap exceeded')
    return {'pilotPrefix': prefix, 'capitalBefore': used, 'capitalAfter': used+order_capital(order),
            'maxCapital': maximum, 'expiresAt': permit['expiresAt']}
