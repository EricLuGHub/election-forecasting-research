"""Item-108 conserved allocation tests (synthetic only, no network)."""
from research.allocate import allocate


def lots(q):
    return [(q, '2026-10-04T00:00:00+00:00')]


def test_two_entries_share_lots_once():
    # 1000 shares/leg, two x1000 entries same race: first gets 1000, second 0
    entries = [('a', 'R', 'D', 1000, 't1'), ('b', 'R', 'D', 1000, 't2')]
    out, res = allocate(entries, {'R': lots(1000), 'D': lots(1000)})
    assert out == {'a': 1000, 'b': 0}
    assert sum(out.values()) <= 1000  # never exceeds owned


def test_reducer_sale_reduces_both():
    entries = [('a', 'R', 'D', 1000, 't1')]
    out, res = allocate(entries, {'R': lots(600), 'D': lots(600)},
                        exits=[('R', 100, 't0'), ('D', 100, 't0')])
    assert out == {'a': 500}


def test_e8_exit_consumes_attributed():
    entries = [('idgov', '860', '859', 675, 't1')]
    lots = {'860': [(675, 't0')], '859': [(675, 't0')]}
    out, res = allocate(entries, lots, exits=[('860', 316, 't2'), ('859', 316, 't2')])
    assert out == {'idgov': 359}
    assert res['_residue'] == {'860': 0, '859': 0}


def test_unattributed_residue_flagged():
    out, res = allocate([], {'R': lots(250)})
    assert out == {} and res == {'_residue': {'R': 250.0}}
