"""Settlement-basis map (backlog item 64). Pure.

Winner, certification, taking-office and chamber-control contracts can
differ — a pair thesis dies when its legs settle on different semantics.
Per leg, classify from node metadata; per pair, REQUIRE identical
semantics (contractType, resolutionType, settlement_date, race scope);
winnerName must differ (R vs D). Anything else REJECTS the pair (wording
defeats the thesis) or parks it in REVIEW (null fields — unmeasurable,
not assumed fine).

Singles (YES-shorts) get a classification + third-party note, not a
pair verdict. A Kalshi quote is a reference input elsewhere, never a
hedge here — no cross-venue offsets are booked.
"""
MATCH_FIELDS = ('contractType', 'resolutionType', 'settlement_date',
                'raceId', 'stageId', 'electionDate', 'raceStage')


def classify(root):
    """(basis_class, detail). Classes: election-outcome | control | other
    | unknown (null metadata — refused, not defaulted)."""
    if not isinstance(root, dict):
        return 'unknown', {'reason': 'no node'}
    cd = root.get('contract_details') or {}
    rtype = cd.get('resolutionType')
    ctype = root.get('contract_type') or cd.get('contractType')
    if rtype is None and ctype is None:
        return 'unknown', {'reason': 'null semantics'}
    if rtype == 'Party Winner':
        cls = 'election-outcome'
    elif rtype is not None and 'ontrol' in str(rtype):
        cls = 'control'
    elif ctype is not None and 'ontrol' in str(ctype):
        cls = 'control'
    else:
        cls = 'other'
    return cls, {'contract_type': ctype, 'resolution': rtype,
                 'settlement_date': root.get('settlement_date'),
                 'settled_with': root.get('settled_with')}


def pair_basis(name, root_r, root_d, third_party=False):
    """(verdict, detail). PASS / REJECT / REVIEW."""
    cls_r, d_r = classify(root_r)
    cls_d, d_d = classify(root_d)
    detail = {'pair': name, 'leg_r': d_r, 'leg_d': d_d,
              'third_party_listed': bool(third_party)}
    if 'unknown' in (cls_r, cls_d):
        detail.update(verdict='review', why='null semantics on a leg')
        return 'review', detail
    if cls_r != cls_d or cls_r != 'election-outcome':
        detail.update(verdict='reject',
                      why=('basis classes %s/%s — wording defeats pair thesis'
                           % (cls_r, cls_d)))
        return 'reject', detail
    cd_r = (root_r.get('contract_details') or {})
    cd_d = (root_d.get('contract_details') or {})
    scope_r = tuple(cd_r.get(k) for k in
                    ('raceId', 'stageId', 'electionDate', 'raceStage'))
    scope_d = tuple(cd_d.get(k) for k in
                    ('raceId', 'stageId', 'electionDate', 'raceStage'))
    if scope_r != scope_d or any(v is None for v in scope_r):
        detail.update(verdict='review', why='scope mismatch or null')
        return 'review', detail
    if root_r.get('settlement_date') != root_d.get('settlement_date'):
        detail.update(verdict='review', why='settlement dates differ')
        return 'review', detail
    if cd_r.get('winnerName') == cd_d.get('winnerName'):
        detail.update(verdict='reject', why='same winnerName both legs')
        return 'reject', detail
    detail.update(verdict='pass', why='identical election-outcome semantics')
    return 'pass', detail
