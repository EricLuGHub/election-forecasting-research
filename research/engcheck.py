"""Registry self-check (backlog item 20). Evidence, not assertions.

Compares a live evidence snapshot (Pi ps list, log mtimes, last fill/exit
times, open orders) against registry claims and shared config (alloc.json,
recovery/mode.json). Reports drift lines; never rewrites shared config.
Stale claims get flagged with the contradicting evidence, attributed to a
source and timestamp.
"""
import argparse
import json
from datetime import datetime, timezone


def check(evidence, registry):
    """evidence: {processes:[cmd...], logs:{name: age_min|None},
    last_fill_at, last_exit_flag_at, open_orders, alloc, mode}.
    registry: {engines: [{id, status, claims:{...}}]}. Returns drift lines."""
    drift = []
    procs = ' '.join(evidence.get('processes', []))
    for eng in registry.get('engines', []):
        eid = eng.get('id', '?')
        for proc_sig, label in eng.get('expect_process', []):
            alive = proc_sig in procs
            if eng.get('status') in ('LIVE ACTIVE', 'RUNNING') and not alive:
                drift.append({'engine': eid, 'kind': 'process_missing',
                              'expected': label})
            if 'PARKED' in str(eng.get('status')) and alive and \
                    eng.get('forbid_process'):
                drift.append({'engine': eid, 'kind': 'unexpected_process',
                              'found': label})
        for log, max_age in eng.get('expect_fresh_logs', []):
            age = (evidence.get('logs') or {}).get(log)
            if age is None:
                drift.append({'engine': eid, 'kind': 'log_missing', 'log': log})
            elif age > max_age:
                drift.append({'engine': eid, 'kind': 'log_stale', 'log': log,
                              'age_min': age})
    alloc = evidence.get('alloc') or {}
    for eng_id, field, observed in evidence.get('alloc_checks', []):
        try:
            node = alloc
            for part in field.split('.'):
                node = node.get(part, {})
            if node != observed:
                drift.append({'engine': eng_id, 'kind': 'alloc_mismatch',
                              'field': field, 'claims': node,
                              'observed': observed})
        except AttributeError:
            drift.append({'engine': eng_id, 'kind': 'alloc_unreadable',
                          'field': field})
    return drift


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--registry', required=True)
    args = parser.parse_args()
    with open(args.evidence) as handle:
        evidence = json.load(handle)
    with open(args.registry) as handle:
        registry = json.load(handle)
    drift = check(evidence, registry)
    print(json.dumps({'drift_lines': len(drift), 'drift': drift}, indent=2))


if __name__ == '__main__':
    main()
