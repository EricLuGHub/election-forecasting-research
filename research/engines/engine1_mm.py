"""Engine1: inside-spread market making (shadow-first).

Reservation-skew quoting in the spirit of Avellaneda-Stoikov (see rodlaf
kalshi-market-maker; Feil & Nendel). Resting YES bid/ask inside the seed spread,
skewed against accumulated inventory. Pure function: no I/O, no fills assumed.
Paper markouts decide whether it earns allocation.
"""
from .base import Engine
from research.execution import round_tick, MIN_PRICE, MAX_PRICE


class MarketMaker(Engine):
    name = 'inside_spread_mm'
    engine_id = 'E1'

    def __init__(self, lot=10, min_spread=0.02, max_position=600,
                 skew_per_lot=0.0025, tick_offset=0.005, tag=None):
        super().__init__(tag=tag or self.engine_id)
        self.lot = lot
        self.min_spread = min_spread
        self.max_position = max_position  # shares (signed YES); shorts count too
        self.skew_per_share = skew_per_lot / 100.0
        self.tick_offset = tick_offset
        self.inventory = {}  # exchangeId -> signed YES shares

    def quote(self, market_state):
        intents = []
        activity = market_state.get('activity', {})
        books = sorted(market_state.get('books', []),
                       key=lambda b: (-activity.get(str(b['exchangeId']), 0),
                                      -(b['yesAsk'] - b['yesBid'])))
        for book in books:
            eid = str(book['exchangeId'])
            bid = book.get('yesBid')
            ask = book.get('yesAsk')
            if bid is None or ask is None or ask - bid < self.min_spread:
                continue
            inv = self.inventory.get(eid, 0)
            if abs(inv) >= self.max_position:
                continue
            # Improve the touch by one tick (or the skew-adjusted equivalent):
            # defined edge, queue priority over deeper seed orders, no
            # meaningless mid-price in 90c-wide books.
            skew = self.skew_per_share * inv
            quote_bid = round_tick(min(max(bid + self.tick_offset - skew, MIN_PRICE), MAX_PRICE))
            quote_ask = round_tick(min(max(ask - self.tick_offset - skew, MIN_PRICE), MAX_PRICE))
            if round(quote_ask - quote_bid, 3) <= 0:
                continue
            side = 'yes'
            intents.append({'engine': self.tag, 'exchangeId': eid, 'side': side,
                            'action': 'buy', 'quantity': self.lot, 'price': quote_bid,
                            'role': 'mm_bid'})
            intents.append({'engine': self.tag, 'exchangeId': eid, 'side': side,
                            'action': 'sell', 'quantity': self.lot, 'price': quote_ask,
                            'role': 'mm_ask'})
        return intents

    def on_fill(self, fill):
        eid = str(fill.get('exchangeId', ''))
        qty = int(fill.get('quantity', 0))
        if fill.get('side') == 'yes':
            self.inventory[eid] = self.inventory.get(eid, 0) + (qty if fill.get('action') == 'buy' else -qty)
