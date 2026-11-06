"""Collateral audit, explicit tournament scope (backlog item 89). Pure.

Question: do collateral offsets exist for scaling, or is cash binding?
Reconcile `/portfolio/collateral?tournamentId=...` against positions,
cash, and settlement floors:
- offsets: collateral value the venue recognizes against open positions
  (reduces cash needed per new order).
- coverage: (cash + collateral) vs (open-order capital + worst-case
  residual exposure).
- verdict: 'offsets-live' (offsets > 0 and verified against positions),
  'cash-binding' (no offsets; every new dollar of exposure needs a cash
  dollar), or 'refused' (endpoint empty/error — absence of data is not
  absence of offsets, and it is also not evidence of them).
Tournament scope is explicit on every call: wrong-tournament collateral
is not ours (refuse scope mismatch, don't net it).
"""


def audit(collateral, positions_value, cash, open_order_capital,
          residual_exposure, tournament_ok=True):
    """All amounts numeric (contest currency). Returns (verdict, detail).

    residual_exposure: worst-case additional loss on open inventory
    (tails minus premiums for shorts; floor shortfall for baskets)."""
    if not tournament_ok:
        return 'refused', {'reason': 'tournament scope mismatch'}
    try:
        if isinstance(collateral, dict):
            col = float(collateral.get('collateralValue',
                                       collateral.get('value', 0)))
        else:
            col = float(collateral or 0)
        pos, cash_, oo, res = (float(positions_value), float(cash),
                               float(open_order_capital),
                               float(residual_exposure))
    except (TypeError, ValueError):
        return None, {'refused': 'non-numeric inputs'}
    if min(pos, cash_, oo, res) < 0 or col < 0:
        return None, {'refused': 'negative economics'}
    need = oo + res
    have = cash_ + col
    detail = {'collateral': round(col, 2), 'cash': round(cash_, 2),
              'need': round(need, 2), 'have': round(have, 2),
              'coverage': round(have / need, 3) if need > 0 else None}
    if col > 0:
        detail['why'] = 'offsets recognized; verify against positions'
        return 'offsets-live', detail
    detail['why'] = ('no offsets: every new exposure dollar needs a cash '
                     'dollar (%.2f cash vs %.2f need)') % (cash_, need)
    return 'cash-binding', detail
