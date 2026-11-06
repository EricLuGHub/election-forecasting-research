"""Independent safety supervisor: persistent entry halt and evidence-only repair.

No placement replay; only uniquely matching expired CLOSED history can resolve
an unknown submission. An unresolved case stays blocked and raises an alert.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .execution import Executor
from .monitor import atomic_json, instance_lock
from .pilot import instant
from .reconcile_order import matching, resolve
from .trial import DIRECTORY


def issues(config, status, now):
    if not status:
        return ['Runner has no heartbeat'] if (now-instant(config['startedAt'])).total_seconds() > 180 else []
    result = []
    age = (now-instant(status['at'])).total_seconds()
    if not 0 <= age <= 180:
        result.append('Runner heartbeat stale or clock invalid')
    if status.get('consecutiveFailures', 0) >= 3 or status.get('phase') == 'reconciliation_wait':
        result.append('Repeated errors or inventory reconciliation failure')
    return result


def repair_unknown(exe, key, row, apply, now):
    if (not key.startswith(('E1R-', 'E7M-', 'E7T-')) or row.get('route') != '/orders'
            or instant(row['body']['expirationDate']) >= now):
        return None
    body = row['body']
    rows = exe.client.pages('/orders', status='all', exchangeId=body['exchangeId'],
                            tournamentId=body['tournamentId'], limit=200)
    matches = [o for o in rows if matching(body, row['at'], o)]
    if len(matches) != 1:
        return None
    # resolve repeats identity, uniqueness and complete lifecycle verification
    # inside the shared execution lock before changing local ownership evidence.
    return resolve(exe, key, matches[0]['id'], apply=apply)


def check(exe, directory, apply=False):
    directory = Path(directory)
    cfg = json.loads((directory/'config.json').read_text())
    status = json.loads((directory/'status.json').read_text()) if (directory/'status.json').exists() else {}
    now = datetime.now(timezone.utc)
    completed = (directory/'completed.json').exists() and (directory/'shutdown.request').exists()
    alerts, repairs, pending = ([] if completed else issues(cfg, status, now)), [], []
    for key, row in exe.journal().items():
        if row['status'] != 'unknown':
            continue
        try:
            # The write-ahead state is also visible during an ordinary in-flight
            # POST. Do not misdiagnose that short window as a stuck placement.
            if ((now-instant(row['at'])).total_seconds() < 180
                    and instant(row['body']['expirationDate']) > now):
                pending.append(key)
                continue
            proof = repair_unknown(exe, key, row, apply, now)
            if proof:
                repairs.append({'key': key, 'orderId': proof['order']['id'], 'applied': apply})
            if not proof or not apply:
                alerts.append('Unresolved submission: '+key)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            alerts.append('Resolution blocked: '+key+': '+str(exc)[:200])
    result = dict(at=now.isoformat(), alerts=alerts, repairs=repairs, awaitingPlacement=pending,
                  entryHalted=completed or (directory/'health-halt.json').exists(), completed=completed, apply=apply)
    if apply and alerts:
        if not (directory/'health-halt.json').exists():
            atomic_json(directory/'health-halt.json', result)
        result['entryHalted'] = True
        # Short expiry is the outage fallback. Never cancel other engines or
        # inventory-reducing exits from this independent safety process.
        owned_buys = {int(r['response']['orderId']) for k, r in exe.journal().items()
                      if k.startswith(cfg['prefix']) and r['status'] == 'confirmed' and r['body']['action'] == 'buy'}
        if owned_buys:
            try:
                for order in exe.open_orders():
                    if int(order['id']) in owned_buys:
                        exe.cancel_order(order['id'])
            except (OSError, RuntimeError, ValueError) as exc:
                result['cancelError'] = str(exc)[:200]
    atomic_json(directory/'health.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with instance_lock(args.directory/'health-lock'):
        print(json.dumps(check(Executor(dry_run=not args.apply), args.directory, args.apply)))


if __name__ == '__main__':
    main()
