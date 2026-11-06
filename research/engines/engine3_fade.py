"""Engine3: Kalshi-reference fade (shadow-only until validated).

Consumes external discrepancies with rule-matched mappings: when the buffered
edge of a SIG leg against its recalibrated Kalshi reference exceeds min_edge and
the book shows two-sided depth, emit a small intended limit order. Recalibration
buckets (politics underconfidence, e.g. 70c ~= 83%) live in market_state['recal'].
Never trades mappingStatus != approved equivalents; stale references are skipped
by the caller via max quote age.
"""
from .base import Engine


class ReferenceFade(Engine):
    name = 'reference_fade'
    engine_id = 'E3'

    def __init__(self, min_edge=0.02, lot=25, tag=None):
        super().__init__(tag=tag or self.engine_id)
        self.min_edge = min_edge
        self.lot = lot

    def quote(self, market_state):
        intents = []
        for gap in market_state.get('gaps', []):
            if gap.get('mappingStatus') != 'candidate_requires_settlement_review':
                continue
            if gap.get('stale', False):
                continue
            edge = float(gap.get('bufferedEdge', 0) or 0)
            if abs(edge) < self.min_edge:
                continue
            side = gap['side']
            action = 'buy' if edge > 0 else 'sell'
            intents.append({'engine': self.tag, 'exchangeId': str(gap['exchangeId']),
                            'side': side, 'action': action, 'quantity': self.lot,
                            'price': gap.get('limitPrice'), 'edge': edge,
                            'role': 'fade'})
        return intents
