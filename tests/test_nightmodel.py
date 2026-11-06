"""Item-78 night model tests (synthetic only, no network)."""
from research.nightmodel import project, call_state


def test_project_math():
    p = project(500, 400, 100, 0.0, 0.2, 1100)
    assert p == {'margin': round(100 / 1100, 4), 'uncertainty': round(0.2 * 100 / 1100, 4)}
    assert project(500, 400, 2000, 0.0, 0.2, 1100) is None
    assert project('x', 1, 1, 0, 0.1, 10) is None


def test_call_states():
    assert call_state({'margin': 0.05, 'uncertainty': 0.01}, 0.03) == 'call-D'
    assert call_state({'margin': 0.05, 'uncertainty': 0.01}, 0.30) == 'too-early'
    assert call_state({'margin': 0.005, 'uncertainty': 0.01}, 0.03) == 'too-early'
    assert call_state({'margin': -0.05, 'uncertainty': 0.01}, 0.03) == 'call-R'
    assert call_state(None, 0.01) == 'too-early'
