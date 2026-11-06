"""Item-32 marginal curve tests (synthetic ladders)."""
from research.marginal import curve, choose


def _ladder():
    # R leg deep (0.13 x 10k), D leg thin (0.87 x 400, then 0.80 x 10k)
    bids_r = [(0.13, 10000.0)]
    bids_d = [(0.87, 400.0), (0.80, 10000.0)]
    return bids_r, bids_d


def test_curve_concave_and_marginal():
    r, d = _ladder()
    rows = dict(curve(r, d, [100, 500, 1000, 2000]))
    # 100: (0.87+0.13) -> NO costs 0.87? no: NO_R = 1-0.13=0.87?? R YES 0.13
    # means R-NO ask 0.87: cost 87 + D-NO (1-0.87)=13 -> 100 total, edge 0
    assert rows[100] == 0.0
    assert rows[500] < 0  # D leg walks to 0.80: NO 0.20 x100 more
    assert rows[1000] < rows[500]


def test_choose_stops_at_dead_marginal():
    rows = [(500, 20.0), (1000, 22.0), (2000, 22.5)]
    # marginals: 20, 2, 0.5 -> $15 bar stops after 500 (concave: first
    # failure ends the search, later steps can only be thinner)
    assert choose(rows) == (500, 20.0)
    assert choose(rows, min_edge=1.0, min_per_share=0.001) == (1000, 22.0)


def test_choose_total_vs_marginal_bars():
    from research.marginal import choose
    # linear 2.5c/share book: small first steps pass on total, rate holds
    rows = [(250, 6.25), (500, 12.5), (1000, 25.0)]
    assert choose(rows) == (1000, 25.0)
    # thinning book: total clears but marginal rate dies -> stop early
    rows2 = [(500, 20.0), (1000, 22.0), (2000, 22.5)]
    assert choose(rows2) == (500, 20.0)
    # nothing clears total -> None (small steps aren't rescued)
    assert choose([(250, 6.25)]) is None


def test_cap_enforced_from_curve():
    from research.marginal import choose
    rows = [(250, 6.25), (500, 12.5), (1000, 25.0)]
    # cost(1000) ~= 975: passes 5000 cap, fails a 5-capital limit outright
    assert choose(rows, max_capital=5.0) is None
    assert choose(rows, max_capital=5000.0) == (1000, 25.0)
    # 970-cost candidate vs 5-capital: refused before bars consulted
    assert choose([(1000, 30.0)], max_capital=5.0) is None
