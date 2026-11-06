"""Engine2: exclusive party-winner NO baskets via atomic multi-leg.

Consumes research.analyze logicalCandidates (exclusive_winners_buy_no): every leg
is bought (NO side), all-or-none persisted by POST /orders/multi-leg, which kills
the leg-fill risk that sequential placement would carry. Optional
relationshipConstraint preflight when the relationship id is known.
"""
from .base import Engine
from research.execution import build_multileg


class NoBasket(Engine):
    name = 'exclusive_no_basket'
    engine_id = 'E2'

    def __init__(self, max_legs_capital=2000.0, tag=None):
        super().__init__(tag=tag or self.engine_id)
        self.max_legs_capital = max_legs_capital

    def quote(self, market_state):
        intents = []
        for cand in market_state.get('no_baskets', []):
            if cand.get('cost', 0) > self.max_legs_capital:
                continue
            legs = [{'exchangeId': str(x['exchangeId']), 'side': x['side'],
                     'action': 'buy', 'quantity': int(cand['quantityEach'])}
                    for x in cand['legs']]
            basket = build_multileg(legs)
            intents.append({'engine': self.tag, 'basket': basket,
                            'expected_capital': cand.get('cost', 0.0),
                            'race': cand.get('race')})
        return intents
