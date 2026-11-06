"""Feed-triggered, read-only reconciliation; REST remains authoritative."""
from datetime import datetime, timezone
import logging
import signal
import time

from .monitor import Monitor, utc
from .realtime import FeedBridge


class RealtimeMonitor(Monitor):
    def publish(self, **fields):
        bridge = getattr(self, 'bridge', None)
        if bridge:
            feed = bridge.inbox.summary()
            fields['feed'] = feed
            # Never display old confirmations as actionable during feed recovery.
            values = fields.get('confirmedCandidates', self.status.get('confirmedCandidates', []))
            if not feed['synchronized'] or feed['pendingExchanges']:
                values = []
            now = datetime.now(timezone.utc)
            fields['confirmedCandidates'] = [c for c in values if
                (now-datetime.fromisoformat(c['bookReadStartedAt'])).total_seconds() <= self.args.max_quote_age]
        super().publish(**fields)

    def run(self):
        stop_file = self.directory / 'stop.request'
        stop_file.unlink(missing_ok=True)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.halt.set())
        self.bridge = None
        self.publish(transport='realtime', feed=None)
        next_full = last_prune = retry_at = 0.
        failures = 0
        try:
            # Resolve only the tournament here; catalog/depth are reconciled below.
            self.tournament = self.client.get(f'/tournaments/{self.args.slug}')
            self.bridge = FeedBridge(self.tournament['id'])
            inbox = self.bridge.inbox
            while not self.halt.is_set() and not stop_file.exists():
                now = time.monotonic()
                self.bridge.check_health()
                if now >= retry_at and (now >= next_full or inbox.wake.is_set()):
                    # Fixed, bounded coalescing window, not a trailing debounce.
                    self.halt.wait(.05)
                    ticket = inbox.take(periodic=now >= next_full)
                    known = {str(e['id']) for m in self.markets for e in m['exchanges']}
                    if ticket['dirty'] - known or ticket['catalogDirty']:
                        ticket['full'] = True
                        self.catalog_at = 0.
                    if ticket['full'] or ticket['dirty']:
                        started = time.monotonic()
                        try:
                            guard = lambda ids: inbox.summary()['connected'] and inbox.valid(ticket, ids)
                            success = self.cycle(None if ticket['full'] else ticket['dirty'], guard=guard)
                            inbox.reconcile(ticket, success)
                            self.publish(confirmedCandidates=[s['candidate'] for s in self.history.states.values()
                                         if s['state'] == 'confirmed' and guard([l['exchangeId'] for l in s['candidate']['legs']])])
                            failures = 0 if success else failures + 1
                        except (RuntimeError, OSError, ValueError, KeyError) as exc:
                            failures += 1
                            inbox.reconcile(ticket, False)
                            logging.error('Realtime scan failed: %s', exc)
                            self.publish(phase='error', errors=[{'error': str(exc)}], confirmedCandidates=[])
                        if ticket['full']:
                            next_full = max(started+self.args.interval, time.monotonic()+.2)
                        retry_at = time.monotonic() + (min(30, 2 ** min(failures, 5)) if failures else .1)
                        self.publish(eventToScanCompleteMs=round((time.monotonic()-ticket['pendingSince'])*1000, 1)
                                     if ticket['pendingSince'] else None)
                        if self.args.cycles and self.cycles >= self.args.cycles:
                            break
                if time.monotonic()-last_prune > 3600:
                    self.history.prune(self.args.retention_days)
                    last_prune = time.monotonic()
                self.publish()
                # Event wakeups don't wait for the next periodic sweep.
                delay = min(1, max(.01, next_full-time.monotonic()))
                if time.monotonic() < retry_at:
                    self.halt.wait(min(1, retry_at-time.monotonic()))
                else:
                    inbox.wake.wait(delay)
        finally:
            if self.bridge:
                self.bridge.close()
            self.publish(phase='stopped', stoppedAt=utc(), confirmedCandidates=[])
            self.history.db.close()
