"""Resolution-lag map: venue rules + runoff inventory (item 79). Pure.

Likely is not settled. Per held race, from verified sources (dated):
- runoff risk: GA/MS general runoffs Dec 1 on sub-majority (sourced
  2026-10-06); LA general: NO runoff under the 2026 closed-primary
  system (sourced 2026-10-06 — earlier worry retired by evidence).
- SIG: auto-settle from sources every 4h; runoffs + chamber manually by
  admin once official; standings lock after ALL settle (delay, not loss).
- Kalshi (reference): inauguration/consensus basis (can precede SIG on
  clear races via accelerated determination; waits with SIG on runoffs).
Scenario lags per position: clear (auto ~11-04), runoff (manual ~Dec,
  capital dead an extra month), contested (admin timing unknown).
A delayed payout at 89% idle cash costs carry, not principal — size the
complaint accordingly.
"""
RUNOFF_STATES_2026 = {'GA', 'MS'}


def race_lag(state, contract='party'):
    """(lag_class, detail). lag_class: clear | runoff-risk | manual."""
    if contract == 'control':
        return 'manual', {'why': 'chamber settled manually by admin'}
    if state in RUNOFF_STATES_2026:
        return 'runoff-risk', {'why': 'majority rule; Dec 1 runoff if split',
                               'states': sorted(RUNOFF_STATES_2026)}
    return 'clear', {'why': 'plurality decides Nov 3; auto-settle'}


def horizon_days(lag_class, base_days=29):
    if lag_class == 'runoff-risk':
        return base_days + 28
    if lag_class == 'manual':
        return None  # admin timing unknown — refused, not zero
    return base_days
