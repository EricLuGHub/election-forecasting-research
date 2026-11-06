"""Finalize only an expired, flat, fully reconciled trial. Never trades."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .e7run import recent_fills
from .engines.engine7_maker import fill_accounting
from .execution import Executor
from .monitor import atomic_json
from .pilot import instant, mode, verify_baseline
from .risk import inventory
from .trial import DIRECTORY


def finish(exe, directory, apply=False):
    directory = Path(directory)
    cfg = json.loads((directory/'config.json').read_text())
    with exe.locked():
        now = datetime.now(timezone.utc)
        if now < instant(cfg['expiresAt']):
            raise ValueError('Trial window has not finished')
        recovery = mode(exe.recovery_path)
        if recovery.get('openingPermit', {}).get('prefix') != cfg['prefix']:
            raise ValueError('Current permit does not belong to this trial')
        journal = exe.journal()
        if any(r['status'] == 'unknown' for r in journal.values()):
            raise ValueError('Resolve all placements before finalizing')
        account = exe.reconcile(include_pnl=False)
        actual = inventory(account['positions']['positions'])
        verify_baseline(cfg, actual)
        ledger = fill_accounting(recent_fills(exe.client, cfg['startedAt'], exe.slug), journal,
                                 cfg['exchanges'], cfg['startedAt'], cfg['prefix'])
        if any(actual.get(e, 0) or ledger['signedInventory'].get(e, 0) for e in cfg['exchanges']):
            raise ValueError('Trial still has inventory; keep exits running')
        if any(str(o['exchangeId']) in cfg['reservedExchangeIds'] for o in account['openOrders']):
            raise ValueError('Reserved race still has a pending order')
        proof = dict(at=now.isoformat(), prefix=cfg['prefix'], flat=True, pendingOrders=0,
                     accounting=ledger, previousPermit=recovery['openingPermit'], applied=apply,
                     reason='30-minute trial complete; no permission to extend or scale')
        if apply:
            # Archive the permit before releasing recovery reservations. Expiry
            # already blocks new entries throughout this shared-lock operation.
            atomic_json(directory/'completed.json', proof)
            atomic_json(directory/'shutdown.request', {'at': now.isoformat(), 'reason': proof['reason']})
            recovery.pop('openingPermit')
            recovery['reduceOnly'] = True
            atomic_json(exe.recovery_path, recovery)
        return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(finish(Executor(), args.directory, args.apply), indent=2))


if __name__ == '__main__':
    main()
