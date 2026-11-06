"""E6: reference-priced, depth-limited value trading. Shadow deployment only.

Kalshi quotes are a pricing hypothesis, not a hedge or a calibrated forecast.
Every marginal share must clear the reference spread, uncertainty, fee,
slippage allowance and minimum edge. No maker fills or short sales are assumed.
"""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import math

from .base import Engine
from research.execution import TICK, MIN_PRICE, MAX_PRICE


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a financial quantity')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite financial quantity')
    return result


def age_seconds(at, now):
    stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
    current = datetime.fromisoformat(now.replace('Z', '+00:00'))
    if stamp.tzinfo is None or current.tzinfo is None:
        raise ValueError('Timezone required')
    return (current - stamp).total_seconds()


def fresh(observation, now, max_age, max_span=10):
    try:
        age = age_seconds(observation['receivedAt'], now)
        span = age_seconds(observation['requestStartedAt'], observation['receivedAt'])
        return 0 <= age <= max_age and 0 <= span <= max_span
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def levels(book, side, action='buy'):
    """Validate depth before converting a YES-normalized book to side prices."""
    if side not in ('yes', 'no') or action not in ('buy', 'sell'):
        raise ValueError('Invalid side/action')
    bids, asks = [], []
    for field, target in (('bids', bids), ('asks', asks)):
        for row in book[field]:
            price, qty = number(row['price']), number(row['quantity'])
            if not 0 < price < 1 or qty < 0:
                raise ValueError('Invalid book level')
            if qty:
                target.append((price, qty))
    if bids and asks and max(p for p, _ in bids) >= min(p for p, _ in asks):
        raise ValueError('Locked/crossed SIG book')
    source = asks if (side == 'yes') == (action == 'buy') else bids
    return sorted(((p if side == 'yes' else 1-p, q) for p, q in source),
                  reverse=action == 'sell')


@dataclass(frozen=True)
class ValueConfig:
    uncertainty: float = 0.03
    slippage: float = 0.005
    fee: float = 0.0
    min_edge: float = 0.02
    min_profit: float = 0.50
    max_reference_spread: float = 0.06
    min_reference_size: float = 20
    min_reference_volume: float = 100
    max_book_age: float = 45
    max_reference_age: float = 120
    max_account_age: float = 120
    kelly_fraction: float = 0.25
    max_order_capital: float = 100
    max_engine_capital: float = 1500
    max_account_capital: float = 20000
    max_race_capital: float = 500
    max_shares: int = 200
    max_orders: int = 5
    exit_edge: float = 0.005

    def __post_init__(self):
        for name, value in asdict(self).items():
            if number(value) < 0:
                raise ValueError(f'{name} must be nonnegative')
        for name in ('max_shares', 'max_orders'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'{name} must be a positive integer')
        if not 0 < self.kelly_fraction <= 1:
            raise ValueError('kelly_fraction must be in (0, 1]')
        if self.uncertainty + self.slippage + self.fee + self.min_edge >= 1:
            raise ValueError('Price allowances must sum to less than one')


def account_risk(account, race_by_exchange):
    """Gross cash at risk; never offset correlated bets or opposing orders.

    Tournament position.quantity is signed YES regardless of option. SELL
    commitments are charged complement collateral even if currently backed.
    Unknown exchange mappings are charged to a common unknown race bucket.
    """
    total, races, shares, occupied = 0.0, defaultdict(float), defaultdict(float), set()
    for position in account['positions']:
        if position.get('settled'):
            continue
        eid = str(position['exchangeId'])
        qty, cost = number(position['quantity']), number(position['costBasis'])
        if cost < 0 or (qty == 0 and cost > 0):
            raise ValueError('Invalid position cost basis')
        total += cost
        races[race_by_exchange.get(eid, 'unknown')] += cost
        shares[eid] += abs(qty)
        if qty:
            occupied.add(eid)
    for order in account['orders']:
        if not order['open']:
            continue
        eid = str(order['exchangeId'])
        qty = number(order['quantity'])
        price = number(order['priceLimit'])
        if qty <= 0 or not 0 < price < 1 or order['side'] not in ('yes', 'no'):
            raise ValueError('Invalid open order')
        if order['action'] not in ('buy', 'sell'):
            raise ValueError('Invalid order action')
        cost = qty * (price if order['action'] == 'buy' else 1-price)
        total += cost
        races[race_by_exchange.get(eid, 'unknown')] += cost
        shares[eid] += qty
        occupied.add(eid)
    cash, equity = number(account['cash']), number(account['equity'])
    if min(cash, equity) < 0:
        raise ValueError('Negative cash/equity')
    return total, races, shares, occupied


