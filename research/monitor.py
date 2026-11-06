"""Continuous read-only quote scanner with refreshed-depth alerts and local history.

python3 -m research.monitor start
python3 -m research.monitor status
python3 -m research.monitor stop
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from .analyze import analyze, basket, race_groups
from .client import Client, ROOT

DIRECTORY = ROOT / 'data/monitor'


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    os.replace(temporary, path)


@contextmanager
def instance_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'monitor.lock').open('a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A monitor already holds this data-directory lock') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def running(directory):
    try:
        with instance_lock(directory):
            return False
    except RuntimeError:
        return True


def identity(candidate):
    legs = sorted((str(x['exchangeId']), x['side']) for x in candidate['legs'])
    return hashlib.sha256(json.dumps([candidate['kind'], legs]).encode()).hexdigest()[:20]


def candidates(snapshot, fee):
    """Return logical and explicitly conditional candidates, including one-book pairs."""
    report = analyze(snapshot, fee=fee)
    output = [dict(x, kind='exclusive_no') for x in report['logicalCandidates']]
    output.extend(dict(x, kind='conditional_yes') for x in report['conditionalCoverageCandidates'])
    for market in snapshot['markets']:
        if market['status'] != 'open':
            continue
        for exchange in market['exchanges']:
            eid = exchange['id']
            if eid not in snapshot['books']:
                continue
            legs = [{'exchangeId': eid, 'marketId': market['id'], 'title': market['title'], 'side': side}
                    for side in ('yes', 'no')]
            found = basket(snapshot['books'], legs, 1, fee)
            if found:
                output.append(dict(found, kind='same_contract_pair', race=market['title']))
    for item in output:
        item['id'] = identity(item)
    return output


def top_book(quote, started, received):
    """Unit sizes are for price screening ONLY; never used as alert depth."""
    book = dict(quote, requestStartedAt=started, receivedAt=received, bids=[], asks=[])
    for name, side in [('bestBid', 'bids'), ('bestAsk', 'asks')]:
        price = quote.get(name)
        if price is not None:
            if not math.isfinite(float(price)) or not 0 <= float(price) <= 1:
                raise ValueError('Invalid quote probability')
            book[side] = [{'price': float(price), 'quantity': 1}]
    return book


def recent(books, max_age, max_span, now=None):
    if not books:
        return False
    now = now or datetime.now(timezone.utc)
    starts = [datetime.fromisoformat(x['requestStartedAt']) for x in books.values()]
    ends = [datetime.fromisoformat(x['receivedAt']) for x in books.values()]
    return (0 <= (now - min(starts)).total_seconds() <= max_age
            and (max(ends) - min(starts)).total_seconds() <= max_span)


def exit_liquidity(books, candidate, fee):
    """Hypothetical immediate round-trip at observed depth, not an exit forecast."""
    quantity = candidate['quantityEach']
    if candidate['kind'] == 'same_contract_pair':
        return {'fullExitAvailable': True, 'netProceeds': quantity,
                'mechanism': 'YES/NO pairs in the same exchange cancel for 1 per pair; verify actual execution economics'}
    legs = []
    for leg in candidate['legs']:
        book = books[leg['exchangeId']]
        levels = [(float(x['price']) if leg['side']=='yes' else 1-float(x['price']), float(x['quantity']))
                  for x in book['bids' if leg['side']=='yes' else 'asks']]
        filled, proceeds = 0., 0.
        for price, size in sorted(levels, reverse=True):
            take = min(size, quantity-filled)
            filled += take
            proceeds += take*(price-fee)
            if filled >= quantity:
                break
        legs.append({'exchangeId': leg['exchangeId'], 'side':leg['side'],
                     'quantitySellable':filled, 'netProceeds':round(proceeds,6), 'complete':filled>=quantity})
    complete = all(x['complete'] for x in legs)
    return {'fullExitAvailable':complete, 'netProceeds':round(sum(x['netProceeds'] for x in legs),6) if complete else None,
            'legs':legs, 'mechanism':'Sell to displayed bids; separate fills and future liquidity are not guaranteed'}


class History:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
                resource TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS observations_at ON observations(at);
            CREATE TABLE IF NOT EXISTS candidate_state (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')
        self.states = {row[0]: json.loads(row[1]) for row in self.db.execute('SELECT id,payload FROM candidate_state')}
        self.last_quotes = {}

    def record(self, kind, resource, payload):
        self.db.execute('INSERT INTO observations(at,kind,resource,payload) VALUES(?,?,?,?)',
                        (utc(), kind, str(resource), json.dumps(payload, allow_nan=False)))

    def quote(self, quote):
        eid = quote['exchangeId']
        fingerprint = (quote.get('bestBid'), quote.get('bestAsk'), quote.get('latestPrice'))
        if self.last_quotes.get(eid) != fingerprint:
            self.record('quote_change', eid, quote)
            self.last_quotes[eid] = fingerprint

    def transition(self, observations, covered_exchanges, min_profit, min_edge, scope=None):
        """An unavailable refresh is UNKNOWN, never evidence of disappearance."""
        events = []
        now = utc()
        for key, item in observations.items():
            status = item['state']
            candidate = item.get('candidate')
            old = self.states.get(key)
            if status == 'confirmed':
                edge = candidate['minimumNetPayoutMinusCost'] / candidate['quantityEach']
                if candidate['minimumNetPayoutMinusCost'] < min_profit or edge + 1e-9 < min_edge:
                    status = 'below_threshold'
            state = {'id': key, 'state': status, 'observedAt': now,
                     'candidate': candidate or (old or {}).get('candidate')}
            if old and old['state'] == status and old.get('candidate') and state.get('candidate'):
                keys = ('cost', 'minimumNetPayoutMinusCost', 'quantityEach', 'tournamentStatus', 'exitLiquidity')
                changed = any(old['candidate'].get(k) != state['candidate'].get(k) for k in keys)
            else:
                changed = old is None or old['state'] != status
            if changed:
                event = dict(state, previousState=old['state'] if old else None)
                self.record('candidate_event', key, event)
                events.append(event)
            self.states[key] = state
        for key, old in list(self.states.items()):
            if key in observations or old['state'] in ('cleared', 'below_threshold'):
                continue
            eids = {str(x['exchangeId']) for x in old['candidate']['legs']}
            if scope is not None and not eids.intersection(scope):
                continue
            state = 'cleared' if eids <= covered_exchanges else 'unknown'
            updated = dict(old, state=state, observedAt=now)
            if state != old['state']:
                self.record('candidate_event', key, updated)
                events.append(updated)
            self.states[key] = updated
        for key, state in self.states.items():
            self.db.execute('INSERT OR REPLACE INTO candidate_state(id,payload) VALUES(?,?)',
                            (key, json.dumps(state, allow_nan=False)))
        self.db.commit()
        return events

    def prune(self, days):
        cutoff = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat()
        self.db.execute('DELETE FROM observations WHERE at < ?', (cutoff,))
        self.db.commit()


class Monitor:
    def __init__(self, args, client=None):
        self.args = args
        self.directory = Path(args.directory)
        self.client = client or Client()
        self.halt = threading.Event()
        self.markets, self.nodes, self.node_times = [], {}, {}
        self.catalog_at = 0.
        self.cycles = 0
        self.status = {'mode': 'READ_ONLY', 'phase': 'starting', 'startedAt': utc(), 'pid': os.getpid()}
        self.history = History(self.directory / 'history.sqlite3')
        self.tournament = None
        cache = self.directory / 'metadata.json'
        if cache.exists():
            data = json.loads(cache.read_text())
            if data.get('slug') == args.slug:
                self.nodes = data['nodes']
                self.node_times = data.get('nodeTimes', {})
        elif (ROOT / 'data/latest.json').exists():
            try:
                pointer = json.loads((ROOT / 'data/latest.json').read_text())
                snapshot = json.loads(Path(pointer['path']).read_text())
                if snapshot['tournament']['slug'] == args.slug:
                    # Only a discovery hint. Every alerted race definition is read again.
                    self.nodes = snapshot['nodes']
            except (OSError, ValueError, KeyError):
                pass

    def publish(self, **fields):
        self.status.update(fields, heartbeatAt=utc())
        atomic_json(self.directory / 'status.json', self.status)

    def read_node(self, mid):
        node = self.client.get(f'/markets/{mid}/nodes', tournamentId=self.tournament['id'])
        self.nodes[mid], self.node_times[mid] = node, time.time()
        return node

    def refresh_catalog(self):
        self.tournament = self.client.get(f'/tournaments/{self.args.slug}')
        if time.monotonic() - self.catalog_at >= self.args.discovery_interval or not self.markets:
            self.markets = self.client.pages('/markets', limit=100, tournamentId=self.tournament['id'])
            self.catalog_at = time.monotonic()
        errors = []
        open_ids = [m['id'] for m in self.markets if m['status'] == 'open']
        pending = sorted((mid for mid in open_ids if time.time() - self.node_times.get(mid, 0) > self.args.metadata_ttl),
                         key=lambda mid: (mid in self.nodes, self.node_times.get(mid, 0)))
        for mid in pending[:self.args.metadata_per_cycle]:
            try:
                self.read_node(mid)
            except (RuntimeError, OSError, ValueError) as exc:
                errors.append({'resource': f'node:{mid}', 'error': str(exc)})
        return errors

    def confirm(self, candidate):
        mids = {str(x['marketId']) for x in candidate['legs']}
        eids = {str(x['exchangeId']) for x in candidate['legs']}
        local = {'startedAt': utc(), 'tournament': self.tournament, 'errors': [],
                 'markets': [m for m in self.markets if m['id'] in mids], 'nodes': {}, 'books': {}}
        for mid in sorted(mids):
            local['nodes'][mid] = self.read_node(mid)
        for eid in sorted(eids):
            started = utc()
            b = self.client.get(f'/exchanges/{eid}/orderbook', tournamentId=self.tournament['id'], depth=200)
            b.update(requestStartedAt=started, receivedAt=utc())
            local['books'][eid] = b
        self.history.record('depth_confirmation', candidate['id'], local)
        if not recent(local['books'], self.args.max_quote_age, self.args.max_confirmation_span):
            return {'state': 'unknown', 'candidate': candidate, 'reason': 'confirmation_too_slow'}
        found = next((x for x in candidates(local, self.args.fee) if x['id'] == candidate['id']), None)
        if not found:
            return {'state': 'cleared', 'candidate': candidate}
        capital = found['cost'] + self.args.fee * found['quantityEach'] * len(found['legs'])
        liquidation = exit_liquidity(local['books'], found, self.args.fee)
        found.update(confirmedAt=utc(), tournamentStatus=self.tournament['status'],
                     capitalRequired=round(capital,6),
                     returnOnCapital=found['minimumNetPayoutMinusCost']/capital if capital > 0 else None,
                     exitLiquidity=liquidation,
                     remainingPayoutOverExit=round(found['minimumPayout']-liquidation['netProceeds'],6) if liquidation['fullExitAvailable'] else None,
                     capitalReleaseDate=None,
                     feePerShareAssumption=self.args.fee,
                     execution='NOT_EXECUTED; separate leg fills are not guaranteed',
                     settlementAssumption='Consistent binary settlement; refunds may alter payout',
                     bookReadStartedAt=min(b['requestStartedAt'] for b in local['books'].values()),
                     bookReadCompletedAt=max(b['receivedAt'] for b in local['books'].values()))
        return {'state': 'confirmed', 'candidate': found}

    def affected_exchanges(self, changed):
        """Refresh every sibling of an affected race, never compare old/new tops."""
        selected = set(changed)
        snapshot = {'markets': self.markets, 'nodes': self.nodes}
        groups = [{str(r['exchangeId']) for r in group} for group in race_groups(snapshot).values()]
        groups.extend({str(e['id']) for e in m['exchanges']} for m in self.markets)
        while True:
            expanded = selected.union(*(g for g in groups if g & selected))
            if expanded == selected:
                return selected
            selected = expanded

    def cycle(self, exchange_ids=None, guard=None):
        self.cycles += 1
        start = time.monotonic()
        self.publish(phase='scanning', cycle=self.cycles, confirmedCandidates=[])
        errors = self.refresh_catalog() if exchange_ids is None else []
        universe = [m for m in self.markets if m['status'] == 'open']
        universe_ids = {str(e['id']) for m in universe for e in m['exchanges']}
        scope = self.affected_exchanges(exchange_ids) if exchange_ids is not None else None
        open_markets = [m for m in universe if scope is None or any(str(e['id']) in scope for e in m['exchanges'])]
        eids = sorted({e['id'] for m in open_markets for e in m['exchanges']})
        snapshot = {'startedAt': utc(), 'tournament': self.tournament, 'markets': open_markets,
                    'nodes': self.nodes, 'books': {}, 'errors': errors}
        for offset in range(0, len(eids), 100):
            batch = eids[offset:offset+100]
            try:
                started = utc()
                response = self.client.get('/exchanges/prices', ids=','.join(batch), tournamentId=self.tournament['id'])
                received = utc()
                for q in response['data']:
                    if q['exchangeId'] not in batch:
                        raise ValueError('Bulk response returned an unrequested exchange')
                    book = top_book(q, started, received)
                    snapshot['books'][q['exchangeId']] = book
                    self.history.quote(q)
                missing = set(batch) - set(snapshot['books'])
                if missing:
                    errors.append({'resource': 'quotes', 'missingIds': sorted(missing)})
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                errors.append({'resource': 'bulk_quotes', 'error': str(exc)})
            self.publish(markets=len(self.markets), exchanges=len(universe_ids), scannedExchanges=len(eids),
                         cycleScope='full' if scope is None else 'affected_races', quotesRead=len(snapshot['books']))
        observations = {}
        # Confirm budget: depth-checking every candidate makes cycles slower than
        # the freshness window, so nothing ever confirms. Biggest edge first.
        shortlist = sorted(candidates(snapshot, self.args.fee),
                           key=lambda c: c.get('minimumNetPayoutMinusCost', 0),
                           reverse=True)[:12]
        for candidate in shortlist:
            try:
                observations[candidate['id']] = self.confirm(candidate)
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                errors.append({'resource': candidate['id'], 'error': str(exc)})
                observations[candidate['id']] = {'state': 'unknown', 'candidate': candidate, 'reason': str(exc)}
        # A refreshed result must still be recent at publication, including when many candidates exist.
        for item in observations.values():
            c = item.get('candidate', {})
            if guard and not guard([x['exchangeId'] for x in c.get('legs', [])]):
                item['state'] = 'unknown'
                item['reason'] = 'feed_changed_during_confirmation'
            if item['state'] == 'confirmed':
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(c['bookReadStartedAt'])).total_seconds()
                if age > self.args.max_quote_age:
                    item['state'] = 'unknown'
                    item['reason'] = 'confirmation_expired_before_publication'
        covered = {eid for eid, book in snapshot['books'].items()
                   if recent({eid: book}, self.args.max_quote_age, self.args.max_quote_age)
                   and (not guard or guard([eid]))}
        # Markets absent/closed in a successful catalog are no longer actionable.
        for previous in self.history.states.values():
            if previous.get('candidate'):
                covered.update(str(x['exchangeId']) for x in previous['candidate']['legs'] if str(x['exchangeId']) not in universe_ids)
        events = self.history.transition(observations, covered, self.args.min_profit, self.args.min_edge, scope)
        for event in events:
            c = event.get('candidate') or {}
            logging.info('%s %s | %s | profit=%s quantity=%s | tournament=%s',
                         event['state'].upper(), c.get('kind'), c.get('race'),
                         c.get('minimumNetPayoutMinusCost'), c.get('quantityEach'), self.tournament['status'])
        states = list(self.history.states.values())
        confirmed = [x['candidate'] for x in states if x['state'] == 'confirmed'
                     and (datetime.now(timezone.utc)-datetime.fromisoformat(x['candidate']['bookReadStartedAt'])).total_seconds() <= self.args.max_quote_age
                     and (not guard or guard([leg['exchangeId'] for leg in x['candidate']['legs']]))]
        grouped = {r['marketId'] for g in race_groups(dict(snapshot, markets=universe)).values() for r in g}
        if scope is None:
            self.status.update(lastFullScanAt=utc(), lastFullQuotesRead=len(snapshot['books']))
        self.publish(phase='waiting', completedAt=utc(), durationSeconds=round(time.monotonic()-start, 2),
                     tournamentStatus=self.tournament['status'], tradingStart=self.tournament['startDate'],
                     tradingEnd=self.tournament['endDate'], quotesRead=len(snapshot['books']),
                     groupedMarkets=len(grouped), metadataRead=len(set(self.nodes) & {m['id'] for m in universe}),
                     ungroupedMarkets=[{'id': m['id'], 'title': m['title']} for m in universe if m['id'] not in grouped],
                     confirmedCandidates=confirmed, unknownCandidates=sum(x['state']=='unknown' for x in states),
                     errors=errors, intervalSeconds=self.args.interval, maxQuoteAgeSeconds=self.args.max_quote_age)
        self.history.record('cycle', self.cycles, self.status)
        self.history.db.commit()
        atomic_json(self.directory / 'metadata.json', {'slug': self.args.slug, 'nodes': self.nodes, 'nodeTimes': self.node_times})
        logging.info('Cycle %d: %d/%d quotes, %d grouped markets, %d confirmed (%d conditional), %d errors, %.1fs',
                     self.cycles, len(snapshot['books']), len(eids), len(grouped), len(confirmed),
                     sum(c['kind']=='conditional_yes' for c in confirmed), len(errors), time.monotonic()-start)
        return not errors and len(snapshot['books']) == len(eids)

    def run(self):
        stop_file = self.directory / 'stop.request'
        stop_file.unlink(missing_ok=True)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.halt.set())
        self.publish()
        last_prune = 0.
        try:
            while not self.halt.is_set() and not stop_file.exists():
                started = time.monotonic()
                try:
                    self.cycle()
                except (RuntimeError, OSError, ValueError, KeyError) as exc:
                    logging.error('Scan failed: %s', exc)
                    self.publish(phase='error', errors=[{'error': str(exc)}], confirmedCandidates=[])
                if time.monotonic()-last_prune > 3600:
                    self.history.prune(self.args.retention_days)
                    last_prune = time.monotonic()
                if self.args.cycles and self.cycles >= self.args.cycles:
                    break
                deadline = max(started+self.args.interval, time.monotonic()+1)
                while time.monotonic() < deadline and not stop_file.exists() and not self.halt.is_set():
                    self.halt.wait(min(1, max(0, deadline-time.monotonic())))
        finally:
            self.publish(phase='stopped', stoppedAt=utc(), confirmedCandidates=[])
            self.history.db.close()


def options(parser):
    parser.add_argument('--directory', default=str(DIRECTORY))
    parser.add_argument('--slug', default='midterm-elections')
    parser.add_argument('--transport', choices=('realtime', 'poll'), default='realtime')
    parser.add_argument('--interval', type=float, default=15., help='Full reconciliation interval; realtime events trigger earlier scans')
    parser.add_argument('--discovery-interval', type=float, default=60.)
    parser.add_argument('--metadata-ttl', type=float, default=900.)
    parser.add_argument('--metadata-per-cycle', type=int, default=5)
    parser.add_argument('--max-quote-age', type=float, default=30.)
    parser.add_argument('--max-confirmation-span', type=float, default=5.)
    parser.add_argument('--min-profit', type=float, default=1., help='Minimum basket profit in SUSQies')
    parser.add_argument('--min-edge', type=float, default=.005, help='Minimum profit per equal-quantity basket unit')
    parser.add_argument('--fee', type=float, default=0., help='Assumed fee per share per leg')
    parser.add_argument('--retention-days', type=int, default=7)
    parser.add_argument('--cycles', type=int, default=0, help='0 keeps running; positive number for smoke tests')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('run', 'start'):
        options(sub.add_parser(command))
    for command in ('status', 'stop'):
        sub.add_parser(command).add_argument('--directory', default=str(DIRECTORY))
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    args.directory = str(directory)
    if args.command == 'status':
        path = directory / 'status.json'
        status = json.loads(path.read_text()) if path.exists() else {'phase': 'never_started'}
        status['processRunning'] = running(directory)
        if 'completedAt' in status:
            status['lastCycleAgeSeconds'] = round((datetime.now(timezone.utc)-datetime.fromisoformat(status['completedAt'])).total_seconds(), 1)
        # Never present saved confirmations as current when stopped, asleep, or behind.
        if not status['processRunning'] or status.get('lastCycleAgeSeconds', float('inf')) > status.get('maxQuoteAgeSeconds', 30):
            status['confirmedCandidates'] = []
            status['quotesCurrent'] = False
        else:
            status['quotesCurrent'] = status.get('phase') == 'waiting'
        if status.get('transport') == 'realtime':
            heartbeat_age = (datetime.now(timezone.utc)-datetime.fromisoformat(status['heartbeatAt'])).total_seconds()
            if heartbeat_age > 5 or not (status.get('feed') or {}).get('synchronized'):
                status['confirmedCandidates'] = []
                status['quotesCurrent'] = False
        print(json.dumps(status, indent=2))
        return
    if args.command == 'stop':
        if not running(directory):
            print('Monitor is not running.')
            return
        (directory / 'stop.request').touch()
        print('Stop requested. The monitor will exit after the current API operation/cycle.')
        return
    positive = (args.interval, args.discovery_interval, args.metadata_ttl, args.max_quote_age, args.max_confirmation_span)
    if (not all(math.isfinite(x) and x > 0 for x in positive) or args.interval < 5
            or not all(math.isfinite(x) and x >= 0 for x in (args.min_profit, args.min_edge, args.fee))
            or args.metadata_per_cycle < 1 or args.retention_days < 1 or args.cycles < 0):
        parser.error('Require finite positive intervals (scan >=5s), nonnegative thresholds/fees and positive retention/metadata limits')
    if args.command == 'start':
        if running(directory):
            print('Monitor is already running. Use status or stop.')
            return
        command = [sys.executable, '-u', '-m', 'research.monitor', 'run']
        for key,value in vars(args).items():
            if key != 'command':
                command.extend(['--'+key.replace('_','-'), str(value)])
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'startup.log').open('a') as output:
            process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=output, start_new_session=True)
        for _ in range(30):
            if process.poll() is not None:
                raise SystemExit('Monitor exited during startup; see data/monitor/startup.log')
            if running(directory):
                print(f'Started read-only monitor (PID {process.pid}); status/history: {directory}')
                return
            time.sleep(.1)
        raise SystemExit('Startup not confirmed; inspect status and startup.log')
    try:
        with instance_lock(directory):
            handler = RotatingFileHandler(directory / 'monitor.log', maxBytes=2_000_000, backupCount=3)
            handlers = [handler]
            if sys.stdout.isatty():
                handlers.append(logging.StreamHandler(sys.stdout))
            logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=handlers)
            if args.transport == 'realtime':
                from .live_monitor import RealtimeMonitor
                RealtimeMonitor(args).run()
            else:
                Monitor(args).run()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
