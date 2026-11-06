"""Order-flow imbalance vs static depth (backlog item 51). Pure.

Static depth (item 50) proved near-constant on these books. The live
question is FLOW: bid/ask size CHANGES plus signed trade flow between
snapshots. OFI proxy per interval: Δbid_size − Δask_size (top level) +
signed trade volume (buys +, sells −; side from trade records where
present, unsigned volume excluded from sign but counted in activity).
Compare head-to-head on the same rounds: static imbalance sign vs OFI
sign for next-move direction. Cancellations unobserved (c215) — OFI
here is net visible flow, labeled as such; hidden cancels bias it
toward zero, never away (stated direction of bias).
"""


def ofi(bids0, asks0, bids1, asks1, trades=None):
    """Net visible flow between two snapshots + signed trades in between.
    Returns (ofi_value, detail) or (None, reason). Sizes in YES units."""
    try:
        db = float(bids1[0][1]) - float(bids0[0][1])
        da = float(asks1[0][1]) - float(asks0[0][1])
    except (IndexError, TypeError, ValueError):
        return None, 'bad books'
    signed = 0.0
    unsigned = 0.0
    for t in trades or []:
        try:
            size = float(t.get('size', 0))
        except (TypeError, ValueError, AttributeError):
            continue
        side = str(t.get('side', '')).lower()
        if side in ('yes', 'buy', 'bid'):
            signed += size
        elif side in ('no', 'sell', 'ask'):
            signed -= size
        else:
            unsigned += size
    return round(db - da + signed, 1), {'d_bid': round(db, 1),
                                        'd_ask': round(da, 1),
                                        'signed_trades': round(signed, 1),
                                        'unsigned_vol': round(unsigned, 1)}


def head_to_head(rounds):
    """rounds: [(static_imb, ofi, next_move)] -> comparison dict."""
    s_agree = o_agree = n = 0
    for imb, flow, mv in rounds:
        try:
            imb, flow, mv = float(imb), float(flow), float(mv)
        except (TypeError, ValueError):
            continue
        if mv == 0:
            continue
        n += 1
        if (imb > 0) == (mv > 0):
            s_agree += 1
        if (flow > 0) == (mv > 0):
            o_agree += 1
    if n == 0:
        return None
    return {'n': n, 'static_hit': round(s_agree / n, 3),
            'flow_hit': round(o_agree / n, 3)}
