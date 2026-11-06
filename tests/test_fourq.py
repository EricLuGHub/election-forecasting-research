"""Item-3 four-quantity tests (fake books/positions)."""
from research.fourq import liquidation


def test_liquidation_splits_depth_and_marks():
    positions = [
        {'exchangeId': 'A', 'quantity': 100, 'marketValue': 50.0, 'costBasis': 40.0},
        {'exchangeId': 'B', 'quantity': -200, 'marketValue': 160.0, 'costBasis': 170.0},
        {'exchangeId': 'C', 'quantity': 10, 'marketValue': 5.0, 'costBasis': 4.0},
    ]
    books = {'A': {'bids': [{'price': 0.5, 'quantity': 1000}], 'asks': []},
             'B': {'bids': [], 'asks': [{'price': 0.20, 'quantity': 1000}]}}
    import research.fourq as F
    orig_top = F.TOP_N
    F.TOP_N = 2
    try:
        proceeds, marks, basis = liquidation(positions, books)
    finally:
        F.TOP_N = orig_top
    # A long: 100 @ YES bid 0.5 = 50. B short-YES: 200 @ NO bid (1-0.2) = 160.
    assert proceeds == 210.0
    assert marks == 5.0  # C stays at marks, labeled
    assert basis == 214.0
