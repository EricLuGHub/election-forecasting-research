"""Read-only top-20 campaign scoreboard with a fixed, non-resetting deadline."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .client import Client, ROOT
from .monitor import atomic_json, instance_lock
from .risk import finite

DIRECTORY = ROOT/'data/top20'


def instant(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timezone is required')
    return dt.astimezone(timezone.utc)


def measure(board, pnl, deadline, now, tournament=None):
    if pnl.get('period') != 'all':
        raise ValueError('Require all-time account P&L to match leaderboard')
    if board['period'] != 'all' or board.get('activeGroupId') is not None or board.get('offset', 0) != 0:
        raise ValueError('Require unfiltered, all-time tournament standings from first page')
    if board.get('sort', 'pnl') != 'pnl':
        raise ValueError('Wrong leaderboard sort')
    rows = board['leaderboard']
    if len(rows) < min(20, board['total']):
        raise ValueError('Insufficient leaderboard coverage')
    ranks = [int(r['rank']) for r in rows]
    scores = [finite(r['pnl']) for r in rows]
    if ranks != sorted(ranks) or scores != sorted(scores, reverse=True):
        raise ValueError('Inconsistent leaderboard ordering')
    eligible = [r for r in rows if 0 < int(r['rank']) <= 20]
    if not eligible:
        raise ValueError('No top-20 cutoff')
    cutoff = finite(eligible[-1]['pnl'])
    if pnl.get('periodPnl') is not None:
        own, source = finite(pnl['periodPnl']), 'reported_all_time_pnl'
    else:
        # Venue currently returns a null periodStart/periodPnl for "all".
        # This fixed-bankroll contest has no participant deposits/withdrawals.
        # Label the derived value; never turn missing P&L into zero.
        if not tournament or tournament.get('slug') != 'midterm-elections':
            raise ValueError('Missing all-time P&L and verified tournament baseline')
        initial = finite(tournament['initialBalance'])
        if initial <= 0:
            raise ValueError('Invalid tournament initial balance')
        own = round(finite(pnl['totalAccountValue'])-initial, 6)
        source = 'account_value_minus_tournament_initial_balance'
    rank = board['myRank']
    if rank is not None and (type(rank) is not int or rank < 1):
        raise ValueError('Invalid rank')
    gap = max(0, cutoff-own)
    hours = max(0, (deadline-now).total_seconds()/3600)
    return {'at': now.isoformat(), 'deadline': deadline.isoformat(), 'hoursRemaining': round(hours, 3),
            'rank': rank, 'rankedParticipants': board['total'], 'targetRank': 20,
            'ownPnl': own, 'ownPnlSource': source, 'top20CutoffPnl': cutoff, 'gapToCurrentCutoff': round(gap, 2),
            'requiredCatchUpPerHourAtFixedCutoff': round(gap/hours, 2) if hours else None,
            'observedTop20': rank is not None and rank <= 20,
            'paceValidated': False,
            'interpretation': 'Current standings only. The cutoff moves; marked P&L and a linear catch-up rate are not proof of a profitable strategy.'}


def run(directory=DIRECTORY, deadline=None, client=None):
    directory = Path(directory)
    with instance_lock(directory):
        config_path = directory/'campaign.json'
        if config_path.exists():
            config = json.loads(config_path.read_text())
            if deadline and instant(deadline) != instant(config['deadline']):
                raise ValueError('Existing campaign deadline cannot be silently reset')
        else:
            if not deadline:
                raise ValueError('Initialize with the explicit goal --deadline')
            config = {'deadline': instant(deadline).isoformat(), 'slug': 'midterm-elections', 'targetRank': 20}
            atomic_json(config_path, config)
        end, now = instant(config['deadline']), datetime.now(timezone.utc)
        if now > end+timedelta(hours=1):
            result = {'phase': 'deadline_passed', 'at': now.isoformat(),
                      'deadline': end.isoformat(), 'paceValidated': False}
            atomic_json(directory/'campaign-status.json', result)
            return result
        client = client or Client()
        board = client.get(f"/tournaments/{config['slug']}/leaderboard", period='all', limit=100)
        pnl = client.get(f"/tournaments/{config['slug']}/portfolio/pnl", period='all')
        tournament = client.get(f"/tournaments/{config['slug']}") if pnl.get('periodPnl') is None else None
        result = measure(board, pnl, end, datetime.now(timezone.utc), tournament)
        result.update(phase='observed_top20' if result['observedTop20'] else 'behind_target',
                      pnl=pnl)
        with (directory/'rank-history.jsonl').open('a') as handle:
            handle.write(json.dumps(result, allow_nan=False)+'\n')
        atomic_json(directory/'campaign-status.json', result)
        atomic_json(directory/'latest-leaderboard.json', board)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--deadline', help='Explicit ISO UTC deadline; initialization only')
    args = parser.parse_args()
    try:
        result = run(args.directory, args.deadline)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        result = {'phase': 'error', 'at': datetime.now(timezone.utc).isoformat(), 'error': str(exc)[:350]}
        atomic_json(args.directory/'campaign-status.json', result)
        raise
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
