"""E8 convergence-exit watcher (paper only). Never places orders.

For each E2 basket in data/e2_taken.json, values the JOINT early exit at
live depth (sell both NO legs into NO bids = 1 - YES asks) and flags when
joint proceeds >= cost + 0.5c/share (the bankable-exit bar from cycle 14).
Whole-basket only; single-leg values never fire. Read-only; the live exit
decision stays with E1-REDUCE per regime.

Engine ID: E8-CONVEXIT v1. Review: 7 days or first 3 flags scored.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from .client import ROOT, Client
from .exit import depth_proceeds

BANK_PER_SHARE = 0.005


def load_baskets(path=None):
    """(name, (eid_r, eid_d), size, cost) for ledger baskets with floors.

    Leg exchange IDs resolve via the markets catalog (race titles), sizes and
    costs come from the taken ledger. Skips entries it cannot resolve.
    """
    ledger = json.loads((ROOT / 'data/e2_taken.json').read_text())
    out = []
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
        out.append((name, race, size, float(cost)))
    return out


STATEMAP = {'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
            'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut',
            'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii',
            'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
            'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine',
            'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan',
            'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
            'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
            'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
            'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
            'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania',
            'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota',
            'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
            'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
            'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'}


def parse_race(race):
    """(state_name, office, district|None) or (None, None, None).

    Accepts 'OK Senate', 'CA-Gov', 'VA-05', 'WI-03 R/D NO x1000', etc.
    Unknown state codes and unknown offices refuse explicitly.
    """
    import re
    up = race.upper().replace('-', ' ')
    m = re.match(r'^([A-Z]{2})(?:\s+(\d+))?\s', up)
    if not m:
        return None, None, None
    place = STATEMAP.get(m.group(1))
    if not place:
        return None, None, None
    district = '%s-%s' % (m.group(1), m.group(2)) if m.group(2) else None
    office = None
    if re.search(r'\bSENATE\b', up):
        office = 'Senate'
    elif re.search(r'\bGOV(ERNOR)?\b', up):
        office = 'Governor'
    elif re.search(r'\bHOUSE\b', up) or district:
        office = 'House race'
    if office is None:
        return None, None, None
    return place, office, district


def race_pair(client, tid, race):
    """(eid_r, eid_d) with strict identity, else None.

    Requires: known state, known office, exactly one Republican and one
    Democratic catalog match containing place + office (+ district). Control
    races (no state name) can never match. Ambiguity refuses loudly.
    """
    place, office, district = parse_race(race)
    if not place or not office:
        return None
    mkts = client.pages('/markets', limit=100, tournamentId=tid)
    found = {'Republican': [], 'Democratic': []}
    for mk in mkts:
        t = mk.get('title', '')
        if district:
            if district not in t:
                continue
        elif place not in t or office not in t:
            continue
        ex = (mk.get('exchanges') or [{}])[0].get('id')
        if 'Republican' in t:
            found['Republican'].append(str(ex))
        elif 'Democratic' in t:
            found['Democratic'].append(str(ex))
    if len(found['Republican']) == 1 and len(found['Democratic']) == 1:
        return found['Republican'][0], found['Democratic'][0]
    return None


def joint_exit(client, tid, eid_r, eid_d, size):
    """Joint NO-sell proceeds for size×2, or None when depth insufficient."""
    total = 0.0
    for eid in (eid_r, eid_d):
        book = client.get(f'/exchanges/{eid}/orderbook', tournamentId=tid, depth=50)
        got = depth_proceeds(book, 'no', size)
        if got is None:
            return None
        total += got
    return total


MIN_EDGE_ABS = 5.0  # bankable needs >= $5 absolute, not just per-share rate
OWN_PREFIXES = ('Q4-', 'ROT-', 'NH-', 'SHELF-', 'ROT2-', 'ROT3-', 'ROT4-', 'ROT5-', 'ROT6-')


def exit_qty(paired, size):
    """Shares per leg actually exitable now (whole pairs only)."""
    try:
        q = min(float(paired), float(size))
    except (TypeError, ValueError):
        return 0
    return int(q) if q > 0 else 0


def own_resting(open_orders, eids):
    """Our-prefix resting quantities per eid (compete for the same depth)."""
    out = {}
    for order in open_orders or []:
        try:
            key = str(order.get('idempotencyKey', ''))
            eid = str(order.get('exchangeId'))
            qty = abs(float(order.get('quantity', 0)))
        except (TypeError, ValueError, AttributeError):
            continue
        if eid in eids and key.startswith(OWN_PREFIXES) and order.get('open'):
            out[eid] = out.get(eid, 0.0) + qty
    return out


def scan(client=None):
    client = client or Client()
    tid = client.get('/tournaments', slug='midterm-elections')['data'][0]['id']
    positions = client.get('/tournaments/midterm-elections/portfolio/positions')
    positions = positions.get('positions', positions)
    if not isinstance(positions, list):
        positions = []
    try:
        open_orders = client.pages('/orders', status='open', limit=50, tournamentId=tid)
    except (RuntimeError, OSError, ValueError, KeyError):
        open_orders = []
    from .reconcile import reconcile
    ledger = json.loads((ROOT / 'data/e2_taken.json').read_text())
    paired_map = {r['basket']: r for r in
                  reconcile(ledger, positions, lambda race: race_pair(client, tid, race))}
    basket_eids = set()
    for row in paired_map.values():
        for eid in (row.get('legs') or {}):
            basket_eids.add(str(eid))
    resting = own_resting(open_orders if isinstance(open_orders, list) else [], basket_eids)
    rows = []
    for name, race, size, cost in load_baskets():
        pair = race_pair(client, tid, race)
        if not pair:
            rows.append({'basket': name, 'state': 'unresolved'})
            continue
        rec = paired_map.get(name, {})
        q = exit_qty(rec.get('paired', 0), size)
        if q <= 0:
            rows.append({'basket': name, 'state': 'depleted',
                         'paired': rec.get('paired', 0)})
            continue
        try:
            proceeds = joint_exit(client, tid, pair[0], pair[1], q)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            rows.append({'basket': name, 'state': 'error', 'reason': str(exc)[:120]})
            continue
        if proceeds is None:
            rows.append({'basket': name, 'state': 'thin'})
            continue
        edge = proceeds - cost * q / size
        per_share = edge / (2 * q)
        per_unit = edge / q
        bankable = per_share >= BANK_PER_SHARE and edge >= MIN_EDGE_ABS
        rows.append({'basket': name, 'state': 'BANKABLE' if bankable else 'hold',
                     'exited_qty': q, 'proceeds': round(proceeds, 2),
                     'cost': round(cost * q / size, 2),
                     'edge': round(edge, 2), 'per_share': round(per_share, 4),
                     'per_unit': round(per_unit, 4),
                     'own_resting': {e: resting.get(e, 0) for e in pair}})
    return rows


def format_row(row):
    """One complete JSON object per line. Never truncate: c185 found the
    old [:220] slice cut `at` timestamps and `own_resting` off long rows,
    making trajectories unbuildable for exactly the interesting baskets."""
    return json.dumps(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loop', type=float, default=0)
    args = parser.parse_args()
    while True:
        try:
            for row in scan():
                row['at'] = datetime.now(timezone.utc).isoformat()
                print(format_row(row), flush=True)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            print(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                              'state': 'error', 'reason': str(exc)[:150]}), flush=True)
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == '__main__':
    main()
