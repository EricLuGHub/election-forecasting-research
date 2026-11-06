"""Event-sensitive cancellation + quote lifetimes (backlog item 57). Pure.

A 120-second timer alone is stale-price protection by clock, not by
economics. Cancel triggers (predeclared thresholds, not tuned):
- BOOK: touch moved >= CANCEL_MOVE against the quote side.
- REFERENCE: external fair value moved >= CANCEL_MOVE against.
- AGE: hard cap MAX_AGE_S regardless (stale-price backstop).
- PRIORITY: keep the resting quote while |fresh - resting| <= HYST_TICKS
  (v4 already does 2-tick hysteresis — preserved here, not reinvented).
Replay: hypothetical resting quotes (side, price, start) over book
series; report cancel rate, median time-to-cancel, and adverse moves
that fired no cancel (misses). Versus baseline: timer-only (cancel at
MAX_AGE always). The comparison that matters: earlier cancels on real
adversity, not more cancels overall.
"""
CANCEL_MOVE = 0.015
MAX_AGE_S = 120.0
HYST_TICKS = 0.01


def should_cancel(side, price, book_bid, book_ask, ref_then, ref_now, age_s,
                  cancel_move=CANCEL_MOVE, max_age=MAX_AGE_S):
    """(cancel: bool, reason). side: 'buy'|'sell' (our resting side).
    Prices numeric; refs None-able (no reference, no reference trigger)."""
    try:
        p = float(price)
        age = float(age_s)
    except (TypeError, ValueError):
        return False, 'bad inputs'
    if age >= max_age:
        return True, 'age cap'
    try:
        bb, ba = float(book_bid), float(book_ask)
    except (TypeError, ValueError):
        return False, 'no book'
    touch = bb if side == 'buy' else ba
    # Resting ahead of a falling/rising market fills first and worst:
    # buy left above a dropped bid, sell left below a lifted ask.
    adverse = (p - touch) if side == 'buy' else (touch - p)
    if adverse >= cancel_move:
        return True, 'book moved %.3f against' % adverse
    if ref_then is not None and ref_now is not None:
        try:
            rm = float(ref_now) - float(ref_then)
        except (TypeError, ValueError):
            return False, 'bad reference'
        ref_adv = -rm if side == 'buy' else rm
        if ref_adv >= cancel_move:
            return True, 'reference moved %.3f against' % ref_adv
    return False, 'hold'


def keep_priority(resting_price, fresh_price, hyst=HYST_TICKS):
    """True = keep resting (within hysteresis). Preserves queue priority
    when the economic quote remains valid."""
    try:
        return abs(float(fresh_price) - float(resting_price)) <= float(hyst)
    except (TypeError, ValueError):
        return False
