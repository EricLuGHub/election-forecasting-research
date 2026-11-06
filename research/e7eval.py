"""Read-only E7 execution evidence. No scaling decisions or assumed fills."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean

from .client import ROOT
from .engines.engine7_maker import liquidation_value
from .monitor import atomic_json
from .pilot import PREFIX, instant


def evaluate(config, fills, journal, observations, now=None):
    now = now or datetime.now(timezone.utc)
    owned = {str(r['response']['orderId']): r['body'] for k, r in journal.items()
             if k.startswith(config.get('prefix', PREFIX)) and r['status'] == 'confirmed'}
    fills = [f for f in fills if str(f['orderId']) in owned and instant(f['filledAt']) >= instant(config['startedAt'])]
    quantity, round_trips = {}, 0
    for f in sorted(fills, key=lambda r: (instant(r['filledAt']), r['id'])):
        eid, order = str(f['exchangeId']), owned[str(f['orderId'])]
        before = quantity.get(eid, 0)
        quantity[eid] = before+abs(f['quantity'])*(1 if order['action'] == 'buy' else -1)
        if before > 0 and quantity[eid] == 0:
            round_trips += 1
    result = {'at': now.isoformat(), 'phase': 'awaiting_observations', 'strategyValidated': False,
              'confirmedOrders': len(owned), 'actualFillRecords': len(fills), 'completedRoundTrips': round_trips,
              'hoursSinceInitialization': max(0, (now-instant(config['startedAt'])).total_seconds()/3600),
              'limitations': ['Entry markouts are later executable quotes, not realized exits.',
                              'A short trial and small fills cannot establish competitive capacity.',
                              'Reported gross results exclude any unmodeled fees; stress is an assumption.']}
    if not observations:
        return result
    observations = sorted(observations, key=lambda o: instant(o['at']))
    last = observations[-1]
    accounting = last['accounting']
    value, residual = accounting['cashFlow'], 0
    for eid, qty in accounting['quantities'].items():
        amount, unpriced = liquidation_value(last['observations'][eid]['book'], config['exchanges'][eid]['side'], qty)
        value += amount
        residual += unpriced
    age = (now-instant(last['at'])).total_seconds()
    result.update(phase='observed', quoteObservedAt=last['at'], ageSeconds=age, stale=not 0 <= age <= 180,
                  realizedGross=accounting['realizedGross'], liquidationGross=value, unpricedInventory=residual,
                  stressedLiquidationGross=value-.005*(accounting['boughtShares']+accounting['soldShares']
                                                        +sum(accounting['quantities'].values())))
    outcomes = {}
    for horizon in (300, 900, 1800):
        marks = []
        for f in fills:
            order = owned[str(f['orderId'])]
            if order['action'] != 'buy':
                continue
            eid, quantity = str(f['exchangeId']), abs(f['quantity'])
            target = instant(f['filledAt']).timestamp()+horizon
            eligible = [o['observations'][eid] for o in observations if eid in o['observations']
                        and target <= instant(o['observations'][eid]['bookAt']).timestamp() <= target+300]
            if not eligible:
                continue
            later = min(eligible, key=lambda o: instant(o['bookAt']))
            amount, missing = liquidation_value(later['book'], order['side'], quantity)
            marks.append({'fillId': f['id'], 'quantity': quantity, 'at': later['bookAt'],
                          'netPerShareBeforeFees': amount/quantity-f['price'], 'unpricedShares': missing,
                          'delayAfterTargetSeconds': instant(later['bookAt']).timestamp()-target})
        shares = sum(m['quantity'] for m in marks)
        outcomes[str(horizon)] = {'observedEntryFills': len(marks), 'shares': shares,
                    'quantityWeightedMarkout': sum(m['quantity']*m['netPerShareBeforeFees'] for m in marks)/shares if shares else None,
                    'meanDelaySeconds': mean(m['delayAfterTargetSeconds'] for m in marks) if marks else None,
                    'marks': marks}
    result['forwardEntryMarkouts'] = outcomes
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'data/e7')
    args = parser.parse_args()
    directory = args.directory
    config = json.loads((directory/'config.json').read_text())
    fills = json.loads((directory/'fills.json').read_text())['fills'] if (directory/'fills.json').exists() else []
    journal = json.loads((ROOT/'data/execution_journal.json').read_text())
    path = directory/'observations.jsonl'
    observations = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    result = evaluate(config, fills, journal, observations)
    atomic_json(directory/'evaluation.json', result)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
