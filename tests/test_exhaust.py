"""Item-68 exhaustion-fade tests (synthetic only, no network)."""
from research.exhaust import to_books, triggers, simulate


def _rows(mids, spreads=None, t0=1_000_000, step=600):
    from datetime import datetime, timezone
    rows = []
    for i, m in enumerate(mids):
        s = (spreads[i] if spreads else 0.01)
        at = datetime.fromtimestamp(t0 + i * step,
                                    tz=timezone.utc).isoformat()
        rows.append((at, 'e', m - s / 2, m + s / 2))
    return rows


def test_exhaustion_win():
    # Dip to 0.45, spread refills, ticks back up, reverts through pre-mid.
    mids = [0.5] * 6 + [0.47, 0.45, 0.46, 0.48, 0.50, 0.52] + [0.52] * 20
    sp = [0.01] * 6 + [0.05, 0.05, 0.01, 0.01, 0.01, 0.01] + [0.01] * 20
    books = to_books(_rows(mids, sp))
    r = simulate(books['e'])
    assert r['n_trig'] >= 1 and r['win'] >= 1


def test_no_refill_no_trigger():
    # Dip with spread staying wide: never triggers.
    mids = [0.5] * 6 + [0.45] + [0.45] * 23
    sp = [0.01] * 6 + [0.05] * 24
    books = to_books(_rows(mids, sp))
    r = simulate(books['e'])
    assert r['n_trig'] == 0 and r['missed'] >= 1


def test_flat_no_events():
    books = to_books(_rows([0.5] * 30))
    r = simulate(books['e'])
    assert r['formed'] == 0 and r['n_trig'] == 0


def test_bad_rows_skipped():
    assert to_books([('junk', 'e', 0.5, 0.51),
                     ('2026-10-05T00:00:00+00:00', 'e', 0.6, 0.5)]) == {}
