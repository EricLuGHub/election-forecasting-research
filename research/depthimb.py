"""Depth imbalance as toxicity filter (backlog item 50). Pure.

Equity-market feature, SIG-unproven coefficients: imbalance =
(bid_size − ask_size) / (bid_size + ask_size) at top of book predicts the
next mid move on stocks (Gould–Bonart motivate the FEATURE, never the
weights — fit nothing from equities here). Test on OUR books:
- prediction: sign agreement between imbalance and next-round mid move
  (hit rate + mean move by imbalance bin).
- conditional fills: joined-quote outcomes split by imbalance regime
  (does resting into heavy-ask books bleed?).
Verdict needs both: prediction without fill economics is trivia, and
fill economics without prediction is noise. Small-n honesty throughout.
"""


def imbalance(bids, asks):
    """Top-of-book (bid_size − ask_size)/(bid_size + ask_size) in YES
    units. None when empty/bad (no book, no signal — refused)."""
    try:
        b = float(bids[0][1])
        a = float(asks[0][1])
    except (IndexError, TypeError, ValueError):
        return None
    if b + a <= 0:
        return None
    return round((b - a) / (b + a), 3)


def mid_of(bids, asks):
    try:
        return (float(bids[0][0]) + float(asks[0][0])) / 2
    except (IndexError, TypeError, ValueError):
        return None


def hit_rate(rounds):
    """rounds: [(imbalance, next_mid_move)] -> {agree, n, mean_move}.
    Agreement = same sign (zero moves excluded, not counted either way)."""
    agree, moves, n = 0, [], 0
    for imb, mv in rounds:
        try:
            imb, mv = float(imb), float(mv)
        except (TypeError, ValueError):
            continue
        if mv == 0:
            continue
        n += 1
        moves.append(mv)
        if (imb > 0) == (mv > 0):
            agree += 1
    if n == 0:
        return None
    import statistics
    return {'n': n, 'hit_rate': round(agree / n, 3),
            'mean_move': round(sum(moves) / n, 4),
            'sd_move': round(statistics.pstdev(moves), 4) if n > 1 else 0.0}
