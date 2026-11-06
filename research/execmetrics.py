"""Timestamped execution metrics (backlog item 5). Pure parsers as code.

`ops/review.sh` counted whole-log SUBMIT/CANCEL lines behind `_1h` keys, so
every 10-minute digest repeated the same totals (515/365) regardless of actual
activity. This module parses ISO timestamps and reports trailing 1h/24h
windows plus totals. Exact-duplicate log lines (double-written by redirect)
are collapsed so activity is not double-counted.

Fill-lifecycle limitation (recorded, not hidden): e1run.log holds no FILL
lines and journal responses are submit-time snapshots (quantityTraded at
submit), so "matched shares / turnover" below are submit-snapshot figures,
not lifecycle fills. True partial/full-fill accounting needs the fills tape
(follow-up work, not claimed here).
"""
import json
import re
from datetime import datetime, timedelta

WINDOWS = {'1h': timedelta(hours=1), '24h': timedelta(hours=24)}

TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?')


def parse_ts(ts):
    """ISO timestamp -> aware datetime, or None when unparseable."""
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt


def parse_log_lines(lines):
    """Log lines -> event dicts. Dedupes exact-duplicate lines; skips junk.

    Event: {'at': datetime, 'kind': 'submit'|'cancel'|'cancel_fail',
            'accepted': bool (submits only)}.
    Accepted = SUBMIT line whose `-> {...}` response carries an orderId.
    Timestamps are found by regex so bell/control-char prefixes (the
    beep-on-fill `\a` bytes that land in redirected logs) do not silently
    drop events. The event token is the first word after the timestamp.
    """
    events = []
    seen = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        m = TS_RE.search(line)
        if not m:
            continue
        at = parse_ts(m.group(0))
        if at is None:
            continue
        rest = line[m.end():].split(None, 2)
        if not rest:
            continue
        tok = rest[0]
        if tok == 'SUBMIT':
            # Response JSON is often truncated by log line-width limits, so
            # extract orderId by regex instead of parsing the full object.
            accepted = bool(re.search(r'"orderId"\s*:\s*\d+',
                                      line.split('->', 1)[1])
                            if '->' in line else False)
            events.append({'at': at, 'kind': 'submit', 'accepted': accepted})
        elif tok == 'CANCEL':
            events.append({'at': at, 'kind': 'cancel'})
        elif tok == 'CANCEL-FAIL':
            events.append({'at': at, 'kind': 'cancel_fail'})
    return events


def windowed_log(events, now):
    """Trailing-window submit/accept/cancel counts plus whole-log totals."""
    out = {}
    for name, delta in WINDOWS.items():
        cutoff = now - delta
        win = [e for e in events if e['at'] >= cutoff]
        out[name] = {
            'submits': sum(1 for e in win if e['kind'] == 'submit'),
            'accepted': sum(1 for e in win
                            if e['kind'] == 'submit' and e['accepted']),
            'cancels': sum(1 for e in win if e['kind'] == 'cancel'),
            'cancel_fails': sum(1 for e in win if e['kind'] == 'cancel_fail'),
        }
    out['total'] = {
        'submits': sum(1 for e in events if e['kind'] == 'submit'),
        'cancels': sum(1 for e in events if e['kind'] == 'cancel'),
    }
    return out


def parse_journal(obj, prefix='E1R-'):
    """Journal dict -> submit-snapshot fills for one idempotency prefix.

    Entry: {'at': datetime, 'shares': abs(quantityTraded),
            'turnover': abs(totalCost)}. Entries missing timestamps are
    dropped (they cannot sit in a window — counted nowhere, said plainly).
    """
    rows = []
    dropped = 0
    items = obj.items() if isinstance(obj, dict) else []
    for key, val in items:
        if prefix and not str(key).startswith(prefix):
            continue
        if not isinstance(val, dict):
            dropped += 1
            continue
        at = parse_ts(val.get('at'))
        if at is None:
            dropped += 1
            continue
        resp = val.get('response') or {}
        try:
            shares = abs(resp.get('quantityTraded') or 0)
            turnover = abs(resp.get('totalCost') or 0)
        except TypeError:
            dropped += 1
            continue
        rows.append({'at': at, 'shares': shares, 'turnover': turnover})
    return rows, dropped


def windowed_fills(rows, now):
    """Trailing-window matched-share/turnover snapshots plus totals."""
    out = {}
    for name, delta in WINDOWS.items():
        cutoff = now - delta
        win = [r for r in rows if r['at'] >= cutoff]
        out[name] = {
            'entries': len(win),
            'matched_shares': sum(r['shares'] for r in win),
            'turnover': round(sum(r['turnover'] for r in win), 2),
        }
    out['total'] = {
        'entries': len(rows),
        'matched_shares': sum(r['shares'] for r in rows),
        'turnover': round(sum(r['turnover'] for r in rows), 2),
    }
    return out


def log_freshness(events, now):
    """Newest event time + age in hours, or {'events': 0} when empty."""
    if not events:
        return {'events': 0, 'last_at': None, 'age_h': None}
    last = max(e['at'] for e in events)
    return {'events': len(events), 'last_at': last.isoformat(),
            'age_h': round((now - last).total_seconds() / 3600, 1)}
