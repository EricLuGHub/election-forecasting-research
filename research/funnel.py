"""Blocked-opportunity funnel (backlog item 5).

Counts each gate of the basket pipeline and attaches rejected dollar value
where measurable, so the bottleneck is a number, not a narrative:

  universe -> fresh books -> top-book edge -> depth edge ($15 rule)
    -> capital eligible -> submitted -> filled -> closed/exited

Gate drops are LOSSES of edge (refused or blocked), not just counts. Inputs
are recorded fire-round evidence (verified depth walks), not estimates.
"""
import json


def funnel(rounds):
    """rounds: list of dicts with fired:[{edge}], refused:[{edge, reason}],
    blocked:[{edge, reason}]. Returns gate table with $ attached."""
    gates = [
        ('depth_walked', 0.0, 0),
        ('fired', 0.0, 0),
        ('refused_edge', 0.0, 0),
        ('blocked_capital', 0.0, 0),
    ]
    table = {name: {'n': 0, 'edge': 0.0} for name, _, _ in gates}
    reasons = {}
    for rnd in rounds:
        for f in rnd.get('fired', []):
            table['fired']['n'] += 1
            table['fired']['edge'] += float(f.get('edge', 0))
            table['depth_walked']['n'] += 1
            table['depth_walked']['edge'] += float(f.get('edge', 0))
        for f in rnd.get('refused', []):
            table['refused_edge']['n'] += 1
            table['refused_edge']['edge'] += float(f.get('edge', 0))
            table['depth_walked']['n'] += 1
            table['depth_walked']['edge'] += float(f.get('edge', 0))
            reasons[f.get('reason', 'rule')] = reasons.get(f.get('reason', 'rule'), 0) + 1
        for f in rnd.get('blocked', []):
            table['blocked_capital']['n'] += 1
            table['blocked_capital']['edge'] += float(f.get('edge', 0))
    for gate in table.values():
        gate['edge'] = round(gate['edge'], 2)
    return {'gates': table, 'refusal_reasons': reasons}


def bottleneck(report):
    """Names the binding gate: largest rejected edge still recoverable."""
    g = report['gates']
    refused = g['refused_edge']['edge']
    blocked = g['blocked_capital']['edge']
    if blocked > refused and blocked > 0:
        return ('capital', blocked)
    if refused > 0:
        return ('edge_threshold', refused)
    return ('opportunity_supply', 0.0)


OCT4_ROUNDS = [
    {'fired': [{'edge': 46.07}],
     'refused': [], 'blocked': []},  # NH
    {'fired': [{'edge': 28.03}, {'edge': 35.00}, {'edge': 32.76},
               {'edge': 19.82}, {'edge': 20.00}],
     'refused': [], 'blocked': []},  # R1
    {'fired': [{'edge': 20.53}, {'edge': 25.00}, {'edge': 20.00}],
     'refused': [{'edge': 10.0, 'reason': 'below_15_rule'},
                 {'edge': 10.5, 'reason': 'below_15_rule'}],
     'blocked': [{'edge': 30.0, 'reason': 'total_cap_20k'},
                 {'edge': 25.0, 'reason': 'total_cap_20k'},
                 {'edge': 25.0, 'reason': 'total_cap_20k'},
                 {'edge': 20.0, 'reason': 'total_cap_20k'}]},  # R2 (+cap blocks)
    {'fired': [{'edge': 30.0}, {'edge': 30.0}, {'edge': 20.0}, {'edge': 20.0},
               {'edge': 17.46}],
     'refused': [{'edge': 14.4, 'reason': 'below_15_rule'}],
     'blocked': []},  # R3
    {'fired': [{'edge': 20.0}, {'edge': 19.5}],
     'refused': [{'edge': 13.38, 'reason': 'below_15_rule'}],
     'blocked': []},  # R4
    {'fired': [{'edge': 20.0}, {'edge': 20.04}],
     'refused': [{'edge': 12.96, 'reason': 'below_15_rule'}],
     'blocked': []},  # R5
    {'fired': [],
     'refused': [{'edge': 7.5, 'reason': 'below_15_rule'}],
     'blocked': []},  # R6
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    report = funnel(OCT4_ROUNDS)
    name, value = bottleneck(report)
    print(json.dumps({'report': report, 'bottleneck': [name, value]}, indent=2))


if __name__ == '__main__':
    main()
