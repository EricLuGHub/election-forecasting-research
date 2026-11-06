"""Election-night results model readiness (backlog item 78). Pure.

On Nov 3 the question flips from polls to COUNTED votes with composition
risk: early vote share misleads when outstanding ballots lean differently.
Model contract (built now, fed on the night):
- FEED records: (race, ts, counted_D, counted_R, est_remaining, source).
  Sources: AP/Edison/DDHQ official feeds (access TBD — survey below).
- Composition estimate: outstanding = total_est - counted; remaining
  lean bounded by county/batch history, NEVER assumed neutral without
  evidence (early-vote skew cuts both ways).
- projected_margin = (counted_D - counted_R + lean*remaining) / total_est
  with uncertainty = |lean_hi - lean_lo| * remaining / total_est.
- CALL rule: project only when the full uncertainty interval clears zero
  AND remaining/total < CALLOFF (predeclared 5%). Otherwise: too early
  (an explicit state, not a shrug).
Backtest harness: replay archived sequences when available (none on
hand — synthetic validation only; the harness interface is the
deliverable, honesty about data first).
"""
CALLOFF = 0.05


def project(counted_d, counted_r, remaining, lean, lean_spread, total_est):
    """(margin, uncertainty) or None on bad inputs. lean: expected D-R
    margin fraction among remaining; lean_spread: its uncertainty width."""
    try:
        cd, cr, rem = float(counted_d), float(counted_r), float(remaining)
        ln, ls, tot = float(lean), float(lean_spread), float(total_est)
    except (TypeError, ValueError):
        return None
    if tot <= 0 or rem < 0 or rem > tot:
        return None
    margin = ((cd - cr) + ln * rem) / tot
    unc = abs(ls) * rem / tot
    return {'margin': round(margin, 4), 'uncertainty': round(unc, 4)}


def call_state(projection, remaining_frac, calloff=CALLOFF):
    """'call-D' / 'call-R' / 'too-early'. Interval must clear zero AND
    remaining share under the cap."""
    if projection is None:
        return 'too-early'
    try:
        rf = float(remaining_frac)
    except (TypeError, ValueError):
        return 'too-early'
    m, u = projection['margin'], projection['uncertainty']
    if rf > calloff:
        return 'too-early'
    if m - u > 0:
        return 'call-D'
    if m + u < 0:
        return 'call-R'
    return 'too-early'
