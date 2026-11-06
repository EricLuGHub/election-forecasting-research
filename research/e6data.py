"""Read-only, tournament-scoped SIG/Kalshi inputs for E6. No order routes."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .client import ROOT
from .external import event_for_title, public_get, KALSHI
from .engines.engine6_value import number


def utc():
    return datetime.now(timezone.utc).isoformat()


def contract_identity(market, node):
    """Candidate identity only. Never claims cross-venue settlement equivalence."""
    root = node.get('root', {})
    details = root.get('contract_details', {})
    mapping = event_for_title(market['title'])
    if (not mapping or root.get('node_type') != 'contract'
            or details.get('resolutionType') != 'Party Winner'
            or details.get('electionDate') != '2026-11-03'
            or details.get('raceStage') != 'General'
            or not details.get('raceId') or not details.get('stageId')
            or len(market.get('exchanges', [])) != 1):
        return None
    party = {'D': 'Democratic Party', 'R': 'Republican Party', 'I': 'Independent'}[mapping[1]]
    # Nonpartisan Nebraska and candidate-specific matches need a separate review.
    if details.get('winnerName') != party:
        return None
    race = ':'.join(str(details[k]) for k in ('raceId', 'stageId', 'electionDate', 'raceStage'))
    return {'raceKey': race, 'ticker': '-'.join(mapping)}


def exclude_own_liquidity(book, orders):
    """Remove our resting quantity: self-trade prevention makes it unfillable."""
    clean = dict(book, bids=[dict(r) for r in book['bids']], asks=[dict(r) for r in book['asks']])
    removed = 0.0
    for order in orders:
        if not order['open'] or str(order['exchangeId']) != str(book['exchangeId']):
            continue
        price, qty = number(order['priceLimit']), number(order['quantity'])
        side, action = order['side'], order['action']
        if side not in ('yes', 'no') or action not in ('buy', 'sell') or qty < 0 or not 0 < price < 1:
            raise ValueError('Invalid account order while removing self liquidity')
        yes_price = price if side == 'yes' else 1-price
        field = 'bids' if (side == 'yes') == (action == 'buy') else 'asks'
        for level in clean[field]:
            if abs(number(level['price'])-yes_price) < 1e-8:
                take = min(qty, number(level['quantity']))
                level['quantity'] = number(level['quantity'])-take
                qty -= take
                removed += take
        clean[field] = [r for r in clean[field] if r['quantity'] > 0]
    clean['bestBid'] = max((number(r['price']) for r in clean['bids']), default=None)
    clean['bestAsk'] = min((number(r['price']) for r in clean['asks']), default=None)
    clean['ownDisplayedQuantityRemoved'] = removed
    return clean


class ValueCollector:
    def __init__(self, client, slug='midterm-elections', max_books=12, reference_get=public_get):
        self.client, self.slug, self.max_books = client, slug, max_books
        self.reference_get = reference_get
        self.nodes = {}
        metadata = ROOT / 'data/monitor/metadata.json'
        if metadata.exists():
            try:
                cached = json.loads(metadata.read_text())
                if cached.get('slug') == slug:
                    self.nodes.update(cached['nodes'])
            except (OSError, KeyError, ValueError):
                pass
        # Archived definitions group existing account risk only. Every selected
        # signal's contract definition is fetched again before it can trade on paper.
        pointer = ROOT / 'data/latest.json'
        if pointer.exists():
            try:
                snapshot = json.loads(Path(json.loads(pointer.read_text())['path']).read_text())
                if snapshot['tournament']['slug'] == slug:
                    for mid, node in snapshot['nodes'].items():
                        self.nodes.setdefault(mid, node)
            except (OSError, KeyError, ValueError):
                pass

    def references(self, markets):
        tickers = sorted({'-'.join(mapping) for m in markets
                          if (mapping := event_for_title(m['title']))})
        refs, raw, errors = {}, {}, []
        for offset in range(0, len(tickers), 50):
            requested = set(tickers[offset:offset+50])
            started, cursor, seen = utc(), None, set()
            batch = {}
            try:
                while True:
                    response = self.reference_get('/markets', tickers=','.join(sorted(requested)),
                                                  limit=1000, **({'cursor': cursor} if cursor else {}))
                    for row in response['markets']:
                        ticker = row['ticker']
                        if ticker in requested:
                            batch[ticker] = row
                    cursor = response.get('cursor')
                    if not cursor:
                        break
                    if cursor in seen:
                        raise ValueError('Repeated Kalshi cursor')
                    seen.add(cursor)
                received = utc()
                for ticker, row in batch.items():
                    raw[ticker] = row
                    refs[ticker] = {'ticker': ticker, 'status': row['status'],
                                    'bid': row.get('yes_bid_dollars'), 'ask': row.get('yes_ask_dollars'),
                                    'bidSize': row.get('yes_bid_size_fp'),
                                    'askSize': row.get('yes_ask_size_fp'),
                                    'volume24h': row.get('volume_24h_fp'),
                                    'requestStartedAt': started, 'receivedAt': received,
                                    'source': KALSHI+'/markets/'+ticker}
            except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                errors.append({'resource': 'kalshi', 'error': str(exc)[:250]})
        return refs, raw, errors, len(tickers)

    def collect(self, paper, config):
        c, started = self.client, utc()
        tournament = c.get(f'/tournaments/{self.slug}')
        tid = tournament['id']
        markets = [m for m in c.pages('/markets', limit=100, tournamentId=tid)
                   if m.get('status') == 'open' and len(m.get('exchanges', [])) == 1]
        by_eid = {str(m['exchanges'][0]['id']): m for m in markets}
        refs, raw_refs, errors, requested = self.references(markets)
        quotes = {}
        eids = sorted(by_eid)
        for offset in range(0, len(eids), 100):
            response = c.get('/exchanges/prices', ids=','.join(eids[offset:offset+100]), tournamentId=tid)
            for row in response['data']:
                if str(row['exchangeId']) in by_eid:
                    quotes[str(row['exchangeId'])] = row
        ranked, comparisons, excluded = [], [], Counter()
        for eid, market in by_eid.items():
            mapping = event_for_title(market['title'])
            if not mapping or mapping[0].startswith('CONTROL'):
                excluded['unsupported_or_chamber'] += 1
                continue
            ref, q = refs.get('-'.join(mapping)), quotes.get(eid)
            if not ref or not q:
                excluded['missing_reference_or_sig_quote'] += 1
                continue
            try:
                if ref['status'] != 'active':
                    excluded['inactive_reference'] += 1
                    continue
                bid, ask = number(ref['bid']), number(ref['ask'])
                if not 0 < bid <= ask < 1 or ask-bid > config.max_reference_spread+1e-9:
                    excluded['invalid_or_wide_reference'] += 1
                    continue
                if min(number(ref['bidSize']), number(ref['askSize'])) < config.min_reference_size:
                    excluded['thin_reference'] += 1
                    continue
                if number(ref['volume24h']) < config.min_reference_volume:
                    excluded['low_reference_volume'] += 1
                    continue
                scores = []
                if q.get('bestAsk') is not None:
                    scores.append(bid-number(q['bestAsk']))
                if q.get('bestBid') is not None:
                    scores.append(number(q['bestBid'])-ask)
                if scores:
                    score = max(scores)-config.uncertainty-config.fee-config.slippage
                    comparisons.append({'exchangeId': eid, 'title': market['title'],
                                        'referenceBid': bid, 'referenceAsk': ask,
                                        'sigBid': q.get('bestBid'), 'sigAsk': q.get('bestAsk'),
                                        'bufferedTopEdge': round(score, 6)})
                    if score >= config.min_edge-1e-9:
                        ranked.append((score, eid))
                    else:
                        excluded['insufficient_edge'] += 1
                else:
                    excluded['empty_sig_book'] += 1
            except (KeyError, ValueError, TypeError):
                excluded['invalid_quote'] += 1
                continue
        held = set(paper['positions'])
        selected = sorted(held & set(by_eid))
        selected += [eid for _, eid in sorted(ranked, reverse=True)
                     if eid not in held][:self.max_books]
        instruments, books = [], {}
        for eid in selected:
            market = by_eid[eid]
            try:
                definition_start = utc()
                node = c.get(f"/markets/{market['id']}/nodes", tournamentId=tid)
                definition = {'requestStartedAt': definition_start, 'receivedAt': utc(), 'node': node}
                self.nodes[str(market['id'])] = node
                book_start = utc()
                book = c.get(f'/exchanges/{eid}/orderbook', tournamentId=tid, depth=200)
                if str(book['exchangeId']) != eid:
                    raise ValueError('Book exchange identity mismatch')
                book.update(requestStartedAt=book_start, receivedAt=utc())
                books[eid] = book
                identity = contract_identity(market, node)
                if identity is None:
                    continue
                ref = refs.get(identity['ticker'])
                if ref is None:
                    continue
                instruments.append({'exchangeId': eid, 'marketId': str(market['id']),
                                    'title': market['title'], 'raceKey': identity['raceKey'],
                                    'mappingStatus': 'candidate_requires_settlement_review',
                                    'reference': ref, 'book': book, 'definition': definition})
            except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                errors.append({'resource': eid, 'error': str(exc)[:250]})
        race_map = {}
        for eid, market in by_eid.items():
            identity = contract_identity(market, self.nodes.get(str(market['id']), {}))
            if identity:
                race_map[eid] = identity['raceKey']
        # Account reads are mandatory and paginated. A failed read aborts the
        # cycle instead of turning unknown positions/orders into an empty account.
        account_start = utc()
        positions = c.get(f'/tournaments/{self.slug}/portfolio/positions')['positions']
        orders = c.pages('/orders', status='open', limit=100, tournamentId=tid)
        pnl = c.get(f'/tournaments/{self.slug}/portfolio/pnl')
        tournament = c.get(f'/tournaments/{self.slug}')
        account = {'requestStartedAt': account_start, 'receivedAt': utc(),
                   'cash': tournament['myBalance'], 'equity': pnl['totalAccountValue'],
                   'positions': positions, 'orders': orders, 'pnl': pnl}
        for eid, book in books.items():
            books[eid] = exclude_own_liquidity(book, orders)
        for item in instruments:
            item['book'] = books[item['exchangeId']]
        unknown_cost = sum(number(p['costBasis']) for p in positions
                           if not p.get('settled') and str(p['exchangeId']) not in race_map)
        return {'now': utc(), 'startedAt': started, 'tournament': tournament,
                'account': account, 'raceByExchange': race_map, 'instruments': instruments,
                'books': books, 'rawReferences': raw_refs, 'errors': errors,
                'screening': {'excluded': dict(excluded),
                              'topComparisons': sorted(comparisons, key=lambda r: -r['bufferedTopEdge'])[:20]},
                'paperCash': paper['cash'], 'paperBankroll': paper['initialCash'],
                'paperPositions': paper['positions'],
                'coverage': {'openMarkets': len(markets), 'referenceRequests': requested,
                             'referencesReceived': len(refs), 'bulkQuotes': len(quotes),
                             'screenedCandidates': len(ranked), 'depthBooks': len(books),
                             'instruments': len(instruments), 'unmappedAccountCost': round(unknown_cost, 2)},
                'limitations': ['Candidate mappings have different settlement wording; no live orders.',
                                'Sequential REST observations are not an atomic executable snapshot.',
                                'Reference receipt time is not the time of the last trade.']}
