"""Item-86 fill-conditional tests (synthetic only, no network)."""
import pytest
from research.fillcond import window_move, fill_moves, summarize


def _series(mids, t0=1_000_000, step=600):
    return [(t0 + i * step, m) for i, m in enumerate(mids)]


def test_window_moves():
    s = _series([0.50, 0.52, 0.55, 0.53])
    assert window_move(s, 1_000_000, 0.5, 1) == pytest.approx(0.03)
    assert window_move(s, 1_000_000 + 1800, 0.5, -1) == pytest.approx(0.03)
    assert window_move(s, 1_000_000, 5.0, 1) is None  # no cover


def test_fill_moves_and_summary():
    s = _series([0.50] * 6 + [0.55] * 6)
    out = fill_moves({'e': s}, [('e', 1_000_000 + 3600, 'buy')])
    assert len(out['e']) == 1
    pre, post, side = out['e'][0]
    assert pre == pytest.approx(0.05) and post == pytest.approx(0.0)
    summ = summarize(out['e'])
    assert summ['pre']['n'] == 1 and summ['post']['mean'] == 0.0


def test_empty_refuses():
    assert summarize([]) is None
    assert fill_moves({}, [('e', 1_000_000, 'buy')]) == {}
