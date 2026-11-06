"""Microprice vs midpoint quote anchor (backlog item 52). Pure.

microprice = (ask x bid_size + bid x ask_size) / (bid_size + ask_size):
size-weights the mid toward the thinner side. On stocks it predicts the
next move; here large displayed queues can vanish (c191/c220), so the
weight may point at ghosts. Test head-to-head: microprice-deviation vs
midpoint-deviation for next-move direction on sized snapshots. An anchor
that never differs from mid, or differs only when sizes flicker, is not
an anchor — record which.
"""


def microprice(bids, asks):
    """Size-weighted mid from top levels, or None (no sizes, no signal)."""
    try:
        bp, bs = float(bids[0][0]), float(bids[0][1])
        ap, aq = float(asks[0][0]), float(asks[0][1])
    except (IndexError, TypeError, ValueError):
        return None
    if bs + aq <= 0:
        return None
    return round((ap * bs + bp * aq) / (bs + aq), 4)


def midpoint(bids, asks):
    try:
        return (float(bids[0][0]) + float(asks[0][0])) / 2
    except (IndexError, TypeError, ValueError):
        return None


def anchor_gap(bids, asks):
    """(micro - mid) in price units, or None. Zero gap = no information
    beyond mid (common when sizes balance or books are symmetric)."""
    mp, mid = microprice(bids, asks), midpoint(bids, asks)
    if mp is None or mid is None:
        return None
    return round(mp - mid, 4)
