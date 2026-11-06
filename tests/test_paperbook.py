"""Item-17 paper lifecycle tests (synthetic books, no network)."""
from research.paperbook import fill_buy, fill_sell, PaperBook


def _book():
    return {'bids': [(0.10, 100), (0.09, 200)],
            'asks': [(0.12, 100), (0.13, 200)]}


def test_pessimistic_needs_trade_through():
    # buy @0.11: no ask <= 0.11 -> nothing (joining earns zero)
    assert fill_buy(_book(), 0.11, 50, 'pessimistic') == (0.0, 0.0)
    # buy @0.12: lifts 100 @0.12 only (partial)
    assert fill_buy(_book(), 0.12, 150, 'pessimistic') == (100.0, 12.0)
    # sell @0.11: no bid >= 0.11... bids 0.10 -> nothing
    assert fill_sell(_book(), 0.11, 50, 'pessimistic') == (0.0, 0.0)
    # sell @0.10: hits 100 @0.10
    assert fill_sell(_book(), 0.10, 150, 'pessimistic') == (100.0, 10.0)


def test_optimistic_touch_overstates_by_design():
    filled, out = fill_buy(_book(), 0.10, 150, 'optimistic')
    assert filled == 150.0 and out == 15.0  # touch earns perfect priority


def test_optimistic_below_touch_impossible():
    # buy BELOW best bid / sell ABOVE best ask: nothing, both bounds
    assert fill_buy(_book(), 0.09, 150, 'optimistic') == (0.0, 0.0)
    assert fill_buy(_book(), 0.09, 150, 'pessimistic') == (0.0, 0.0)
    assert fill_sell(_book(), 0.13, 150, 'optimistic') == (0.0, 0.0)
    assert fill_sell(_book(), 0.13, 150, 'pessimistic') == (0.0, 0.0)


def test_no_retrofill_across_snapshots():
    pb = PaperBook('optimistic')
    assert pb.quote(_book(), 'buy', 0.09, 150) == 0.0  # below touch: nothing
    assert pb.fills == 0 and pb.inventory == 0.0
    assert 'assumptions' in pb.state()


def test_book_tracks_partials_exits_cash():
    pb = PaperBook('pessimistic')
    assert pb.quote(_book(), 'buy', 0.12, 150) == 100.0
    assert pb.partials == 1 and pb.inventory == 100.0 and pb.cash == -12.0
    delta = pb.exit_all(_book())  # sell 100 into bids: 100 @0.10
    assert abs(delta - 10.0) < 1e-9 and pb.inventory == 0.0
    assert abs(pb.pnl() - (-2.0)) < 1e-9  # paid spread 2c/share, honestly


def test_residual_inventory_retained():
    pb = PaperBook('pessimistic', cash=1000.0)
    pb.inventory = 100.0  # thin book: only 20 bids @0.10
    thin = {'bids': [(0.10, 20)], 'asks': [(0.12, 5)]}
    delta = pb.exit_all(thin, mark=0.10)
    assert delta == 2.0 and pb.inventory == 80.0  # retains 80 shares
    assert pb.unfilled_value == 8.0  # missing liquidation recorded
    assert pb.pnl() == 2.0  # funding 1000 excluded from P&L


def test_funded_no_trade_zero_profit():
    pb = PaperBook('pessimistic', cash=1000.0)
    assert pb.pnl() == 0.0  # funding is not earnings
    assert pb.exit_all(_book()) == 0.0
