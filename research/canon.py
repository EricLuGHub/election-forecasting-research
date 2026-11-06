"""Canonical basket universe from settlement metadata (item 31). Pure.

The fixed STATEMAP list bakes in assumptions (50 states + DC, Senate /
Governor / House only, one R + one D each). This module enumerates R/D
pairs from contract metadata instead — group by (raceId, stageId,
electionDate, raceStage), require exactly one Republican + one Democratic
contract — and RECORDS every exclusion with its reason. Coverage gaps in
either direction (metadata finds what the list misses; list covers what
metadata cannot prove) become explicit hunting instructions.
"""
PARTIES = ('Republican', 'Democratic')


def _party(mk):
    t = str(mk.get('title', ''))
    has_r = 'Republican' in t
    has_d = 'Democratic' in t
    if has_r == has_d:
        return None
    return 'Republican' if has_r else 'Democratic'


def enumerate_pairs(markets):
    """(pairs, exclusions).

    pairs: [{'key': (raceId, stageId, electionDate, raceStage),
             'eids': {'Republican': eid, 'Democratic': eid},
             'titles': {...}}].
    exclusions: [(market_id_or_eid, reason)] — every non-paired market
    accounted for, no silent drops.
    """
    pairs, exclusions = [], []
    groups = {}
    for mk in markets:
        mid = mk.get('mid', mk.get('id', '?'))
        if mk.get('resolutionType') != 'Party Winner':
            exclusions.append((mid, 'non-party resolution'))
            continue
        key = tuple(mk.get(k) for k in
                    ('raceId', 'stageId', 'electionDate', 'raceStage'))
        if any(v is None for v in key):
            exclusions.append((mid, 'missing race metadata'))
            continue
        party = _party(mk)
        if party is None:
            exclusions.append((mid, 'no unique R/D party in title'))
            continue
        groups.setdefault(key, []).append((party, mk))
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        by_party = {}
        for party, mk in members:
            by_party.setdefault(party, []).append(mk)
        if set(by_party) != set(PARTIES):
            missing = set(PARTIES) - set(by_party)
            for party, mk in members:
                exclusions.append((mk.get('mid', mk.get('id', '?')),
                                   'single-party race, missing %s'
                                   % sorted(missing)))
            continue
        if any(len(by_party[p]) != 1 for p in PARTIES):
            for party, mk in members:
                exclusions.append((mk.get('mid', mk.get('id', '?')),
                                   'duplicate %s contracts (%d)'
                                   % (party, len(by_party[party]))))
            continue
        eids, titles = {}, {}
        for p in PARTIES:
            mk = by_party[p][0]
            eids[p] = mk.get('eid')
            titles[p] = mk.get('title')
        pairs.append({'key': key, 'eids': eids, 'titles': titles})
    return pairs, exclusions
