"""Item-72 newswire tests (synthetic only, no network)."""
from research.newswire import story, dedup, confirm, route


def _s(race, event, at, source, tier='outlet'):
    return story(race, event, at, source, tier, 'http://x/%s' % source)


def test_syndication_clusters():
    stories = [_s('IA-Gov', 'marist-poll', '2026-09-20T00:00:00+00:00', 'rcp'),
               _s('IA-Gov', 'marist-poll', '2026-09-21T00:00:00+00:00',
                  'forecast', 'pollster'),
               _s('IA-Gov', 'siena-poll', '2026-10-01T00:00:00+00:00', 'nyt')]
    clusters = dedup(stories)
    assert len(clusters) == 2
    marist = [c for c in clusters if c['event'] == 'marist-poll'][0]
    assert len(marist['confirmations']) == 2
    assert marist['wire_sources'] == ['forecast']


def test_tier1_confirms_single_blog_does_not():
    ok, _ = confirm({'confirmations': [('marist', 'pollster')]})
    assert ok is True
    ok, why = confirm({'confirmations': [('blog', 'blog')]})
    assert ok is False and 'unconfirmed' in why


def test_two_outlets_confirm():
    ok, _ = confirm({'confirmations': [('a', 'outlet'), ('b', 'outlet')]})
    assert ok is True
    ok, _ = confirm({'confirmations': [('a', 'outlet'), ('a', 'outlet')]})
    assert ok is False  # same outlet twice is not corroboration


def test_route_and_refusals():
    assert story('', 'e', 't', 's', 'outlet', 'l') is None
    assert story('r', 'e', 't', 's', 'vibes', 'l') is None
    clusters = [{'race': 'IA', 'event': 'e',
                 'confirmations': [('p', 'pollster')]}]
    assert route(clusters) == [('IA', 'e', 'tier-1 source present')]
    assert route([]) == []
