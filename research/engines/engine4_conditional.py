"""Engine4: conditional listed-winner YES baskets (small directional).

Consumes conditionalCoverageCandidates: payouts assume a listed outcome wins and
are NOT guaranteed. Intents carry the explicit assumption tag and are sized tiny
by the allocator. Never presented as arbitrage.
"""
from .base import Engine
from research.execution import build_multileg


class ConditionalYes(Engine):
    name = 'conditional_yes'
    engine_id = 'E4'

    def __init__(self, max_legs_capital=500.0, tag=None):
        super().__init__(tag=tag or self.engine_id)
        self.max_legs_capital = max_legs_capital

    def quote(self, market_state):
        intents = []
        for cand in market_state.get('conditional_baskets', []):
            if cand.get('cost', 0) > self.max_legs_capital:
                continue
            legs = [{'exchangeId': str(x['exchangeId']), 'side': x['side'],
                     'action': 'buy', 'quantity': int(cand['quantityEach'])}
                    for x in cand['legs']]
            basket = build_multileg(legs)
            intents.append({'engine': self.tag, 'basket': basket,
                            'expected_capital': cand.get('cost', 0.0),
                            'race': cand.get('race'),
                            'assumption': 'a listed outcome wins; not guaranteed'})
        return intents
