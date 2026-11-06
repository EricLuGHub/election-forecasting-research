"""Chronological, quote-only SIG/reference convergence study. Never places orders.

No maker fills, midpoint executions, best-future exits, or independent-sample
claims. Entry at the ask, exit at a later bid, with one tick stress each way.
Historical top quotes have no size: this cannot establish deployable capacity.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime
import gzip
import json
from pathlib import Path
from statistics import mean, median

from .client import ROOT
from .external import event_for_title
from .monitor import atomic_json
from .risk import finite


def stamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timezone required')
    return dt.timestamp()


def valid_reference(row, strict):
    bid, ask = finite(row['yes_bid_dollars']), finite(row['yes_ask_dollars'])
    size = min(finite(row['yes_bid_size_fp']), finite(row['yes_ask_size_fp']))
    volume = finite(row['volume_24h_fp'])
    return (row['status'] == 'active' and 0 < bid <= ask < 1
            and ask-bid <= (.06 if strict else .10)+1e-9
            and size >= (20 if strict else 1) and volume >= (100 if strict else 0))


def matched_quotes(sig, reference_history, strict=True):
    references = sorted(reference_history, key=lambda r: stamp(r['completedAt']))
    times = [stamp(r['completedAt']) for r in references]
    rows, failures = [], defaultdict(int)
    for raw in sig:
        mapping = event_for_title(raw['title'])
        if not mapping or mapping[0].startswith(('CONTROLH-', 'CONTROLS-')):
            continue
        at = stamp(raw['at'])
        index = bisect_right(times, at)-1
        if index < 0:
            failures['no_prior_reference'] += 1
            continue
        observation = references[index]
        # Ref acquisition happened within this earlier completed cycle. Bound
        # age from cycle start, not just its later completion timestamp.
        if at-stamp(observation['at']) > 300 or times[index]-stamp(observation['at']) > 180:
            failures['stale_reference'] += 1
            continue
        ref = observation['refs'].get('-'.join(mapping))
        if not ref:
            failures['missing_reference'] += 1
            continue
        try:
            if not valid_reference(ref, strict):
                failures['reference_quality'] += 1
                continue
            bid, ask = finite(raw['sig_bid']), finite(raw['sig_ask'])
            if not 0 < bid < ask < 1:
                raise ValueError('Invalid SIG book')
            rb, ra = finite(ref['yes_bid_dollars']), finite(ref['yes_ask_dollars'])
        except (ValueError, KeyError, TypeError):
            failures['invalid_values'] += 1
            continue
        rows.append(dict(raw, time=at, race=mapping[0], bid=bid, ask=ask, refBid=rb, refAsk=ra))
    return rows, dict(failures)


def study(sig, reference_history, horizon=3600, threshold=.05, strict=True, stress=.005):
    matched, exclusions = matched_quotes(sig, reference_history, strict)
    raw_series = defaultdict(list)
    for row in sig:
        raw_series[str(row['exchangeId'])].append(row)
    for series in raw_series.values():
        series.sort(key=lambda r: stamp(r['at']))
    times = {eid: [stamp(r['at']) for r in rows] for eid, rows in raw_series.items()}
    all_times = sorted({stamp(r['at']) for r in sig})
    if not all_times:
        return {'trades': [], 'summary': {'count': 0}}
    split = (all_times[0]+all_times[-1])/2
    candidates = []
    for row in matched:
        for side, edge in (('yes', row['refBid']-row['ask']), ('no', row['bid']-row['refAsk'])):
            if edge+1e-9 >= threshold:
                candidates.append(dict(row, side=side, edge=edge))
    candidates.sort(key=lambda r: (r['time'], -r['edge'], r['exchangeId'], r['side']))
    busy, trades, seen = {}, [], set()
    for row in candidates:
        at, race, eid = row['time'], row['race'], str(row['exchangeId'])
        if busy.get(race, 0) > at or (at, race) in seen:
            continue
        series = raw_series[eid]
        index = bisect_left(times[eid], at+horizon)
        if index == len(series) or times[eid][index] > at+horizon+900:
            continue
        future = series[index]
        fb, fa = finite(future['sig_bid']), finite(future['sig_ask'])
        if not 0 < fb < fa < 1:
            continue
        entry = row['ask'] if row['side'] == 'yes' else 1-row['bid']
        exit_price = fb if row['side'] == 'yes' else 1-fa
        # Trades crossing the train/test boundary are neither training nor test.
        partition = 'validation' if at >= split else ('training' if times[eid][index] < split else 'boundary')
        pnl = exit_price-entry-2*stress
        trades.append({'enteredAt': row['at'], 'exitedAt': future['at'], 'exchangeId': eid,
                       'race': race, 'title': row['title'], 'side': row['side'],
                       'referenceEdge': round(row['edge'], 6), 'entryAsk': entry,
                       'exitBid': exit_price, 'netPerShare': round(pnl, 6),
                       'returnOnEntry': pnl/(entry+stress), 'partition': partition})
        busy[race] = times[eid][index]
        seen.add((at, race))

    def describe(rows):
        return {'count': len(rows), 'uniqueRaces': len({r['race'] for r in rows}),
                'meanNetPerShare': mean(r['netPerShare'] for r in rows) if rows else None,
                'medianNetPerShare': median(r['netPerShare'] for r in rows) if rows else None,
                'positiveFraction': mean(r['netPerShare'] > 0 for r in rows) if rows else None,
                'sumEqualSharePnl': sum(r['netPerShare'] for r in rows)}

    return {'horizonSeconds': horizon, 'threshold': threshold, 'strictReference': strict,
            'stressPerSide': stress, 'matchedQuoteRows': len(matched), 'exclusions': exclusions,
            'chronologicalSplit': datetime.fromtimestamp(split, datetime.fromisoformat(sig[0]['at']).tzinfo).isoformat(),
            'training': describe([r for r in trades if r['partition'] == 'training']),
            'validation': describe([r for r in trades if r['partition'] == 'validation']),
            'all': describe(trades), 'trades': trades,
            'limitations': ['Top quote sizes and fill probability are unavailable; no deployable P&L/capacity estimate.',
                            'Candidate settlement mappings are not exact arbitrage equivalents.',
                            'Nonoverlapping trades within a race remain correlated across races.',
                            'Predeclared parameter grid is diagnostic, not a fitted or validated live strategy.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'data/top20')
    args = parser.parse_args()
    with (args.directory/'e3paper.log').open() as handle:
        sig = [json.loads(line) for line in handle]
    with gzip.open(args.directory/'reference-history.json.gz', 'rt') as handle:
        refs = json.load(handle)
    results = [study(sig, refs, horizon=horizon, threshold=edge, strict=strict)
               for horizon in (1800, 3600, 7200) for edge in (.02, .05, .10) for strict in (True, False)]
    atomic_json(args.directory/'convergence-study.json', results)
    print(json.dumps([{k:v for k,v in r.items() if k not in ('trades','limitations','exclusions')}
                      for r in results], indent=2))


if __name__ == '__main__':
    main()
