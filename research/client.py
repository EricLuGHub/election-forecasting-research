"""Small API client. GETs are read-only; POST/DELETE place or cancel orders.

Order submission is gated in research.execution (dry-run default, open-tournament
check, caps, kill switch). Never call post()/delete() from ad-hoc scripts.
"""
import json
import os
from pathlib import Path
import random
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://sig.thesuper.market/api/v1'


def load_key():
    key = os.environ.get('SUPERMARKET_API_KEY')
    if not key:
        path = ROOT / '.env'
        if path.exists():
            for line in path.read_text().splitlines():
                if line.startswith('SUPERMARKET_API_KEY='):
                    key = line.split('=', 1)[1].strip().strip('\"\'')
    if not key:
        raise RuntimeError('Set SUPERMARKET_API_KEY or put it in .env')
    return key


class Client:
    def __init__(self):
        self.key = load_key()
        self.last_request = 0.0

    def get(self, path, **params):
        if not path.startswith('/') or '://' in path:
            raise ValueError('Expected an API-relative path')
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = BASE + path + ('?' + query if query else '')
        from .ratelimit import take, record_429, consumer_tag
        take('read', consumer_tag())
        network_retries = 0
        for attempt in range(5):
            time.sleep(max(0, 0.3 - (time.monotonic() - self.last_request)))
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.key})
            self.last_request = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    record_429(consumer_tag())
                if exc.code in (429, 502, 503, 504) and attempt < 4:
                    delay = exc.headers.get('Retry-After', '')
                    time.sleep(min(60, float(delay)) if delay.isdigit() else 2 ** attempt + random.random())
                    continue
                # Never include request headers or credentials in errors.
                raise RuntimeError(f'GET {path}: HTTP {exc.code}: {exc.read().decode()[:500]}') from None
            except (TimeoutError, ConnectionError, urllib.error.URLError) as exc:
                # GET is read-only. Bound network recovery separately; never
                # copy this retry into mutation routes with ambiguous outcomes.
                if network_retries < 1 and attempt < 4:
                    network_retries += 1
                    time.sleep(1)
                    continue
                raise RuntimeError(f'GET {path}: network failure ({type(exc).__name__})') from None
        raise RuntimeError('Retries exhausted')

    def pages(self, path, **params):
        rows, seen = [], set()
        while True:
            response = self.get(path, **params)
            rows.extend(response['data'])
            page = response.get('pagination', {})
            if not page.get('hasMore'):
                return rows
            cursor = page.get('nextCursor')
            if not cursor or cursor in seen:
                raise RuntimeError('Missing or repeated pagination cursor')
            seen.add(cursor)
            params['cursor'] = cursor

    def _request(self, method, path, body=None):
        if not path.startswith('/') or '://' in path:
            raise ValueError('Expected an API-relative path')
        from .ratelimit import take, record_429, consumer_tag
        take('write', consumer_tag())
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(5):
            time.sleep(max(0, 0.3 - (time.monotonic() - self.last_request)))
            req = urllib.request.Request(
                BASE + path, data=data, method=method,
                headers={'Authorization': 'Bearer ' + self.key,
                         'Content-Type': 'application/json'})
            self.last_request = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                payload = exc.read().decode()[:1000]
                if exc.code == 429:
                    record_429(consumer_tag())
                if exc.code in (429, 502, 503, 504) and attempt < 4:
                    delay = exc.headers.get('Retry-After', '')
                    time.sleep(min(60, float(delay)) if delay.isdigit() else 2 ** attempt + random.random())
                    continue
                # Never include request headers or credentials in errors.
                raise RuntimeError(f'{method} {path}: HTTP {exc.code}: {payload}') from None
        raise RuntimeError('Retries exhausted')

    def post(self, path, body):
        return self._request('POST', path, body)

    def delete(self, path):
        return self._request('DELETE', path)


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
