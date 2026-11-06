"""News extraction for routing research + rechecks (backlog item 72). Pure.

Text never touches prices here — it routes ATTENTION (which races get
rechecks). Pipeline:
1. story(): (race, event, pub_at, source, link) — all five required;
   dateless or raceless items refuse (no phantom catalysts).
2. dedup(): same race+event within SYNDICATION_WINDOW from different
   outlets = ONE story with N confirmations (syndication is repetition,
   not corroboration — but repetition of a wire story still counts the
   underlying single source once; see tiers).
3. confirm(): tier-1 (wire/original pollster/registrar) OR >=2 independent
   tier-2 outlets. Single-blog rumors never route.
4. route(): confirmed stories -> race recheck list with reason; the
   recheck itself runs the bars (triggers/curves), never the headline.

Evaluation protocol (predeclared, needs live operation): over 2 weeks,
fraction of routed rechecks that clear bars vs baseline trigger rate.
Text earns price-influence only by beating that baseline. Until then:
routing only.
"""
SYNDICATION_H = 72.0
TIER1 = {'wire', 'pollster', 'registrar', 'official'}


def story(race, event, pub_at, source, tier, link):
    if not all([race, event, pub_at, source, link]):
        return None
    if tier not in TIER1 | {'outlet', 'blog'}:
        return None
    return {'race': race, 'event': event, 'pub_at': pub_at,
            'source': source, 'tier': tier, 'link': link}


def _ts(at):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def dedup(stories, window_h=SYNDICATION_H):
    """Cluster by (race, event) within window. Returns [{race, event,
    first_at, confirmations: [(source, tier)], underlying: tier-1 sources
    or 'single-wire' note}]."""
    groups = {}
    for s in stories:
        if s is None:
            continue
        t = _ts(s['pub_at'])
        if t is None:
            continue
        key = (s['race'], s['event'])
        g = groups.setdefault(key, [])
        g.append((t, s))
    out = []
    for (race, event), items in sorted(groups.items()):
        items.sort()
        first = items[0][0]
        confs = [(s['source'], s['tier']) for _, s in items
                 if _ts(s['pub_at']) - first <= window_h * 3600]
        t1 = sorted({src for src, tier in confs if tier in TIER1})
        out.append({'race': race, 'event': event,
                    'first_at': items[0][1]['pub_at'],
                    'confirmations': confs,
                    'wire_sources': t1 if t1 else ['single-wire-or-less']})
    return out


def confirm(cluster):
    """True when routable: tier-1 present, or >=2 tier-2+ outlets."""
    tiers = [t for _, t in cluster['confirmations']]
    if any(t in TIER1 for t in tiers):
        return True, 'tier-1 source present'
    outlets = {s for s, t in cluster['confirmations'] if t == 'outlet'}
    if len(outlets) >= 2:
        return True, 'two independent outlets'
    return False, 'unconfirmed single/blog'


def route(clusters):
    """Confirmed clusters -> [(race, event, reason)]."""
    routed = []
    for c in clusters:
        ok, why = confirm(c)
        if ok:
            routed.append((c['race'], c['event'], why))
    return routed
