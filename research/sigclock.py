"""Signal-to-fill clock (backlog item 26). Measurement, not estimates.

For every journaled basket submission with fills, records submit time
(journal `at`), fill time (fills filledAt), and fill-vs-limit slippage per
leg (fill price vs the limit set from the depth walk). Reports latency
distribution and slippage totals: the measured cost of our execution speed.
Discovery-to-verify latency is bounded separately by session design
(verify+fire in one session); this module covers submit-to-fill.
"""
import argparse
import json
from datetime import datetime
from .client import ROOT


def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return None


def leg_clock(journal_entry, fills):
    """Per-leg [(orderId, submit_ts, fill_ts, latency_s, slip)] for one entry.

    Slip = fill price minus limit price in fill-side units (positive = paid
    worse than limit; limits should bind, so nonzero slip is information).
    """
    body = (journal_entry or {}).get('body', {})
    legs = body.get('legs', [])
    submit_ts = _ts((journal_entry or {}).get('at'))
    response = ((journal_entry or {}).get('response') or {}).get('results', [])
    out = []
    indexed = list(zip(legs, response if isinstance(response, list) else []))
    for leg, res in indexed:
        data = (res or {}).get('data', {})
        oid = data.get('orderId')
        fill = next((f for f in fills
                     if str(f.get('orderId', '')) == str(oid)), None)
        fill_ts = _ts((fill or {}).get('filledAt'))
        lat = (fill_ts - submit_ts) if fill_ts and submit_ts else None
        slip = None
        try:
            if fill is not None:
                slip = float(fill.get('price')) - float(leg.get('price'))
        except (TypeError, ValueError):
            pass
        out.append({'orderId': oid, 'exchangeId': leg.get('exchangeId'),
                    'latency_s': round(lat, 1) if lat is not None else None,
                    'slip': round(slip, 4) if slip is not None else None,
                    'traded': data.get('quantityTraded'),
                    'remaining': data.get('remainingQuantity')})
    return out


def summarize(clocks):
    lats = [c['latency_s'] for legs in clocks for c in legs
            if c['latency_s'] is not None]
    slips = [c['slip'] for legs in clocks for c in legs
             if c['slip'] is not None]
    n = len(lats)
    return {'legs_measured': n,
            'latency_p50': sorted(lats)[n // 2] if n else None,
            'latency_max': max(lats) if lats else None,
            'mean_abs_slip': round(sum(abs(s) for s in slips) / len(slips), 4) if slips else None,
            'worst_slip': min(slips) if slips else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-prefix', default='')
    args = parser.parse_args()
    journal = json.loads((ROOT / 'data/execution_journal.json').read_text())
    from .client import Client
    client = Client()
    fills = client.pages('/tournaments/midterm-elections/portfolio/fills', limit=200)
    clocks = []
    for key, entry in journal.items():
        if args.key_prefix and not key.startswith(args.key_prefix):
            continue
        if (entry or {}).get('status') != 'confirmed':
            continue
        legs = leg_clock(entry, fills if isinstance(fills, list) else [])
        if legs:
            clocks.append(legs)
            print(json.dumps({'key': key, 'legs': legs})[:300], flush=True)
    print(json.dumps({'summary': summarize(clocks),
                      'baskets': len(clocks)}, indent=2))


if __name__ == '__main__':
    main()
