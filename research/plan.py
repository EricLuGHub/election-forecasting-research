"""Prepare a research-only valuation and limit-quote plan against a fresh book.

This command never submits orders. The probability is a user-supplied assumption.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from .client import Client, ROOT, save_json
from .pricing import buy_levels, fractional_kelly, quote, sweep


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--market', required=True, help='SIG market ID, not exchange ID')
    parser.add_argument('--p', required=True, type=float, help='Assumed YES probability')
    parser.add_argument('--uncertainty', type=float, default=.03, help='Illustrative probability haircut')
    parser.add_argument('--quantity', type=int, default=100)
    parser.add_argument('--fee', type=float, default=0.)
    parser.add_argument('--inventory', type=float, default=0., help='Assumed signed YES inventory for quote illustration')
    args = parser.parse_args()
    if (not all(math.isfinite(x) for x in (args.p, args.uncertainty, args.fee, args.inventory))
            or not 0 <= args.p <= 1 or not 0 <= args.uncertainty <= 1 or args.quantity <= 0 or args.fee < 0):
        parser.error('Invalid probability, uncertainty, fee or quantity')
    c = Client()
    t = c.get('/tournaments/midterm-elections')
    m = c.get(f'/markets/{args.market}', tournamentId=t['id'])
    if len(m['exchanges']) != 1:
        parser.error('This planner supports single-exchange binary markets only')
    eid = m['exchanges'][0]['id']
    b = c.get(f'/exchanges/{eid}/orderbook', tournamentId=t['id'], depth=200)
    sides = []
    for side in ('yes','no'):
        p = args.p if side == 'yes' else 1-args.p
        lower = max(0, p-args.uncertainty)
        fill = sweep(b, side, args.quantity)
        if fill['filled']:
            cost = fill['vwap'] + args.fee
            bankroll_fraction = fractional_kelly(lower, cost) if 0 < cost < 1 else 0.
            sides.append({'side':side, **fill, 'assumedProbability':p,
                          'bufferedProbability':lower, 'bufferedEdgePerFilledShare':lower-cost,
                          'illustrativeIsolatedCashCap': t['myBalance'] * bankroll_fraction,
                          'note':'Cash cap is not a portfolio risk limit; outstanding orders and correlated exposure must be included.'})
    result = {'mode':'RESEARCH_ONLY_NO_ORDERS_SUBMITTED', 'at':datetime.now(timezone.utc).isoformat(),
              'marketId': m['id'], 'exchangeId':eid, 'title':m['title'],
              'tournamentStatus':t['status'], 'startDate':t['startDate'],
              'assumptions':vars(args), 'takerValuations':sides,
              'makerQuote':quote(args.p, uncertainty=args.uncertainty, fee=args.fee, inventory=args.inventory),
              'limitations':['Probability and uncertainty are assumptions, not calibrated estimates.',
                             'No fill-probability, queue, portfolio or adverse-selection model is fitted.',
                             'Quote illustration is not an executable order instruction.']}
    save_json(ROOT/'data/plans'/f'{m["id"]}.json',result)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
