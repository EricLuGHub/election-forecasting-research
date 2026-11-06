"""Engine interface. Every EngineN implements this; the allocator only talks to it.

An engine produces *intended* orders (paper or live) and reports attributed fills.
Live submission always flows through research.execution.Executor (dry-run default,
open-tournament gate, caps, kill switch). Engines never call the API directly.
"""
import uuid


class Engine:
    name = 'base'
    engine_id = 'E0'

    def __init__(self, tag=None):
        self.tag = tag or self.engine_id

    def prefix(self):
        return f'{self.tag}-{uuid.uuid4().hex[:8]}'

    def quote(self, market_state):
        """Return a list of intended order dicts (exchangeId/side/action/quantity/price).

        market_state carries fresh books, positions, inventory and fair values.
        Pure function of its inputs; no I/O. Empty list means no opportunity.
        """
        raise NotImplementedError

    def on_fill(self, fill):
        """Optional inventory/state update after an attributed fill."""

    def describe(self):
        return {'engine': self.name, 'tag': self.tag}
