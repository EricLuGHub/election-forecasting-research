"""Read-only LAN status server. Serves monitor/account state; never orders.

Routes: GET /status, /health, /candidates, /pnl, /alloc. Binds LAN only.
Optional bearer token via LAN_TOKEN env. No POST routes exist on purpose:
order placement and cancel-all are never exposed here.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from .client import ROOT


class Handler(BaseHTTPRequestHandler):
    def _send(self, value, code=200):
        body = json.dumps(value, indent=2, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self):
        token = os.environ.get('LAN_TOKEN')
        if token and self.headers.get('Authorization') != f'Bearer {token}':
            self._send({'error': 'unauthorized'}, 401)
            return False
        return True

    def do_GET(self):  # noqa: N802 - stdlib naming
        if not self._guard():
            return
        if self.path == '/status':
            path = ROOT / 'data/monitor/status.json'
            self._send(json.loads(path.read_text()) if path.exists() else {'phase': 'never_started'})
        elif self.path == '/health':
            self._send(health())
        elif self.path == '/candidates':
            path = ROOT / 'data/monitor/status.json'
            status = json.loads(path.read_text()) if path.exists() else {}
            self._send(status.get('confirmedCandidates', []))
        elif self.path == '/alloc':
            path = ROOT / 'data/alloc.json'
            self._send(json.loads(path.read_text()) if path.exists() else {})
        elif self.path == '/e6':
            from .e6run import read_status
            self._send(read_status())
        elif self.path == '/e7':
            from datetime import datetime, timezone
            path = ROOT / 'data/e7/status.json'
            status = json.loads(path.read_text()) if path.exists() else {'phase': 'never_started'}
            if status.get('at'):
                status['ageSeconds'] = round((datetime.now(timezone.utc)-datetime.fromisoformat(status['at'])).total_seconds(), 1)
                status['stale'] = status['ageSeconds'] > 180
            self._send(status)
        elif self.path == '/trial':
            from datetime import datetime, timezone
            from .trial import DIRECTORY
            result = {}
            for name in ('status', 'health', 'evaluation'):
                path = DIRECTORY/(name+'.json')
                value = json.loads(path.read_text()) if path.exists() else {'phase': 'not_available'}
                if value.get('at'):
                    age = (datetime.now(timezone.utc)-datetime.fromisoformat(value['at'])).total_seconds()
                    value.update(ageSeconds=round(age, 1), stale=not 0 <= age <= 180)
                result[name] = value
            self._send(result)
        elif self.path == '/recovery':
            from datetime import datetime, timezone
            path = ROOT / 'data/recovery/status.json'
            status = json.loads(path.read_text()) if path.exists() else {'phase': 'never_started'}
            if status.get('at'):
                status['ageSeconds'] = round((datetime.now(timezone.utc)-datetime.fromisoformat(status['at'])).total_seconds(), 1)
                status['stale'] = status['ageSeconds'] > 180
            self._send(status)
        elif self.path == '/campaign':
            from datetime import datetime, timezone
            path = ROOT / 'data/top20/campaign-status.json'
            status = json.loads(path.read_text()) if path.exists() else {'phase': 'never_started'}
            if status.get('at'):
                status['ageSeconds'] = round((datetime.now(timezone.utc)-datetime.fromisoformat(status['at'])).total_seconds(), 1)
                status['stale'] = status['ageSeconds'] > 1200
            self._send(status)
        elif self.path == '/review':
            path = ROOT / 'data/review.log'
            if not path.exists():
                self._send({'review': None})
            else:
                lines = path.read_text().strip().split('\n')
                self._send([json.loads(line) for line in lines[-6:] if line.startswith('{')])
        elif self.path in ('/', '/dashboard'):
            body = dashboard().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send({'error': 'not found', 'routes': ['/', '/status', '/health', '/candidates', '/alloc', '/review', '/e6', '/e7', '/trial', '/recovery', '/campaign']}, 404)

    def log_message(self, *args):
        pass


def dashboard():
    """Single-page read-only overview. Every section fails soft to 'n/a'."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime('%H:%M:%SZ')
    acct, positions, fills = 'n/a', [], []
    try:
        from .client import Client
        c = Client()
        p = c.get('/tournaments/midterm-elections/portfolio/pnl')
        acct = (f"PnL <b>{round(p.get('periodPnl', 0), 2)}</b> &nbsp; value "
                f"<b>{round(p.get('totalAccountValue', 0), 2)}</b> &nbsp; holdings "
                f"{round(p.get('totalHoldingsValue', 0) or 0, 2)}")
        pos = c.get('/tournaments/midterm-elections/portfolio/positions').get('positions', [])
        positions = sorted(pos, key=lambda z: abs(z.get('unrealizedPnl', 0)), reverse=True)[:15]
        f = c.get('/tournaments/midterm-elections/portfolio/fills', limit=8)
        rows = f.get('data', f) if isinstance(f, dict) else f
        fills = rows if isinstance(rows, list) else []
    except (RuntimeError, OSError, ValueError, KeyError):
        pass

    def section(title, body):
        return f'<h2>{title}</h2>{body}'

    try:
        status = json.loads((ROOT / 'data/monitor/status.json').read_text())
        mon = (f"phase {status.get('phase')} · cycle {status.get('cycle')} · "
               f"confirmed {len(status.get('confirmedCandidates', []))} · "
               f"feed {((status.get('feed') or {}).get('connected'))}/{((status.get('feed') or {}).get('synchronized'))} · "
               f"errors {len(status.get('errors', []))}")
    except (OSError, ValueError):
        mon = 'n/a'
    try:
        alloc = json.loads((ROOT / 'data/alloc.json').read_text())
        modes = ' · '.join(f"{k}: {v.get('mode')}" for k, v in alloc.get('engines', {}).items())
        modes += f" (envelope {alloc.get('total_live_envelope')})"
    except (OSError, ValueError):
        modes = 'n/a'
    try:
        mode = json.loads((ROOT / 'data/recovery/mode.json').read_text())
        modes += f"<br>recovery: {json.dumps(mode)[:200]}"
    except (OSError, ValueError):
        pass

    rows_html = ''.join(
        f"<tr><td>{x.get('exchangeId')}</td><td>{(x.get('marketTitle') or '')[:38]}</td>"
        f"<td>{x.get('quantity')}</td><td>{x.get('avgCost')}</td>"
        f"<td>{round(x.get('currentPrice', 0), 3)}</td>"
        f"<td>{round(x.get('unrealizedPnl', 0), 2)}</td></tr>" for x in positions)
    fills_html = ''.join(
        f"<tr><td>{r.get('filledAt', '')[11:19]}</td><td>{r.get('exchangeId')}</td>"
        f"<td>{r.get('side')}</td><td>{r.get('quantity')}</td><td>{r.get('price')}</td></tr>"
        for r in fills)
    try:
        rev = (ROOT / 'data/review.log').read_text().strip().split('\n')[-1]
        rev = json.loads(rev) if rev.startswith('{') else {}
        rev_html = (f"pnl {rev.get('account', {}).get('pnl')} · value "
                    f"{rev.get('account', {}).get('value')} · open "
                    f"{rev.get('account', {}).get('open_orders')} · taken {rev.get('e2_taken')}")
    except (OSError, ValueError, IndexError):
        rev_html = 'n/a'
    return (f"""<html><head><meta http-equiv="refresh" content="30"><title>Cup</title>
<style>body{{font-family:monospace;max-width:900px;margin:auto;padding:12px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:3px 6px;font-size:12px}}h2{{margin:14px 0 4px;font-size:15px}}</style>
</head><body><h1>Predictions Cup — {now}</h1>"""
            f"{section('Account', acct)}"
            f"{section('Engines', modes)}"
            f"{section('Monitor', mon)}"
            f"{section('Top positions', f'<table><tr><th>ex</th><th>market</th><th>qty</th><th>avg</th><th>mark</th><th>uPnl</th></tr>{rows_html}</table>')}"
            f"{section('Recent fills', f'<table><tr><th>time</th><th>ex</th><th>side</th><th>qty</th><th>px</th></tr>{fills_html}</table>')}"
            f"{section('Last review', rev_html)}"
            f"<p>JSON: /status /health /candidates /alloc /review /e6 /e7 /trial /recovery /campaign</p></body></html>""")


