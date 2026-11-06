"""Shared account-wide rate limiter (backlog item 21).

Venue quota is per ACCOUNT (100 reads / 30 writes per minute for ordinary
accounts), but Client.last_request throttles per process. Under contention
(monitor + quoter + E6 + crons) the account 429s and everyone retries blind.

Design: two file-locked token buckets (reads, writes) shared by all local
processes, keyed by consumer tag (invocation). take() blocks briefly for a
token instead of spending quota into a 429; record_429() logs venue
throttles by consumer for pressure analysis. Additive by design: under normal
load the bucket is full and request timing is unchanged; the limiter only
engages where a 429 would otherwise occur. MIDTERM_NO_LIMIT=1 disables both
buckets (recording continues).
"""
import fcntl
import json
import os
import sys
import time
from pathlib import Path

from .client import ROOT

STATE = ROOT / 'data/ratelimit.json'
READ_RATE = 100.0 / 60.0
WRITE_RATE = 30.0 / 60.0
CAPACITY = (100.0, 30.0)


def _now():
    return time.monotonic()


def consumer_tag(argv=None):
    parts = list(argv if argv is not None else sys.argv[1:])
    return (' '.join(parts[:2]) or 'unknown')[:80]


def _load(path=None, now=None):
    path = Path(path or STATE)
    try:
        state = json.loads(path.read_text())
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    stamp = now if now is not None else _now()
    return {'reads': {'tokens': CAPACITY[0], 'at': stamp},
            'writes': {'tokens': CAPACITY[1], 'at': stamp},
            'consumers': {}}


def _save(path, state):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state))
        os.replace(tmp, path)
    except OSError:
        pass


def take(kind, consumer, tokens=1.0, timeout=5.0, path=None, clock=None):
    """Take tokens from the shared bucket. Returns (allowed, waited_s).

    Waits up to timeout for refill, then gives up and returns (False, waited)
    so a stuck lockfile can never deadlock trading; the caller proceeds and
    the venue's own 429/backoff remains the backstop.
    """
    now = clock() if clock else _now()
    if os.environ.get('MIDTERM_NO_LIMIT') == '1':
        return True, 0.0
    rate, cap = (READ_RATE, CAPACITY[0]) if kind == 'read' else \
        (WRITE_RATE, CAPACITY[1])
    path = Path(path or STATE)
    deadline = now + timeout
    waited = 0.0
    while True:
        cur = clock() if clock else _now()
        try:
            with path.open('a+') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    state = _load(path, cur)
                    bucket = state.setdefault(kind + 's', {'tokens': cap, 'at': cur})
                    bucket['tokens'] = min(cap, bucket['tokens'] + (cur - bucket['at']) * rate)
                    bucket['at'] = cur
                    if bucket['tokens'] >= tokens:
                        bucket['tokens'] -= tokens
                        cons = state.setdefault('consumers', {}).setdefault(consumer, {})
                        cons['takes'] = cons.get('takes', 0) + 1
                        cons['waited_ms'] = round(cons.get('waited_ms', 0.0) + waited * 1000.0, 1)
                        _save(path, state)
                        return True, waited
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        except (OSError, ValueError):
            return True, waited  # lock contention: proceed, venue backstops
        if cur >= deadline:
            return False, waited
        time.sleep(0.05)
        waited = (clock() if clock else _now()) - now


def record_429(consumer, path=None):
    try:
        path = Path(path or STATE)
        with path.open('a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                state = _load(path)
                cons = state.setdefault('consumers', {}).setdefault(consumer, {})
                cons['throttles'] = cons.get('throttles', 0) + 1
                _save(path, state)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
