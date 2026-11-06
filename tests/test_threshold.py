"""Item-33 threshold study tests."""
from research.threshold import evaluate


def test_monotone_capture():
    low = evaluate(5.0)
    high = evaluate(25.0)
    assert low['fired_n'] >= high['fired_n']
    assert low['captured'] >= high['captured']
    assert low['refused_value'] <= high['refused_value']


def test_fifteen_splits_history():
    mid = evaluate(15.0)
    assert mid['fired_n'] == 18
    assert mid['captured'] == 444.21
    assert mid['refused_n'] == 6
    assert abs(mid['refused_value'] - 68.74) < 0.01
    assert mid['avg_edge'] > mid['refused_avg']
    assert mid['roc'] > mid['refused_roc']
