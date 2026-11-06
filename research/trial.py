"""Initialize a separate, fixed 30-minute three-race simulated maker trial.

Never resets another run. Existing counterpart positions are frozen, not sold
or attributed to trial P&L. The shared recovery switch remains enabled.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

from .client import ROOT
from .e6data import contract_identity
from .execution import Executor
from .external import event_for_title
from .monitor import atomic_json, instance_lock
from .pilot import instant, mode, trial_scope
from .risk import inventory

DIRECTORY = ROOT/'data/trial-20261002'


def initialize(exe, directory, snapshot, selections):
    directory = Path(directory)
    if (directory/'config.json').exists():
        raise ValueError('Trial already initialized; cannot reset deadline or history')
    if len(selections) != 3 or len({e for e, _ in selections}) != 3:
        raise ValueError('Require three distinct trial instruments')
    snap = json.loads(Path(snapshot).read_text())
    scopes, nodes, reserved = {}, {}, set()
    for eid, side in selections:
        if side not in ('yes', 'no'):
            raise ValueError('Invalid side')
        market = next(m for m in snap['markets'] if any(str(e['id']) == eid for e in m['exchanges']))
        mapping = event_for_title(market['title'])
        if not mapping or mapping[0].startswith('CONTROL') or market['status'] != 'open':
            raise ValueError('Unsupported or closed trial market')
        nodes[eid] = exe.client.get(f"/markets/{market['id']}/nodes")
        identity = contract_identity(market, nodes[eid])
        if not identity:
            raise ValueError('Unverified trial contract identity')
        group = set()
        for sibling in snap['markets']:
            if (event_for_title(sibling['title']) or (None,))[0] != mapping[0]:
                continue
            node = nodes[eid] if sibling['id'] == market['id'] else exe.client.get(f"/markets/{sibling['id']}/nodes")
            other = contract_identity(sibling, node)
            if not other or other['raceKey'] != identity['raceKey']:
                raise ValueError('Counterpart race identity not verified')
            group.update(str(e['id']) for e in sibling['exchanges'])
        if group & reserved:
            raise ValueError('Trial instruments must be from independent races')
        reserved |= group
        scopes[eid] = dict(identity, side=side, marketId=str(market['id']), maxShares=100,
                           raceExchangeIds=sorted(group), title=market['title'])
    with exe.locked():
        t, account = exe.preflight(), exe.reconcile(include_pnl=False)
        if str(t['id']) != str(snap['tournament']['id']):
            raise ValueError('Wrong snapshot tournament')
        if any(r['status'] == 'unknown' for r in exe.journal().values()):
            raise ValueError('Resolve ambiguous placements first')
        quantities = inventory(account['positions']['positions'])
        if any(quantities.get(e, 0) for e in scopes):
            raise ValueError('Each traded instrument must initially be flat')
        if any(str(o['exchangeId']) in reserved for o in account['openOrders']):
            raise ValueError('Wait for reserved race orders to close before initialization')
        recovery = mode(exe.recovery_path)
        old = recovery.get('openingPermit')
        now = datetime.now(timezone.utc)
        if old:
            old_ids = set(old['reservedExchangeIds'])
            if (old.get('entryEnabled') or instant(old['expiresAt']) > now
                    or any(quantities.get(e, 0) for e in old_ids)
                    or any(str(o['exchangeId']) in old_ids for o in account['openOrders'])):
                raise ValueError('Prior pilot must be disabled, expired, flat and order-free')
        frozen = {e: quantities.get(e, 0) for e in reserved-set(scopes)}
        cfg = dict(version=2, prefix='E7T-'+uuid.uuid4().hex[:12]+'-', slug=exe.slug,
                   startedAt=now.isoformat(), expiresAt=(now+timedelta(minutes=30)).isoformat(),
                   maxCapital=500, lossStop=25, maxHoldSeconds=600, minExitDepth=100,
                   referenceBuffer=.015, minSpread=.01, compareQuotes=True,
                   reservedExchangeIds=sorted(reserved), baselineInventory=frozen, exchanges=scopes)
        trial_scope(cfg)
        atomic_json(directory/'prior-recovery-mode.json', recovery)
        atomic_json(directory/'baseline.json', dict(at=now.isoformat(), account=account, nodes=nodes))
        atomic_json(directory/'config.json', cfg)
        if not exe.dry_run:
            atomic_json(exe.recovery_path, dict(recovery, reduceOnly=True, openingPermit=dict(cfg, entryEnabled=True)))
        return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--select', action='append', required=True, help='exchange:yes or exchange:no; exactly three')
    args = parser.parse_args()
    with instance_lock(args.directory):
        cfg = initialize(Executor(dry_run=not args.live), args.directory, args.snapshot,
                         [tuple(s.split(':')) for s in args.select])
        print(json.dumps(cfg, indent=2))


if __name__ == '__main__':
    main()
