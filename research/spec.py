"""One-page experiment specifications (backlog item 81). Process as code.

Every new engine files a spec BEFORE running: mechanism, baseline, window,
evidence minimum, deadline, budget, caps, loss limit, and keep/stop/promotion
criteria. check() refuses incomplete specs — an engine without a spec cannot
reach KEEP TESTING, let alone promotion. Versions are immutable once filed:
changed terms get a new version, never an edit.
"""
import json

REQUIRED = ('id', 'version', 'hypothesis', 'mechanism', 'baseline',
            'data_window', 'evidence_minimum', 'review_deadline',
            'runtime_budget', 'allocation', 'exposure_cap', 'max_loss',
            'keep_criteria', 'stop_criteria', 'promotion_criteria')


def check(spec):
    """(ok, missing_fields). Pure; no I/O."""
    if not isinstance(spec, dict):
        return False, list(REQUIRED)
    missing = [f for f in REQUIRED
               if f not in spec or spec[f] in (None, '')]
    return (len(missing) == 0), missing


def render(spec):
    ok, missing = check(spec)
    lines = ['# Experiment spec: %(id)s v%(version)s' % {
        'id': spec.get('id', '?'), 'version': spec.get('version', '?')}]
    for field in REQUIRED[2:]:
        lines.append('- %s: %s' % (field, spec.get(field)))
    lines.append('- status: %s' % ('COMPLETE' if ok else 'INCOMPLETE: %s' % missing))
    return '\n'.join(lines) + '\n'


E8_EXAMPLE = {
    'id': 'E8-CONVEXIT', 'version': 'v1-filed-c184',
    'hypothesis': 'Volatile-name baskets become bankable before settlement; '
                  'joint exit flags beat single-position flags.',
    'mechanism': 'Joint NO-exit valuation at live depth vs ledger cost; '
                 '0.5c/share + $5 absolute bars; whole baskets only.',
    'baseline': 'exit.py single-position paper flags.',
    'data_window': '2026-10-04 through 2026-10-11 (7 days from c126).',
    'evidence_minimum': '3 flags rescored at depth.',
    'review_deadline': '2026-10-11',
    'runtime_budget': '2x/day cron reads + one-shots; no capital at risk.',
    'allocation': 'paper only, $0 live.',
    'exposure_cap': '$0 live exposure.',
    'max_loss': '$0 (paper).',
    'keep_criteria': 'Cron firing + flags rescoring within 20% of stated edge.',
    'stop_criteria': '>50% false flags on rescore, or systematic misvaluation.',
    'promotion_criteria': 'Live-exit wiring proposed via E1 owner ONLY; '
                           'never unilateral.',
}
