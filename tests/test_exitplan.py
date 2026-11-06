"""Item-37 paired-exit planner tests (synthetic only, no network)."""
from research.exitplan import plan_exit, PREFIX


def test_paired_plan():
    legs, d = plan_exit('lasen', '958', '957', 100, 0.06, 0.935, 90.0,
                        999.0, 900.0, set(), set())
    assert legs is not None and d['edge'] == 9.5
    assert d['key'] == PREFIX + 'lasen' and d['mode'] == 'paired-only'


def test_edge_bar_refuses():
    assert plan_exit('x', '1', '2', 100, 0.06, 0.93, 95.0,
                     1000.0, 900.0, set(), set())[0] is None


def test_floor_violation_refuses():
    # proceeds 99.5 but floor drops 200 with only 99.5 cash back
    assert plan_exit('x', '1', '2', 100, 0.06, 0.935, 90.0,
                     1000.0, 800.0, set(), set())[0] is None


def test_foreign_orders_and_refire_refuse():
    ok, _ = plan_exit('x', '1', '2', 100, 0.06, 0.935, 90.0,
                      999.0, 900.0, set(), set())
    assert ok is not None
    assert plan_exit('x', '1', '2', 100, 0.06, 0.935, 90.0,
                     1000.0, 900.0, {'1'}, set())[0] is None
    assert plan_exit('x', '1', '2', 100, 0.06, 0.935, 90.0,
                     1000.0, 900.0, set(), {'E8X-x'})[0] is None


def test_bad_inputs_refuse():
    assert plan_exit('x', '1', '2', 0, 0.06, 0.935, 90.0,
                     1000.0, 900.0, set(), set())[0] is None
    assert plan_exit('x', '1', '2', 100, None, 0.935, 90.0,
                     1000.0, 900.0, set(), set())[0] is None
