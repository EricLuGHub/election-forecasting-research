"""Bounded event coalescing and supervision for the official Supabase SDK bridge."""
from collections import deque
from datetime import datetime, timezone
import json
import shutil
import subprocess
import threading
import time

from .client import ROOT


class FeedInbox:
    def __init__(self, tournament_id):
        self.tournament_id = tournament_id
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.connected = False
        self.epoch = 0
        self.reconciled_epoch = -1
        self.need_full = True
        self.dirty = set()
        self.versions = {}
        self.revisions = {}
        self.seen = {}
        self.messages = self.gaps = self.duplicates = 0
        self.last_message = None
        self.last_bridge = time.monotonic()
        self.disconnected_since = self.last_bridge
        self.last_heartbeat = None
        self.heartbeat_latency = None
        self.reason = 'startup'
        self.first_pending = None
        self.catalog_dirty = False

    def reset(self, reason, disconnect=False):
        with self.lock:
            self.epoch += 1
            self.need_full = True
            self.reason = reason
            if disconnect:
                if self.connected or self.disconnected_since is None:
                    self.disconnected_since = time.monotonic()
                self.connected = False
                self.revisions.clear()
                self.seen.clear()
            self.first_pending = self.first_pending or time.monotonic()
            self.wake.set()

    def accept(self, message):
        with self.lock:
            self.last_bridge = time.monotonic()
            kind = message.get('kind')
            if kind == 'reset':
                self.reset(message.get('reason', 'reset'), disconnect=True)
                return
            if kind == 'ready':
                self.connected = True
                self.disconnected_since = None
                self.reset('subscription_ready')
                return
            if kind == 'health':
                if not message.get('connected') and self.connected:
                    self.reset('transport_disconnected', disconnect=True)
                return
            if kind == 'heartbeat':
                if message.get('status') == 'ok':
                    self.last_heartbeat = datetime.now(timezone.utc).isoformat()
                    self.heartbeat_latency = message.get('latencyMs')
                elif message.get('status') in ('timeout', 'error', 'disconnected'):
                    self.reset('heartbeat_failed', disconnect=True)
                return
            if kind == 'subscription':
                if message.get('status') != 'SUBSCRIBED':
                    self.reset('subscription_' + str(message.get('status')), disconnect=True)
                return
            if kind != 'batch':
                return
            topic, event, payload = message['topic'], message['event'], message['payload']
            self.messages += 1
            self.last_message = datetime.now(timezone.utc).isoformat()
            if event in ('market_batch', 'account_batch'):
                delivery = payload.get('delivery') or {}
                revision, previous = delivery.get('revision'), delivery.get('previousRevision')
                if revision is None:
                    self.reset('missing_revision')
                else:
                    seen = self.seen.setdefault(topic, deque(maxlen=128))
                    if revision in seen:
                        self.duplicates += 1
                        return
                    if topic not in self.revisions:
                        self.reset('first_topic_revision')
                    elif previous != self.revisions[topic]:
                        self.gaps += 1
                        self.reset('revision_gap')
                    self.revisions[topic] = revision
                    seen.append(revision)
            changes = []
            for name in ('trades', 'bookDirty', 'fills', 'orderUpdates', 'settlements', 'refunds', 'observedPrices'):
                changes.extend(payload.get(name) or [])
            for item in changes:
                scope = item.get('tournamentId', payload.get('tournamentId'))
                if scope is not None and scope != self.tournament_id:
                    continue
                eid = item.get('exchangeId')
                if eid is not None:
                    eid = str(eid)
                    self.dirty.add(eid)
                    self.versions[eid] = self.versions.get(eid, 0) + 1
            settlements = [x for x in payload.get('marketSettled', []) if x.get('tournamentId') in (None, self.tournament_id)]
            if settlements:
                self.catalog_dirty = True
                self.reset('market_settled')
            if event == 'violation' and not changes:
                self.reset('relationship_violation')
            if len(self.dirty) > 5000 or len(self.versions) > 10000:
                self.dirty.clear()
                self.versions.clear()
                self.reset('event_capacity')
            if self.dirty or self.need_full:
                self.first_pending = self.first_pending or time.monotonic()
                self.wake.set()

    def take(self, periodic=False):
        with self.lock:
            ticket = {'epoch': self.epoch, 'versions': dict(self.versions), 'dirty': set(self.dirty),
                      'full': periodic or self.need_full, 'catalogDirty': self.catalog_dirty,
                      'pendingSince': self.first_pending}
            self.need_full = False
            self.catalog_dirty = False
            self.dirty.clear()
            self.first_pending = None
            self.wake.clear()
            return ticket

    def reconcile(self, ticket, success):
        with self.lock:
            if success and ticket['full'] and ticket['epoch'] == self.epoch:
                self.reconciled_epoch = self.epoch
            elif not success:
                self.reconciled_epoch = -1
                self.need_full = True
                self.wake.set()

    def valid(self, ticket, exchange_ids):
        with self.lock:
            return ticket['epoch'] == self.epoch and all(
                self.versions.get(str(eid), 0) == ticket['versions'].get(str(eid), 0) for eid in exchange_ids)

    def summary(self):
        with self.lock:
            healthy = self.connected and time.monotonic()-self.last_bridge < 12
            return {'connected': healthy, 'synchronized': healthy and self.reconciled_epoch == self.epoch,
                    'recoveryReason': self.reason, 'batchesReceived': self.messages, 'revisionGaps': self.gaps,
                    'duplicateBatches': self.duplicates, 'pendingExchanges': len(self.dirty),
                    'lastBatchAt': self.last_message, 'lastHeartbeatAt': self.last_heartbeat,
                    'heartbeatLatencyMs': self.heartbeat_latency,
                    'secondsDisconnected': (round(time.monotonic()-self.disconnected_since, 2)
                                            if self.disconnected_since is not None else 0),
                    'secondsSinceBridgeMessage': round(time.monotonic()-self.last_bridge, 2)}


