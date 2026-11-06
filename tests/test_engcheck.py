"""Item-20 self-check tests (synthetic evidence)."""
from research.engcheck import check


def _reg():
    return {'engines': [
        {'id': 'E1', 'status': 'LIVE ACTIVE',
         'expect_process': [['research.e1run', 'e1run']],
         'expect_fresh_logs': [['exit.log', 60]]},
        {'id': 'V4', 'status': 'PARKED sees detector only',
         'expect_process': [], 'forbid_process': False},
    ]}


def test_process_and_log_drift():
    ev = {'processes': ['python3 -m research.monitor run'],
          'logs': {'exit.log': 120.0}}
    drift = check(ev, _reg())
    kinds = {(d['engine'], d['kind']) for d in drift}
    assert ('E1', 'process_missing') in kinds
    assert ('E1', 'log_stale') in kinds


def test_alloc_mismatch():
    ev = {'processes': [], 'logs': {},
          'alloc': {'E1': {'lot': 600}},
          'alloc_checks': [('E1', 'E1.lot', 25)]}
    drift = check(ev, _reg())
    assert any(d['kind'] == 'alloc_mismatch' and d['observed'] == 25
               for d in drift)


def test_clean():
    ev = {'processes': ['python3 -m research.e1run --live'],
          'logs': {'exit.log': 5.0}, 'alloc': {},
          'alloc_checks': []}
    assert check(ev, _reg()) == []
