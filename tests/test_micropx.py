"""Item-52 microprice tests (synthetic only, no network)."""
from research.micropx import microprice, midpoint, anchor_gap


def test_microprice_weights_thin_side():
    # Thin bids -> micro near ask.
    assert microprice([(0.5, 100)], [(0.52, 900)]) == round((0.52 * 100 + 0.5 * 900) / 1000, 4)
    assert midpoint([(0.5, 100)], [(0.52, 100)]) == 0.51
    assert anchor_gap([(0.5, 100)], [(0.52, 100)]) == 0.0  # balanced: no info


def test_refusals():
    assert microprice([], [(0.5, 1)]) is None
    assert microprice([(0.5, 0)], [(0.52, 0)]) is None
    assert anchor_gap(None, [(0.5, 1)]) is None
