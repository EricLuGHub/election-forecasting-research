"""Item-101 single-tick tests (synthetic only, no network)."""
from research.ticks import to_vticks, from_vticks, display, VENUE_TICK
from research.execution import TICK


def test_venue_truth_single():
    assert VENUE_TICK == TICK == 0.005
    assert to_vticks(0.105) == 21
    assert to_vticks(0.10) == 20
    assert from_vticks(21) == 0.105
    # Adjacent legal prices stay distinct (the item's criterion).
    assert to_vticks(0.10) != to_vticks(0.105)
    assert to_vticks('junk') is None and from_vticks('junk') is None


def test_display_both_units():
    assert display(0.105) == {'susqies': 0.105, 'vticks': 21}
    assert display(None) is None
