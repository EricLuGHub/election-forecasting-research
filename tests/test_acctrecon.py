"""Item-2 identity tests (pure logic)."""
from research.acctrecon import check_identity


def test_balanced():
    snap = {'total_value': 100500.0, 'cash': 90000.0, 'holdings_value': 10500.0,
            'total_pnl': 500.0, 'realized_fifo': 600.0, 'unrealized': -100.0,
            'tx_cash_sum': -10000.0, 'starting_balance': 100000.0}
    out = check_identity(snap)
    assert out['residuals'] == {}


def test_residuals_surfaced():
    snap = {'total_value': 100500.0, 'cash': 90000.0, 'holdings_value': 10400.0,
            'total_pnl': 500.0, 'realized_fifo': 600.0, 'unrealized': -100.0,
            'tx_cash_sum': -9000.0, 'starting_balance': 100000.0}
    out = check_identity(snap)
    assert out['residuals']['A_cash_plus_holdings'] == 100.0
    assert out['residuals']['C_transactions_vs_cash'] == -1000.0
    assert 'B_realized_plus_unrealized' not in out['residuals']
