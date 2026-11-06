"""Cancel legacy E1 orders identified by returned IDs in its submission log.

Default is a preview. No price/title guessing and no account-wide cancel-all.
"""
import argparse
import json
import re
from datetime import datetime, timezone

from .client import ROOT
from .execution import Executor
from .monitor import atomic_json
from .risk import inventory, finite


def legacy_ids(path=None):
    path = path or ROOT / 'data/e1run.log'
    if not path.exists():
        return set()
    with path.open() as handle:
        return {int(match.group(1)) for line in handle
                if (match := re.search(r'SUBMIT[^\n]*?"orderId":\s*(\d+)', line))}


def cancel_legacy(executor, path=None):
    tournament = executor.preflight()
    rows = executor.client.pages('/orders', status='open', limit=100, tournamentId=tournament['id'])
    owned = legacy_ids(path)
    result = {'at': datetime.now(timezone.utc).isoformat(), 'dryRun': executor.dry_run,
              'targetIds': [o['id'] for o in rows if int(o['id']) in owned], 'results': []}
    for oid in result['targetIds']:
        response = executor.cancel_order(oid)
        result['results'].append({'orderId': oid, 'response': response})
        atomic_json(ROOT / 'data/recovery/legacy-cancellations.json', result)
    return result


def exposure_changes(before, after):
    prior, current = inventory(before), inventory(after)
    return [{'exchangeId': eid, 'before': prior.get(eid, 0), 'after': current.get(eid, 0),
             'increasedOrFlipped': (abs(current.get(eid, 0)) > abs(prior.get(eid, 0))
                                   or current.get(eid, 0)*prior.get(eid, 0) < 0)}
            for eid in sorted(set(prior) | set(current)) if prior.get(eid, 0) != current.get(eid, 0)]


def audit(executor):
    """Read-only lifecycle-fill and account comparison; no profitability inference."""
    account = executor.reconcile()
    before = json.loads((ROOT / 'data/recovery/pre-live.json').read_text())
    changes = exposure_changes(before['positions']['positions'], account['positions']['positions'])
    journal = {key: row for key, row in executor.journal().items() if key.startswith('E1R-')}
    fills, errors = [], []
    for row in journal.values():
        if row['status'] != 'confirmed':
            continue
        body = row['body']
        oid = row['response']['orderId']
        try:
            data = executor.client.get(f'/orders/{oid}/fills', limit=1)
            if (str(data['orderId']) != str(oid) or str(data['exchangeId']) != body['exchangeId']
                    or data['tournamentId'] != body['tournamentId'] or not data['coverage']['complete']):
                raise ValueError('Fill identity/coverage mismatch')
            signed = finite(data['totalQuantityFilled'])
            if signed and (signed > 0) != (body['side'] == 'yes'):
                raise ValueError('Unexpected fill outcome sign')
            qty = abs(signed)
            if qty > body['quantity']:
                raise ValueError('Filled more than submitted')
            price = finite(data['avgFillPrice']) if qty else None
            if price is not None and price+1e-9 < body['price']:
                raise ValueError('Sell fill below limit')
            cost = row['riskProof']['costCeiling']
            fills.append({'orderId': oid, 'exchangeId': body['exchangeId'], 'side': body['side'],
                          'quantity': qty, 'averagePrice': price,
                          'grossGainLowerBoundBeforeFees': qty*(price-cost) if qty else 0})
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            errors.append({'orderId': oid, 'error': str(exc)[:300]})
    events = []
    path = ROOT / 'data/recovery/events.jsonl'
    if path.exists():
        with path.open() as handle:
            for line in handle:
                event = json.loads(line)
                if event.get('mode') == 'live_reduce_only' and event['event'] == 'cycle':
                    events.append(event)
    result = {'at': datetime.now(timezone.utc).isoformat(), 'pnl': account['pnl'],
              'baselinePnl': before['pnl'], 'cyclesObserved': len(events),
              'firstCycleAt': events[0]['at'] if events else None,
              'lastCycleAt': events[-1]['at'] if events else None,
              'positionsChanged': changes,
              'increasedOrFlipped': [r for r in changes if r['increasedOrFlipped']],
              'unknownPlacements': sum(r['status'] != 'confirmed' for r in journal.values()),
              'submittedOrders': len(journal), 'openOrders': account['openOrders'],
              'filledShares': sum(r['quantity'] for r in fills),
              'grossGainLowerBoundBeforeFees': round(sum(r['grossGainLowerBoundBeforeFees'] for r in fills), 4),
              'fills': fills, 'errors': errors,
              'interpretation': 'Operational evidence only. Account P&L includes unrelated mark changes; strategy profitability unproven.'}
    atomic_json(ROOT / 'data/recovery/audit.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--audit', action='store_true', help='Read-only recovery/fill evaluation; never cancels')
    args = parser.parse_args()
    exe = Executor(dry_run=not args.live)
    print(json.dumps(audit(exe) if args.audit else cancel_legacy(exe), indent=2))


if __name__ == '__main__':
    main()