class ReferenceValue(Engine):
    name = 'reference_value'
    engine_id = 'E6'
    deployment = 'shadow'

    def __init__(self, config=None, tag=None):
        super().__init__(tag=tag)
        self.config = config or ValueConfig()

    def quote(self, market_state):
        return self.evaluate(market_state)['intents']

    def evaluate(self, state):
        cfg, skipped, candidates, exits = self.config, Counter(), [], []
        result = {'engine': self.tag, 'mode': 'shadow', 'intents': [], 'skipped': {},
                  'config': asdict(cfg), 'executionEligible': False}
        now = state['now']
        account = state['account']
        if not fresh(account, now, cfg.max_account_age, 30):
            return dict(result, skipped={'stale_account': 1})
        race_map = state['raceByExchange']
        try:
            total, race_used, shares, occupied = account_risk(account, race_map)
            paper = state.get('paperPositions', {})
            paper_used = 0.0
            for eid, pos in paper.items():
                cost, qty = number(pos['cost']), number(pos['quantity'])
                if cost < 0 or qty <= 0 or pos['side'] not in ('yes', 'no'):
                    raise ValueError('Invalid paper position')
                paper_used += cost
                race_used[pos['raceKey']] += cost
                shares[eid] += qty
            pending = sum(number(o['quantity']) * (number(o['priceLimit']) if o['action'] == 'buy'
                                                   else 1-number(o['priceLimit']))
                          for o in account['orders'] if o['open'])
            # myBalance may include encumbered cash. Reserving commitments again
            # is conservative if the venue already reports an available balance.
            cash = min(number(state['paperCash']), max(0, number(account['cash'])-pending))
            bankroll = number(state['paperBankroll'])
            if min(cash, bankroll) < 0:
                raise ValueError('Negative paper balance')
        except (ValueError, KeyError, TypeError):
            return dict(result, skipped={'invalid_account': 1})
        seen = set()
        for item in state['instruments']:
            eid = str(item['exchangeId'])
            if eid in seen:
                skipped['duplicate_exchange'] += 1
                continue
            seen.add(eid)
            ref, book = item.get('reference', {}), item.get('book', {})
            reason = self.reject(item, now)
            if reason:
                skipped[reason] += 1
                continue
            lo = max(0, number(ref['bid']) - cfg.uncertainty)
            hi = min(1, number(ref['ask']) + cfg.uncertainty)
            try:
                position = paper.get(eid)
                if position and eid in occupied:
                    skipped['existing_account_exposure'] += 1
                    continue
                if position:
                    side = position['side']
                    upper = hi if side == 'yes' else 1-lo
                    bids = levels(book, side, 'sell')
                    profitable = [(p, q) for p, q in bids if p-cfg.fee-cfg.slippage >= upper+cfg.exit_edge]
                    intent = self.intent(item, side, 'sell', profitable,
                                         int(position['quantity']), upper)
                    if intent:
                        exits.append(intent)
                    # Never stack entries or flip an existing paper position in one cycle.
                    skipped['paper_position_held'] += 1
                    continue
                if eid in occupied:
                    skipped['existing_account_exposure'] += 1
                    continue
                for side, lower in (('yes', lo), ('no', 1-hi)):
                    eligible = [(p, q) for p, q in levels(book, side)
                                if lower-p-cfg.fee-cfg.slippage >= cfg.min_edge-1e-9]
                    if not eligible:
                        continue
                    candidates.append((lower-eligible[0][0]-cfg.fee-cfg.slippage,
                                       item, side, lower, eligible))
            except (ValueError, KeyError, TypeError):
                skipped['invalid_book'] += 1
        intents = sorted(exits, key=lambda i: -i['expectedProfit'])[:cfg.max_orders]
        # Do not spend hypothetical exit proceeds until a subsequent cycle.
        budget = min(cash, cfg.max_engine_capital-paper_used,
                     cfg.max_account_capital-total-paper_used)
        for _, item, side, lower, depth in sorted(candidates, key=lambda x: (-x[0], x[1]['exchangeId'], x[2])):
            if len(intents) >= cfg.max_orders:
                skipped['order_limit'] += 1
                continue
            eid, race = str(item['exchangeId']), item['raceKey']
            if any(i['exchangeId'] == eid for i in intents):
                continue
            worst = depth[-1][0]
            # Kelly stake is a cash amount; use the worst eligible price plus costs.
            unit_cost = round(math.ceil((worst-1e-10)/TICK)*TICK, 3) + cfg.fee + cfg.slippage
            kelly = cfg.kelly_fraction * max(0, (lower-unit_cost)/(1-unit_cost))
            allowed = min(budget, cfg.max_order_capital, bankroll*kelly,
                          cfg.max_race_capital-race_used[race]-race_used['unknown'])
            qty = max(0, min(cfg.max_shares-int(shares[eid]), math.floor(allowed/unit_cost)))
            intent = self.intent(item, side, 'buy', depth, qty, lower)
            if not intent or intent['expectedProfit'] < cfg.min_profit:
                skipped['capital_or_min_profit'] += 1
                continue
            reserve = intent['quantity'] * (intent['price']+cfg.fee+cfg.slippage)
            budget -= reserve
            race_used[race] += reserve
            shares[eid] += intent['quantity']
            intents.append(intent)
        result.update(intents=intents, skipped=dict(skipped), candidates=len(candidates),
                      accountCapitalAtRisk=round(total, 4), paperCapitalAtRisk=round(paper_used, 4),
                      remainingEntryBudget=round(max(0, budget), 4))
        return result

    def reject(self, item, now):
        cfg, ref = self.config, item.get('reference', {})
        if not item.get('raceKey') or item.get('mappingStatus') != 'candidate_requires_settlement_review':
            return 'unsupported_mapping'
        if not fresh(item.get('definition', {}), now, 900):
            return 'stale_definition'
        if not fresh(item.get('book', {}), now, cfg.max_book_age):
            return 'stale_book'
        if not fresh(ref, now, cfg.max_reference_age):
            return 'stale_reference'
        try:
            bid, ask = number(ref['bid']), number(ref['ask'])
            if ref['status'] != 'active' or not 0 < bid <= ask < 1:
                return 'invalid_reference'
            if ask-bid > cfg.max_reference_spread+1e-9:
                return 'wide_reference'
            if min(number(ref['bidSize']), number(ref['askSize'])) < cfg.min_reference_size:
                return 'thin_reference'
            if number(ref['volume24h']) < cfg.min_reference_volume:
                return 'inactive_reference'
        except (ValueError, TypeError, KeyError):
            return 'invalid_reference'
        return None

    def intent(self, item, side, action, depth, max_quantity, bound):
        qty, value, worst = 0, 0.0, None
        for price, available in depth:
            # Whole-share orders, never round displayed capacity up.
            take = min(math.floor(available), max_quantity-qty)
            if take > 0:
                qty += take
                value += price*take
                worst = price
            if qty >= max_quantity:
                break
        if not qty:
            return None
        # Buy rounds up to reach observed depth; sell rounds down. Check the
        # rounding still respects the bound before emitting an aggressive limit.
        price = round((math.ceil((worst-1e-10)/TICK) if action == 'buy'
                       else math.floor((worst+1e-10)/TICK))*TICK, 3)
        cfg = self.config
        marginal = bound-price if action == 'buy' else price-bound
        edge = marginal-cfg.fee-cfg.slippage
        threshold = cfg.min_edge if action == 'buy' else cfg.exit_edge
        if not MIN_PRICE <= price <= MAX_PRICE or edge < threshold-1e-9:
            return None
        expected = (bound*qty-value if action == 'buy' else value-bound*qty)-qty*(cfg.fee+cfg.slippage)
        return {'engine': self.tag, 'exchangeId': str(item['exchangeId']),
                'marketId': item['marketId'], 'title': item['title'], 'raceKey': item['raceKey'],
                'side': side, 'action': action, 'quantity': qty, 'price': price,
                'observedValue': round(value, 6), 'referenceBound': round(bound, 6),
                'edge': round(edge, 6), 'expectedProfit': round(expected, 6),
                'referenceTicker': item['reference']['ticker'], 'bookReceivedAt': item['book']['receivedAt'],
                'mappingStatus': item['mappingStatus'], 'executionEligible': False,
                'role': 'value_entry' if action == 'buy' else 'value_exit'}
