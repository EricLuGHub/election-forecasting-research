"""Capital time and return on loss exposure (backlog item 88).

Separates what most reporting merges: cash tied up, guaranteed floors,
hypothetical collateral release, and worst-scenario loss. Optimizes against
the BINDING constraint, not gross volume.

Definitions (explicit, no hidden netting):
- cash_tied: sum of position cost bases (cash already spent, locked in).
- floor_paired: paired basket shares x $1 (normal single-winner resolution).
- tails: short-YES max loss = shares - premium collected (per short entry).
- worst_loss: tails + grading haircut (5% of basket cost: refunds, rule
  ambiguity, settlement mismatch — an allowance, not a prediction).
- locked_edge: floor_paired + collected premiums - cash_tied... careful:
  locked edge on baskets = floor - cost; shorts edge = premium at risk.
  Return on loss exposure = locked_edge / worst_loss.
- capital_days: (locked_edge / cash_tied) / days_to_settlement.

Assumptions stated, not buried: single-winner offices pay exactly $1 per
paired unit; indie wins pay $2 (upside, excluded from floor); settlement
invalidation beyond the 5% haircut is unmodeled catastrophe risk.
"""
import argparse
import json
from datetime import datetime, timezone
from .client import ROOT, Client

SETTLEMENT = datetime(2026, 11, 4, tzinfo=timezone.utc)
HAIRCUT = 0.05


def capital_use(basket_cost, basket_floor, other_cb, shorts_collected,
                shorts_tails, now=None):
    """Pure computation. Basket inventory separated from legacy inventory."""
    now = now or datetime.now(timezone.utc)
    days = max(1.0, (SETTLEMENT - now).total_seconds() / 86400.0)
    cash_tied = basket_cost + other_cb
    locked = (basket_floor - basket_cost) + shorts_collected
    worst = shorts_tails + HAIRCUT * cash_tied
    return {
        'cash_tied': round(cash_tied, 2),
        'basket_cost': round(basket_cost, 2),
        'other_cost': round(other_cb, 2),
        'floor_paired': round(basket_floor, 2),
        'locked_edge': round(locked, 2),
        'worst_loss': round(worst, 2),
        'return_on_exposure': round(locked / worst, 3) if worst > 0 else None,
        'edge_per_capital_day': round(locked / cash_tied / days, 6) if cash_tied > 0 else None,
        'days_to_settlement': round(days, 1),
    }


def live(client=None):
    client = client or Client()
    slug = 'midterm-elections'
    pnl = client.get(f'/tournaments/{slug}/portfolio/pnl', period='all')
    positions = client.get(f'/tournaments/{slug}/portfolio/positions')
    holds = positions.get('positions', positions)
    cb = sum(float(p.get('costBasis', 0) or 0) for p in holds)
    ledger = json.loads((ROOT / 'data/e2_taken.json').read_text())
    from .reconcile import reconcile
    from .convexit import race_pair
    tid = client.get('/tournaments', slug=slug)['data'][0]['id']
    paired = 0.0
    basket_cost = 0.0
    for r in reconcile(ledger, holds,
                       lambda race: race_pair(client, tid, race)):
        if r.get('status') not in ('intact', 'partial'):
            continue
        paired += r.get('paired', 0)
        info = ledger.get(r['basket'], {})
        size = next((int(t[1:]) for t in str(info.get('race', '')).split()
                     if t.startswith('x') and t[1:].isdigit()), 0)
        if size > 0:
            basket_cost += float(info.get('cost', 0)) * r.get('paired', 0) / size
    collected, tails = 0.0, 0.0
    for name, info in ledger.items():
        if 'proceeds' in info and 'tail' in info:
            collected += float(info['proceeds'])
            tails += float(info['tail']) - float(info['proceeds'])
    out = capital_use(basket_cost, paired * 1.0, cb - basket_cost,
                      collected, tails)
    out['position_count'] = len(holds)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    print(json.dumps(live(), indent=2))


if __name__ == '__main__':
    main()
