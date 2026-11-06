"""Summarize E6's archived observations; never equate paper returns with proof."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from .e6run import DIRECTORY


def summarize(cycles):
    count = successful = errors = candidate_count = entries = exits = 0
    entered, skipped = set(), Counter()
    first = last = best = latest_paper = latest_coverage = None
    for cycle in cycles:
        count += 1
        at = datetime.fromisoformat(cycle['completedAt'])
        first, last = min(first, at) if first else at, max(last, at) if last else at
        errors += bool(cycle.get('errors'))
        if cycle.get('phase') != 'running':
            continue
        successful += 1
        latest_paper, latest_coverage = cycle.get('paper'), cycle.get('coverage')
        candidate_count += cycle.get('coverage', {}).get('screenedCandidates', 0)
        for execution in cycle.get('assumedExecutions', []):
            if execution['action'] == 'buy':
                entries += 1
                entered.add(execution['exchangeId'])
            else:
                exits += 1
        for row in cycle.get('screening', {}).get('topComparisons', []):
            best = max(best, row['bufferedTopEdge']) if best is not None else row['bufferedTopEdge']
        skipped.update(cycle.get('screening', {}).get('excluded', {}))
    if not count:
        return {'engine': 'E6', 'verdict': 'no_observations', 'liveValidated': False, 'cycles': 0}
    return {'engine': 'E6', 'mode': 'shadow', 'liveValidated': False,
            'verdict': 'paper_entries_need_validation' if entries else 'no_qualifying_entries_observed',
            'cycles': count, 'successfulCycles': successful,
            'firstCompletedAt': first.isoformat(), 'lastCompletedAt': last.isoformat(),
            'observationSpanSeconds': (last-first).total_seconds(),
            'cyclesWithErrors': errors, 'screenedCandidateObservations': candidate_count,
            'assumedEntryOrders': entries, 'assumedExitOrders': exits,
            'enteredExchanges': len(entered), 'bestBufferedScreenEdge': best,
            'screenExclusions': dict(skipped), 'latestPaper': latest_paper,
            'latestCoverage': latest_coverage,
            'limitations': ['Repeated observations and correlated races are not independent trials.',
                            'Screen quotes have no depth guarantee; only refreshed depth can generate an intent.',
                            'Counterfactual fills, provisional mappings and short observation periods cannot validate live profit.']}


def evaluate(directory=DIRECTORY):
    path = Path(directory).resolve() / 'history.sqlite3'
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        # Stream potentially gigabytes of retained input snapshots on the Pi.
        return summarize(json.loads(row[0]) for row in db.execute('SELECT payload FROM cycles ORDER BY at'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.directory), indent=2))


if __name__ == '__main__':
    main()
