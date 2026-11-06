"""Item-34 retrigger tests (synthetic only, no network)."""
from research.retrigger import top, joint_top_cost, should_recheck, catalog_diff


def _snap(eids=('1', '2'), pr=(0.52, 1000), pd=(0.52, 1000)):
    return {'eids': eids, 'top_r': pr, 'top_d': pd}


def test_quiet_book_stays_quiet():
    fire, reasons = should_recheck('b', _snap(), _snap())
    assert fire is False and reasons == []


def test_price_move_fires():
    fire, reasons = should_recheck('b', _snap(),
                                  _snap(pd=(0.54, 1000)))
    assert fire is True and any('joint cost' in r for r in reasons)


def test_sub_cent_move_ignored():
    fire, _ = should_recheck('b', _snap(), _snap(pd=(0.5205, 1000)))
    assert fire is False  # 0.0005 < 1c bar


def test_depth_shift_fires():
    fire, reasons = should_recheck('b', _snap(),
                                  _snap(pr=(0.52, 2500)))
    assert fire is True and any('depth' in r for r in reasons)


def test_moderate_depth_flicker_ignored():
    # c191: 25-90% top-size flicker on seed ladders carries no price move.
    fire, _ = should_recheck('b', _snap(), _snap(pr=(0.52, 500)))
    assert fire is False


def test_missing_book_never_fires():
    fire, reasons = should_recheck('b', _snap(),
                                  {'eids': ('1', '2'),
                                   'top_r': (None, 0),
                                   'top_d': (0.52, 1000)})
    assert fire is False and reasons == ['missing top_r book']


def test_relist_fires():
    fire, reasons = should_recheck('b', _snap(), _snap(eids=('1', '9')))
    assert fire is True and any('relist' in r for r in reasons)


def test_top_and_joint_helpers():
    assert top({'bids': [{'price': '0.52', 'quantity': '7'}]}) == (0.52, 7.0)
    assert top({}) == (None, 0)
    assert joint_top_cost((0.52, 1), (0.52, 1)) == 0.96
    assert joint_top_cost((None, 0), (0.52, 1)) is None


def test_catalog_diff_strict():
    mkts = [{'title': 'Iowa Senate Republican', 'exchanges': [{'id': 5}]},
            {'title': 'Iowa Senate Democratic', 'exchanges': [{'id': 6}]},
            {'title': 'Iowa Dogcatcher Whippet', 'exchanges': [{'id': 7}]},
            {'title': 'US Senate Control', 'exchanges': [{'id': 8}]}]
    assert catalog_diff({'5'}, mkts, {'Iowa'}) == ['6']
