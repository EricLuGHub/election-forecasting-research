"""Item-21 limiter tests (fake clock + tmp paths, no network)."""
import os
from research.ratelimit import take, record_429, consumer_tag, _load


def test_bucket_refills_and_caps(tmp_path):
    path = str(tmp_path / 'rl.json')
    clock = [0.0]
    ok, waited = take('read', 't', tokens=100.0, path=path,
                      clock=lambda: clock[0])
    assert ok and waited == 0.0
    # bucket empty: immediate take fails after timeout, never deadlocks
    ok2, _ = take('read', 't', tokens=1.0, timeout=0.0, path=path,
                  clock=lambda: clock[0])
    assert ok2 is False
    # 60s later: full refill, capped (not overfilled)
    clock[0] = 61.0
    ok3, _ = take('read', 't', tokens=100.0, path=path, clock=lambda: clock[0])
    assert ok3 is True
    assert _load(path)['reads']['tokens'] == 0.0


def test_kill_switch(tmp_path, monkeypatch):
    path = str(tmp_path / 'rl.json')
    monkeypatch.setenv('MIDTERM_NO_LIMIT', '1')
    ok, waited = take('write', 't', tokens=1000.0, path=path)
    assert ok and waited == 0.0


def test_429_recording(tmp_path):
    path = str(tmp_path / 'rl.json')
    record_429('quoter', path)
    record_429('quoter', path)
    state = _load(path)
    assert state['consumers']['quoter']['throttles'] == 2


def test_consumer_tag():
    assert consumer_tag(['research.quoter', '--max-markets', '3']) == 'research.quoter --max-markets'
    assert consumer_tag([]) == 'unknown'