def health():
    out = {'ok': True, 'checks': {}}
    status_path = ROOT / 'data/monitor/status.json'
    if not status_path.exists():
        return {'ok': False, 'checks': {'status_file': 'missing'}}
    from datetime import datetime, timezone
    status = json.loads(status_path.read_text())
    out['checks']['phase'] = status.get('phase')
    out['checks']['pid'] = status.get('pid')
    completed = status.get('completedAt')
    if completed:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(completed)).total_seconds()
        out['checks']['last_cycle_age_s'] = round(age, 1)
        if age > status.get('maxQuoteAgeSeconds', 30) + 120:
            out['ok'] = False
    feed = status.get('feed') or {}
    out['checks']['feed'] = {'connected': feed.get('connected'), 'synchronized': feed.get('synchronized')}
    if status.get('transport') == 'realtime' and not (feed.get('connected') and feed.get('synchronized')):
        out['ok'] = False
    if status.get('errors'):
        out['checks']['errors'] = status['errors'][:5]
        out['ok'] = False
    import shutil
    usage = shutil.disk_usage(ROOT / 'data')
    out['checks']['disk_free_gb'] = round(usage.free / 1e9, 2)
    if usage.free < 1e9:
        out['ok'] = False
    return out


def main():
    port = int(os.environ.get('LAN_PORT', '8000'))
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'LAN read-only server on :{port} (no order routes)', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
