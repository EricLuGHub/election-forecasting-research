"""Fresh, read-only trial audit. Never extends a permit or submits orders."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .e6data import exclude_own_liquidity
from .e7eval import evaluate
from .e7run import recent_fills
from .engines.engine7_maker import fill_accounting
from .execution import Executor
from .monitor import atomic_json
from .pilot import verify_baseline
from .risk import inventory
from .trial import DIRECTORY


def audit(exe, directory, lifecycle=False):
    directory = Path(directory)
    cfg = json.loads((directory/'config.json').read_text())
    started = datetime.now(timezone.utc).isoformat()
    t = exe.preflight()
    account = exe.reconcile(include_pnl=False)
    fills = recent_fills(exe.client, cfg['startedAt'], exe.slug)
    journal = exe.journal()
    ledger = fill_accounting(fills, journal, cfg['exchanges'], cfg['startedAt'], cfg['prefix'])
    actual = inventory(account['positions']['positions'])
    issues = []
    if any(actual.get(e, 0) != ledger['signedInventory'].get(e, 0) for e in cfg['exchanges']):
        issues.append('Account and attributable fills disagree; repeat after reporting catches up')
    try:
        verify_baseline(cfg, actual)
    except ValueError as exc:
        issues.append(str(exc))
    unknown = [k for k, r in journal.items() if r['status'] == 'unknown']
    if unknown:
        issues.append('Shared journal has unresolved placements')
    current = {}
    for eid, spec in cfg['exchanges'].items():
        book = exe.client.get(f'/exchanges/{eid}/orderbook', tournamentId=t['id'], depth=50)
        if str(book['exchangeId']) != eid or str(book['marketId']) != spec['marketId']:
            raise ValueError('Wrong audit book identity')
        current[eid] = dict(book=exclude_own_liquidity(book, account['openOrders']),
                            bookAt=datetime.now(timezone.utc).isoformat())
    path = directory/'observations.jsonl'
    observations = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    observations.append(dict(at=datetime.now(timezone.utc).isoformat(), observations=current, accounting=ledger))
    result = evaluate(cfg, fills, journal, observations)
    owned = {int(r['response']['orderId']) for k, r in journal.items()
             if k.startswith(cfg['prefix']) and r['status'] == 'confirmed'}
    open_owned = [o for o in account['openOrders'] if int(o['id']) in owned]
    reports = {}
    if lifecycle:
        for oid in sorted(owned):
            detail = exe.client.get(f'/orders/{oid}/fills', limit=1)
            body = next(r['body'] for k, r in journal.items() if k.startswith(cfg['prefix'])
                        and str((r.get('response') or {}).get('orderId')) == str(oid))
            if (str(detail['orderId']) != str(oid) or str(detail['exchangeId']) != str(body['exchangeId'])
                    or str(detail['tournamentId']) != str(t['id']) or not detail['coverage']['complete']
                    or abs(detail['totalQuantityFilled']) != ledger['filledByOrder'].get(str(oid), 0)):
                issues.append('Lifecycle coverage/quantity mismatch: '+str(oid))
            reports[str(oid)] = detail
    finished = datetime.now(timezone.utc)
    ages = {e: (finished-datetime.fromisoformat(o['bookAt'])).total_seconds() for e, o in current.items()}
    if any(age > 90 for age in ages.values()):
        issues.append('Audit price reads aged beyond 90 seconds; refresh before interpreting open inventory')
    result.update(auditStartedAt=started, auditCompletedAt=finished.isoformat(), bookAgeSeconds=ages,
                  issues=issues, unknownKeys=unknown, openOrders=open_owned,
                  actualTrialInventory={e: actual.get(e, 0) for e in cfg['exchanges']},
                  baselineInventoryUnchanged=all(actual.get(e, 0) == q for e, q in cfg['baselineInventory'].items()),
                  flat=not any(actual.get(e, 0) for e in cfg['exchanges']) and not open_owned,
                  accounting=ledger, lifecycleChecked=lifecycle, lifecycle=reports,
                  automaticScaleUp=False, permitChanged=False)
    atomic_json(directory/'evaluation.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--lifecycle', action='store_true')
    args = parser.parse_args()
    result = audit(Executor(), args.directory, args.lifecycle)
    print(json.dumps({k: v for k, v in result.items() if k != 'lifecycle'}, indent=2))


if __name__ == '__main__':
    main()
