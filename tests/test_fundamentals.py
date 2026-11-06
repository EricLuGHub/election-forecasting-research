"""Item-74 fundamentals tests (synthetic only, no network)."""
from research.fundamentals import record, lean_of, agree


def test_record_gaps_explicit():
    assert record('VA-05', 'R+6', 'R', 'Likely R', '2026-09-25', '2026-10-06') is not None
    assert record('VA-05', None, 'R', 'Likely R', 'd', 'd') is None


def test_lean_parsing():
    mk = lambda c: {'cook': c}
    assert lean_of(mk('Likely R')) == 'R'
    assert lean_of(mk('Solid D')) == 'D'
    assert lean_of(mk('Toss Up')) is None
    assert lean_of(mk('Lean D')) == 'D'
    assert lean_of(None) is None


def test_agree():
    row = record('VA-05', 'R+6', 'R', 'Likely R', '2026-09-25', '2026-10-06')
    assert agree(row, 'R') == {'agree': True, 'fundamentals': 'R', 'sig': 'R'}
    assert agree(row, 'D')['agree'] is False
    assert agree(row, None) is None
