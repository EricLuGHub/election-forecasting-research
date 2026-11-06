"""Shared timestamped market-data cache (backlog item 22).

Every loop (monitor, quoter, E6, dashboards, research) refetches the same
catalog and bulk quotes on its own schedule. One file-backed cache with
per-key TTLs replaces N redundant fetches: first reader populates, the rest
hit. Entries carry fetched-at timestamps; stale reads are explicit
(fresh/stale flag), never silent. Hit/miss/stale counters per key prove the
saving; freshness-critical paths (exit decisions, fire verification) bypass
with ttl=0.
"""
import fcntl
import json
import os
import time
from pathlib import Path

from .client import ROOT

CACHE = ROOT / 'data/mdcache.json'


def _now():
    return time.time()


def _load(path=None):
    path = Path(path or CACHE)
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {'keys': {}, 'stats': {}}


def _save(path, data):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)
    except OSError:
        pass


def get_or_fetch(key, ttl, fetcher, path=None, now=None):
    """(value, fresh_bool, hit_bool). Fetch errors propagate (fail loud);
    no stale fallback: a failed refresh never returns old data silently."""
    now = _now() if now is None else now
    path = Path(path or CACHE)
    try:
        with path.open('a+') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX)
                data = _load(path)
                entry = data.get('keys', {}).get(key)
                stats = data.setdefault('stats', {}).setdefault(key, {})
                if entry and now - entry['at'] <= ttl:
                    stats['hits'] = stats.get('hits', 0) + 1
                    _save(path, data)
                    return entry['value'], True, True
                value = fetcher()
                data.setdefault('keys', {})[key] = {'value': value, 'at': now}
                stats['misses'] = stats.get('misses', 0) + 1
                _save(path, data)
                return value, True, False
            finally:
                try:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                except OSError:
                    pass
    except OSError:
        return fetcher(), True, False


def stats(path=None):
    return _load(path).get('stats', {})
