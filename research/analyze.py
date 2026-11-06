"""Audit executable prices, logical baskets and external-reference discrepancies."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
import json
import math
from statistics import median
from .client import ROOT, save_json
from .pricing import buy_levels, sweep


def load_latest(name):
    return json.loads(open(json.loads((ROOT / f'data/{name}.json').read_text())['path']).read())


def race_groups(snapshot):
    groups = defaultdict(list)
    for market in snapshot['markets']:
        if market.get('status', 'open') != 'open':
            continue
        root = snapshot['nodes'].get(market['id'], {}).get('root', {})
        details = root.get('contract_details', {})
        if (root.get('node_type') != 'contract' or details.get('resolutionType') != 'Party Winner'
                or not details.get('raceId') or not details.get('stageId') or len(market['exchanges']) != 1):
            continue
        # IDs and dates, not title similarity, establish a shared contest.
        key = (details['raceId'], details['stageId'], details.get('electionDate'), details.get('raceStage'))
        groups[key].append({'marketId': market['id'], 'exchangeId': market['exchanges'][0]['id'],
                            'party': details['winnerName'], 'race': details.get('raceName'),
                            'title': market['title']})
    return groups


def basket(books, legs, min_payout, fee):
    levels = [buy_levels(books[x['exchangeId']], x['side']) for x in legs]
    if any(not x for x in levels):
        return None
    # Evaluate at every depth breakpoint; retain the most profitable full basket.
    max_quantity = min(sum(q for _, q in x) for x in levels)
    quantities = {max_quantity}
    for ls in levels:
        cum = 0
        for _, q in ls:
            cum += q
            if cum <= max_quantity:
                quantities.add(cum)
    best = None
    for quantity in sorted(quantities):
        fills = [sweep(books[x['exchangeId']], x['side'], quantity) for x in legs]
        cost = sum(f['cost'] for f in fills)
        net = quantity * min_payout - cost - fee * quantity * len(legs)
        if net > 1e-8 and (best is None or net > best['minimumNetPayoutMinusCost']):
            best = {'quantityEach': quantity, 'cost': round(cost, 6), 'minimumPayout': min_payout * quantity,
                    'minimumNetPayoutMinusCost': round(net, 6), 'legs': legs, 'fills': fills}
    return best


def analyze(snapshot, external=None, fee=0.0, uncertainty=0.03):
    books = snapshot['books']
    markets = {m['id']: m for m in snapshot['markets']}
    groups = race_groups(snapshot)
    result = {'snapshotStartedAt': snapshot['startedAt'], 'snapshotCompletedAt': snapshot.get('completedAt'),
              'tournamentStatus': snapshot['tournament']['status'], 'marketCount': len(markets),
              'bookCount': len(books), 'errors': snapshot['errors'], 'feePerShareAssumption': fee,
              'uncertaintyHaircut': uncertainty, 'raceGroups': len(groups),
              'groupSizes': dict(Counter(len(v) for v in groups.values())),
              'logicalCandidates': [], 'conditionalCoverageCandidates': [], 'externalComparisons': [],
              'spreads': {}, 'notes': [
                  'Historical sequential scan: prices must be refreshed before any execution.',
                  'Logical bounds assume consistent binary settlement; refunds and settlement mismatches can break them.',
                  'External discrepancies are model signals; SUSQies cannot hedge real-money venue positions.',
                  'Uncertainty haircut is an illustrative sensitivity parameter, not a calibrated confidence interval.',
              ]}
    spreads = [b['bestAsk'] - b['bestBid'] for b in books.values() if b['bestAsk'] is not None and b['bestBid'] is not None]
    result['spreads'] = {'twoSided': len(spreads), 'oneSidedOrEmpty': len(books)-len(spreads),
                         'median': median(spreads) if spreads else None,
                         'distribution': dict(Counter(round(v, 3) for v in spreads))}
    for key, group in groups.items():
        if len(group) < 2 or len({r['party'] for r in group}) != len(group):
            continue
        if any(x['exchangeId'] not in books for x in group):
            continue
        # Every subset of exclusive winners has at most one YES. All-NO basket
        # therefore pays at least n-1, including if an unlisted third party wins.
        for n in range(2, len(group)+1):
            for subset in combinations(group, n):
                legs = [dict(x, side='no') for x in subset]
                found = basket(books, legs, n-1, fee)
                if found:
                    result['logicalCandidates'].append(dict(found, type='exclusive_winners_buy_no', race=group[0]['race'], raceKey=key))
        # Buying every listed YES is only a hedge if that set is exhaustive.
        found = basket(books, [dict(x, side='yes') for x in group], 1, fee)
        if found:
            result['conditionalCoverageCandidates'].append(dict(found, race=group[0]['race'],
                warning='NOT GUARANTEED: an unlisted winner can make every YES lose; exhaustiveness unverified.'))
    if external:
        midpoint_differences = []
        for mid, ref in external['references'].items():
            if mid not in markets or not ref['quoteValid']:
                continue
            market = markets[mid]
            if market.get('status') != 'open' or len(market['exchanges']) != 1:
                continue
            eid = market['exchanges'][0]['id']
            if eid not in books:
                continue
            book = books[eid]
            if book['bestBid'] is not None and book['bestAsk'] is not None:
                midpoint_differences.append(abs((book['bestBid'] + book['bestAsk']) / 2 - ref['mid']))
            for side in ('yes', 'no'):
                levels = buy_levels(book, side)
                if not levels:
                    continue
                cost, size = levels[0]
                p = ref['mid'] if side == 'yes' else 1-ref['mid']
                # Use the far side of the reference spread and an explicit haircut.
                lower = ref['bid'] if side == 'yes' else 1-ref['ask']
                buffer_edge = lower - uncertainty - cost - fee
                item = {'marketId': mid, 'exchangeId': eid, 'title': market['title'], 'side': side,
                        'sigCost': round(cost, 6), 'topQuantity': size, 'referenceMid': p,
                        'referenceBid': ref['bid'], 'referenceAsk': ref['ask'],
                        'rawEdge': round(p-cost-fee, 6), 'bufferedEdge': round(buffer_edge, 6),
                        'referenceTicker': ref['ticker'], 'mappingStatus': ref['mappingStatus'],
                        'referenceVolume24h': ref['volume24h'], 'referenceReceivedAt': ref['receivedAt'],
                        'sigReceivedAt': book['receivedAt']}
                result['externalComparisons'].append(item)
        result['externalComparisons'].sort(key=lambda x: x['bufferedEdge'], reverse=True)
        result['externalCoverage'] = {
            'candidateMappings': len(external['references']),
            'validReferenceQuotes': sum(r['quoteValid'] for r in external['references'].values()),
            'unmatched': len(external['missing']), 'errors': external['errors'],
            'twoSidedMidpointComparisons': len(midpoint_differences),
            'medianAbsoluteMidpointDifference': median(midpoint_differences) if midpoint_differences else None,
            'withinHalfPoint': sum(d <= .005 + 1e-9 for d in midpoint_differences),
            'positiveBufferedSideComparisons': sum(r['bufferedEdge'] > 0 for r in result['externalComparisons']),
        }
    result['logicalCandidates'].sort(key=lambda x: x['minimumNetPayoutMinusCost'], reverse=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot')
    parser.add_argument('--fee', type=float, default=0.0, help='Assumed SIG fee per share per leg; not independently verified')
    parser.add_argument('--uncertainty', type=float, default=.03, help='Illustrative probability haircut')
    args = parser.parse_args()
    if not math.isfinite(args.fee) or args.fee < 0 or not 0 <= args.uncertainty <= 1:
        parser.error('Invalid fee or uncertainty')
    s = json.loads(open(args.snapshot).read()) if args.snapshot else load_latest('latest')
    e = load_latest('external_latest') if (ROOT / 'data/external_latest.json').exists() else None
    result = analyze(s, e, args.fee, args.uncertainty)
    save_json(ROOT / 'data/analysis.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('externalComparisons', 'conditionalCoverageCandidates')}, indent=2))
    print('Conditional YES baskets (not guaranteed):', len(result['conditionalCoverageCandidates']))
    print('Largest external-reference gaps (not approved trading signals):')
    for row in result['externalComparisons'][:15]:
        print(row['marketId'], row['side'], row['sigCost'], 'external', round(row['referenceMid'],4),
              'buffered', row['bufferedEdge'], row['title'])


if __name__ == '__main__':
    main()