class FeedBridge:
    def __init__(self, tournament_id):
        if not shutil.which('node'):
            raise RuntimeError('Realtime requires Node.js 22+ and npm ci --ignore-scripts')
        if not (ROOT / 'node_modules/@supabase/supabase-js').exists():
            raise RuntimeError('Realtime dependencies missing: run npm ci --ignore-scripts')
        self.inbox = FeedInbox(tournament_id)
        self.stop = threading.Event()
        self.process = None
        self.tournament_id = tournament_id
        self.thread = threading.Thread(target=self._run, daemon=True, name='realtime-feed')
        self.thread.start()

    def _run(self):
        failures = 0
        while not self.stop.is_set():
            try:
                self.process = subprocess.Popen(
                    ['node', str(ROOT / 'research/feed_bridge.mjs'), self.tournament_id], cwd=ROOT,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
                for line in self.process.stdout:
                    if self.stop.is_set():
                        break
                    try:
                        self.inbox.accept(json.loads(line))
                    except (ValueError, KeyError, TypeError, AttributeError):
                        self.inbox.reset('invalid_bridge_message', disconnect=True)
                self.inbox.reset('bridge_exited', disconnect=True)
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.inbox.reset('bridge_process_error', disconnect=True)
            finally:
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            failures += 1
            self.stop.wait(min(30, 2 ** min(failures, 5)))

    def close(self):
        self.stop.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self.thread.join(timeout=5)

    def check_health(self):
        """Restart a hung or stuck-unsubscribed bridge, even if it emits health."""
        health = self.inbox.summary()
        silent = health['secondsSinceBridgeMessage'] > 45
        disconnected = health['secondsDisconnected'] > 90
        if silent or disconnected:
            # Give the next child a fresh recovery window; repeated error/health
            # messages themselves must never extend that window.
            with self.inbox.lock:
                self.inbox.disconnected_since = time.monotonic()
            self.inbox.accept({'kind': 'reset', 'reason': 'bridge_watchdog' if silent else 'subscription_watchdog'})
            if self.process and self.process.poll() is None:
                self.process.kill()
