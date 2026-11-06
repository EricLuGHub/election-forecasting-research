"""Collect public Kalshi references; no credentials or real-money trading."""
import argparse
from datetime import datetime, timezone
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from .client import ROOT, save_json

KALSHI = 'https://external-api.kalshi.com/trade-api/v2'
STATES = dict(zip(
    'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming'.split('|'),
    'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split()))


def public_get(path, **params):
    url = KALSHI + path + ('?' + urllib.parse.urlencode(params) if params else '')
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 502, 503, 504) or attempt == 3:
                raise RuntimeError(f'Public Kalshi {path}: HTTP {exc.code}') from None
            time.sleep(2 ** attempt)
    raise RuntimeError('Retries exhausted')


def event_for_title(title):
    """Candidate discovery only. Returned tickers are verified against real responses."""
    match = re.fullmatch(r'Will the (Democratic|Republican|Independent) Party win the (.+)\?', title)
    if not match:
        return None
    party, race = match.groups()
    suffix = {'Democratic': 'D', 'Republican': 'R', 'Independent': 'I'}[party]
    if race in ('U.S. Senate', 'U.S. House'):
        return ('CONTROLS' if race.endswith('Senate') else 'CONTROLH') + '-2026', suffix
    house = re.fullmatch(r'([A-Z]{2})-(\d+) House race', race)
    if house:
        return f'HOUSE{house[1]}{int(house[2])}-26', suffix
    for office, prefix in [('Senate', 'SENATE'), ('Governor', 'GOVPARTY')]:
        if race.endswith(' ' + office) and race[:-(len(office) + 1)] in STATES:
            state = STATES[race[:-(len(office) + 1)]]
            # Florida is a special Senate election. Alaska party governor series has KX prefix.
            if office == 'Senate' and state == 'FL':
                return 'SENATEFLS-26', suffix
            if office == 'Governor' and state == 'AK':
                return 'KXGOVPARTYAK-26', suffix
            return prefix + state + '-26', suffix
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markets', help='Snapshot or market-list JSON; defaults to the latest completed SIG snapshot')
    args = parser.parse_args()
    path = args.markets or json.loads((ROOT / 'data/latest.json').read_text())['path']
    markets = json.loads(open(path).read())
    if isinstance(markets, dict):
        markets = markets['markets']
    result = {'startedAt': datetime.now(timezone.utc).isoformat(), 'source': KALSHI,
              'references': {}, 'missing': [], 'errors': [], 'events': {}}
    mappings = {m['id']: event_for_title(m['title']) for m in markets}
    event_ids = sorted({v[0] for v in mappings.values() if v})
    for index, event_id in enumerate(event_ids, 1):
        try:
            rows, cursor, seen = [], '', set()
            while True:
                d = public_get('/markets', event_ticker=event_id, limit=1000, **({'cursor': cursor} if cursor else {}))
                rows.extend(d['markets'])
                cursor = d.get('cursor')
                if not cursor:
                    break
                if cursor in seen:
                    raise RuntimeError('Repeated external pagination cursor')
                seen.add(cursor)
            result['events'][event_id] = rows
            received = datetime.now(timezone.utc).isoformat()
            for market in markets:
                mapping = mappings[market['id']]
                if not mapping or mapping[0] != event_id:
                    continue
                candidates = [r for r in rows if r['ticker'] == event_id + '-' + mapping[1]]
                if len(candidates) != 1:
                    result['missing'].append({'marketId': market['id'], 'title': market['title'], 'event': event_id})
                    continue
                r = candidates[0]
                b, a = float(r['yes_bid_dollars']), float(r['yes_ask_dollars'])
                valid = r['status'] == 'active' and 0 < b <= a < 1 and float(r.get('yes_bid_size_fp', 0)) > 0 and float(r.get('yes_ask_size_fp', 0)) > 0
                result['references'][market['id']] = {
                    'ticker': r['ticker'], 'title': r['title'], 'receivedAt': received,
                    'bid': b, 'ask': a, 'mid': (a + b) / 2 if valid else None,
                    'quoteValid': valid, 'volume24h': float(r.get('volume_24h_fp', 0)),
                    'bidSize': float(r.get('yes_bid_size_fp', 0)), 'askSize': float(r.get('yes_ask_size_fp', 0)),
                    'rules': r.get('rules_primary', ''), 'secondaryRules': r.get('rules_secondary', ''),
                    'mappingStatus': 'candidate_requires_settlement_review',
                    'url': KALSHI + '/markets/' + r['ticker'],
                }
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            result['errors'].append({'event': event_id, 'error': str(exc)})
        time.sleep(0.15)
        if index % 20 == 0:
            print(f'External references: {index}/{len(event_ids)} events', flush=True)
    result['completedAt'] = datetime.now(timezone.utc).isoformat()
    path = ROOT / 'data/external' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    save_json(path, result)
    save_json(ROOT / 'data/external_latest.json', {'path': str(path)})
    print(json.dumps({'file': str(path), 'references': len(result['references']),
                      'missing': len(result['missing']), 'errors': result['errors']}, indent=2))


if __name__ == '__main__':
    main()
