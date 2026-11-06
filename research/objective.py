"""Objective decision math (backlog item 95). No slogans, just rates.

Compares candidate objectives as required sustained rates from today's
profile, so the choice is explicit: terminal wealth maximization, top-20
placement, top-3 prizes, or the stated +1%/h. All rates assume 30 days to
settlement and linear accumulation (generous to the goal-seeker: real edge
arrives in lumps, and cutoffs move).
"""
import argparse
import json
from datetime import datetime, timezone

DAYS_LEFT = 30.0


def required_rates(ours, cutoff_top20, cutoff_top3, days_left=DAYS_LEFT):
    """ours: current all-time PnL. Returns $/day and %/h per objective."""
    out = {}
    out['top20'] = {'need': round(cutoff_top20 - ours, 2)}
    out['top3'] = {'need': round(cutoff_top3 - ours, 2)}
    for key in ('top20', 'top3'):
        need = max(0.0, out[key]['need'])
        out[key]['per_day'] = round(need / days_left, 2)
        out[key]['per_hour_pct'] = round(need / days_left / 24.0 / 1000.0, 4)
    out['plus1pct_hour'] = {'per_day': 24000.0, 'per_hour_pct': 1.0,
                            'note': 'stated goal: $1k/h on $100k base'}
    out['terminal_wealth'] = {'policy': 'maximize settlement value per '
                                        'verified edge; rate follows edge supply'}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ours', type=float, default=522.58)
    parser.add_argument('--cutoff-top20', type=float, default=81678.67)
    parser.add_argument('--cutoff-top3', type=float, default=670507.53)
    args = parser.parse_args()
    print(json.dumps(required_rates(args.ours, args.cutoff_top20,
                                    args.cutoff_top3), indent=2))


if __name__ == '__main__':
    main()
