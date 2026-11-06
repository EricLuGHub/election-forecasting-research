"""Item-12 reconciliation tests (pure logic, no network)."""
from research.reconcile import leg_inventory, reconcile, load_baskets_from


def test_leg_inventory():
    positions = [{'exchangeId': '1071', 'quantity': -2000,
                  'lots': [{'side': 'NO', 'quantity': 1500},
                           {'side': 'NO', 'quantity': 500},
                           {'side': 'YES', 'quantity': 200}]}]
    no_sum, net = leg_inventory(positions, '1071')
    assert no_sum == 2000
    assert net == -2000
    assert leg_inventory(positions, '9999') == (0.0, None)


def test_reconcile_statuses():
    ledger = {
        'full': {'race': 'X Senate R/D NO x100', 'cost': 90.0, 'floor': 100.0},
        'part': {'race': 'Y Senate R/D NO x100', 'cost': 90.0, 'floor': 100.0},
        'gone': {'race': 'Z Senate R/D NO x100', 'cost': 90.0, 'floor': 100.0},
        'myst': {'race': 'Q Senate R/D NO x100', 'cost': 90.0, 'floor': 100.0},
        'short': {'race': 'W Senate YES short x500', 'proceeds': 70.0},
    }
    positions = [
        {'exchangeId': 'R1', 'quantity': 100,
         'lots': [{'side': 'NO', 'quantity': 100}]},
        {'exchangeId': 'D1', 'quantity': 100,
         'lots': [{'side': 'NO', 'quantity': 100}]},
        {'exchangeId': 'R2', 'quantity': 60,
         'lots': [{'side': 'NO', 'quantity': 60}]},
        {'exchangeId': 'D2', 'quantity': 100,
         'lots': [{'side': 'NO', 'quantity': 100}]},
    ]
    mapping = {'X Senate R/D NO x100': ('R1', 'D1'),
               'Y Senate R/D NO x100': ('R2', 'D2'),
               'Z Senate R/D NO x100': ('R9', 'D9')}
    rows = reconcile(ledger, positions, lambda race: mapping.get(race))
    by_name = {r['basket']: r for r in rows}
    assert by_name['full']['status'] == 'intact'
    assert by_name['part']['status'] == 'partial'
    assert by_name['part']['paired'] == 60
    assert by_name['gone']['status'] == 'depleted'
    assert by_name['myst']['status'] == 'unresolved'
    assert 'short' not in by_name  # proceeds-only entries skipped
    assert by_name['full']['net_mismatch'] is False


def test_net_mismatch_flagged():
    ledger = {'a': {'race': 'X Senate R/D NO x100', 'cost': 90.0, 'floor': 100.0}}
    positions = [{'exchangeId': 'R1', 'quantity': -40,
                  'lots': [{'side': 'NO', 'quantity': 100}]}]
    rows = reconcile(ledger, positions, lambda race: ('R1', 'D1'))
    assert rows[0]['net_mismatch'] is True
    assert rows[0]['status'] == 'depleted'  # D1 has zero NO lots
