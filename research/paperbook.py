"""Complete paper lifecycle (backlog item 17). Quote-touch counts are
observations, not fills: this engine turns virtual orders into bounded fills.

Execution model (stated bounds, no queue data available):
- A virtual resting BUY at price p over one book snapshot fills:
  - pessimistic: only the quantity offered AT or BELOW p (asks <= p),
    i.e. someone trades through us; joining the bid earns nothing.
  - optimistic: full size at p when p touches/improves the best bid
    (p >= best bid), i.e. perfect queue priority assumed (overstates;
    queue position unknown). BELOW the touch fills NOTHING — a bid
    under the market cannot be filled by displayed bids above it
    (item-103 fix: the old comparison was inverted and filled those).
- SELL mirrors: pessimistic bids >= p; optimistic requires p <= best
  ask (at/improving the offer), else nothing.
- True fill lies between the bounds; a strategy valid only under optimistic
  assumptions is rejected. Partials, cancels (unfilled rest dies at book
  refresh), inventory, exits (market into opposite touch), and cash tracked.
- One snapshot = one evaluation: a later touch never retro-fills an
  earlier quote (no manufactured volume across observations).
- state() carries the live assumption list; bounds are labeled, never
  guaranteed, on real fills.
"""
import argparse
import json


def fill_buy(book, price, size, bound):
    """(filled_qty, cash_out). Bids/asks are YES-unit (price, qty) lists."""
    asks = sorted([(float(p), float(q)) for p, q in book.get('asks', [])])
    bids = sorted(((float(p), float(q)) for p, q in book.get('bids', [])),
                  reverse=True)
    if bound == 'pessimistic':
        filled, out = 0.0, 0.0
        for p, q in asks:
            if p > price:
                break
            take = min(q, size - filled)
            filled += take
            out += take * p
            if filled >= size:
                break
        return filled, out
    # optimistic: touch earns perfect priority (documented overstatement);
    # below the touch fills NOTHING (item-103: inverted gate fixed).
    if bids and price >= bids[0][0] - 1e-9:
        return float(size), float(size) * price
    return 0.0, 0.0


def fill_sell(book, price, size, bound):
    bids = sorted([(float(p), float(q)) for p, q in book.get('bids', [])],
                  reverse=True)
    asks = sorted([(float(p), float(q)) for p, q in book.get('asks', [])])
    if bound == 'pessimistic':
        filled, proceeds = 0.0, 0.0
        for p, q in bids:
            if p < price:
                break
            take = min(size - filled, q)
            filled += take
            proceeds += take * p
            if filled >= size:
                break
        return filled, proceeds
    if asks and price <= asks[0][0] + 1e-9:
        return float(size), float(size) * price
    return 0.0, 0.0


class PaperBook:
    """Virtual inventory + cash under one bound. One instance per bound.

    Cash discipline (item-104): initial funding (cash) is tracked
    separately from trading P&L (realized). A funded, never-traded book
    reports zero profit — funding is not earnings.
    """

    def __init__(self, bound='pessimistic', cash=0.0):
        assert bound in ('pessimistic', 'optimistic')
        self.bound = bound
        self.cash = cash
        self.initial_cash = cash
        self.inventory = 0.0
        self.fills = 0
        self.partials = 0
        self.unfilled_value = 0.0  # liquidation value that had no depth

    def quote(self, book, side, price, size):
        """Rest one virtual order for a single snapshot. Returns filled qty."""
        if side == 'buy':
            filled, out = fill_buy(book, price, size, self.bound)
            self.cash -= out
            self.inventory += filled
        else:
            filled, proceeds = fill_sell(book, price, size, self.bound)
            self.cash += proceeds
            self.inventory -= filled
        if filled > 0:
            self.fills += 1
            if filled < size:
                self.partials += 1
        return filled

    def exit_all(self, book, mark=None):
        """Market out of inventory into opposite touch, bounded by ACTUAL
        modeled fills: unsold shares stay in inventory and their missing
        liquidation value is recorded (never zeroed by fiat). mark: per-share
        residual mark for the retained inventory (or None = unvalued).
        Returns realized cash delta (not total cash)."""
        if self.inventory > 0:
            filled, proceeds = fill_sell(book, -1.0, self.inventory, 'pessimistic')
            self.cash += proceeds
            self.inventory -= filled
            missing = self.inventory
            delta = proceeds
        elif self.inventory < 0:
            filled, out = fill_buy(book, 2.0, -self.inventory, 'pessimistic')
            self.cash -= out
            self.inventory += filled
            missing = -self.inventory
            delta = -out
        else:
            return 0.0
        if missing > 1e-9:
            px = mark if mark is not None else 0.0
            self.unfilled_value = round(missing * px, 2)
        return round(delta, 2)

    def pnl(self):
        """Trading P&L = cash minus initial funding. Funding is not profit."""
        return round(self.cash - self.initial_cash, 2)

    def state(self):
        assumptions = [
            'pessimistic: fills only displayed contra-depth at/through limit',
            'optimistic: touch earns perfect queue priority (overstates)',
            'below-touch optimistic fills: rejected as impossible (item-103)',
            'one snapshot = one evaluation; no retro-fills across observations',
            'bounds labeled, never guaranteed, on real fills',
        ]
        return {'bound': self.bound, 'cash': round(self.cash, 2),
                'initial_cash': round(self.initial_cash, 2),
                'pnl': self.pnl(),
                'inventory': self.inventory, 'fills': self.fills,
                'partials': self.partials,
                'unfilled_value': self.unfilled_value,
                'assumptions': assumptions}
