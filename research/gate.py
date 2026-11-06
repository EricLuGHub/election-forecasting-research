"""Competition start/end gate. Status is authoritative; dates are the backup.

Live order paths must call check() first: it requires tournament status 'open'
AND now within [startDate, endDate] (with a small clock-skew allowance), and
caches the tournament document for 60s instead of refetching per order.
Read-only research (snapshot/monitor/shadow) never calls this.
"""
import time
from datetime import datetime, timezone

SKEW_SECONDS = 300
CACHE_TTL = 60.0


class GateClosed(RuntimeError):
    pass


class Gate:
    def __init__(self, client, slug='midterm-elections'):
        self.client = client
        self.slug = slug
        self.cached = None
        self.cached_at = 0.0

    def tournament(self):
        if time.monotonic() - self.cached_at > CACHE_TTL or not self.cached:
            self.cached = self.client.get(f'/tournaments/{self.slug}')
            self.cached_at = time.monotonic()
        return self.cached

    def check(self, now=None):
        t = self.tournament()
        now = now or datetime.now(timezone.utc)
        if t.get('status') not in ('open', 'active'):
            raise GateClosed(f"Tournament status is {t.get('status')!r}; orders blocked")
        start = datetime.fromisoformat(t['startDate'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(t['endDate'].replace('Z', '+00:00'))
        if (now - start).total_seconds() < -SKEW_SECONDS:
            raise GateClosed(f'Competition starts {start.isoformat()}; orders blocked')
        if (now - end).total_seconds() > SKEW_SECONDS:
            raise GateClosed(f'Competition ended {end.isoformat()}; orders blocked')
        return t
