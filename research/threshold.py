"""$15-rule study (backlog item 33). Shadow comparison only; live rule unchanged.

Uses recorded fire-round outcomes (fired edges + refused edges at refusal
time). Cost per basket inferred from its floor (cost = floor - edge), which
holds exactly for full-fill buy baskets. Metrics per candidate threshold T:
captured edge, basket count, refused value left behind, average edge/basket,
return on locked cash, and profit per capital-day over a 30-day hold.
Operational session cost is noted separately, not invented.
"""
import json

# (edge, floor) for every depth-walked basket, fired or refused, Oct 4-5.
# Refused edges are values AT refusal (decay-aware counterfactuals noted).
FIRED = [
    (46.07, 2000.0), (28.03, 1000.0), (35.00, 1000.0), (32.76, 1000.0),
    (19.82, 1000.0), (20.00, 1000.0), (20.53, 1000.0), (25.00, 1000.0),
    (20.00, 1000.0), (30.00, 1000.0), (30.00, 1000.0), (20.00, 1000.0),
    (20.00, 1000.0), (17.46, 1000.0), (20.00, 1000.0), (19.50, 1000.0),
    (20.00, 1000.0), (20.04, 1000.0),
]
REFUSED = [
    (10.00, 1000.0), (10.50, 1000.0), (14.40, 1000.0), (13.38, 1000.0),
    (12.96, 1000.0), (7.50, 500.0),
]
HOLD_DAYS = 30.0


def evaluate(threshold):
    fired = [(e, f) for e, f in FIRED if e >= threshold]
    refused = [(e, f) for e, f in FIRED + REFUSED if e < threshold]
    cap = lambda rows: sum(f - e for e, f in rows)
    prof = lambda rows: sum(e for e, f in rows)
    out = {'threshold': threshold,
           'fired_n': len(fired), 'captured': round(prof(fired), 2),
           'refused_n': len(refused), 'refused_value': round(prof(refused), 2)}
    if fired:
        out['avg_edge'] = round(prof(fired) / len(fired), 2)
        out['roc'] = round(prof(fired) / cap(fired), 4)
        out['per_capital_day'] = round(prof(fired) / cap(fired) / HOLD_DAYS, 6)
    if refused:
        out['refused_avg'] = round(prof(refused) / len(refused), 2)
        out['refused_roc'] = round(prof(refused) / cap(refused), 4)
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    for threshold in (5.0, 10.0, 15.0, 20.0, 25.0):
        print(json.dumps(evaluate(threshold)))


if __name__ == '__main__':
    main()
