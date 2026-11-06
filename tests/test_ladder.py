"""Item-87 ladder tests (NH measured clips)."""
from research.ladder import marginals, recommend, NH_MEASURED


def test_marginals_match_record():
    rows = marginals(NH_MEASURED)
    assert rows[0]['edge'] == 35.00  # 1000: 1000-965
    assert rows[1]['marginal_edge'] == 33.48  # 2000 adds +33.48
    assert rows[3]['marginal_per_share'] == 0.0052  # 10k step halves rate


def test_recommend_stops_where_marginal_dies():
    rec = recommend(NH_MEASURED)
    rows = marginals(NH_MEASURED)
    # 2000->5000 marginal: (140.29-68.48)/6000 = 1.196c >= 1c and +71.81 >= 15
    # so the rule actually clears 5000 on NH's deep book; 10k fails (0.52c)
    assert rows[2]['marginal_per_share'] >= 0.01
    assert rows[3]['marginal_per_share'] < 0.01
    assert rec['size'] == 5000
