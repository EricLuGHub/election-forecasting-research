"""Public, read-only election research collection. No SIG key or trading calls.

Each run archives source bytes, hashes, retrieval times and failures in data/.
Forecasts are research references, not settlement-equivalent trade signals.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request

from .client import ROOT, save_json

RAW = 'https://raw.githubusercontent.com/fivethirtyeight/data/master/'
SOURCES = [
    ('raw-polls.csv', RAW + 'pollster-ratings/2023/raw-polls.csv', 'csv', {'poll_id', 'race_id', 'polldate', 'margin_actual'}),
    ('pollster-ratings.csv', RAW + 'pollster-ratings/2023/pollster-ratings.csv', 'csv', {'Pollster', '538 Grade'}),
    ('historical-senate-QUARANTINED.csv', RAW + 'forecast-methodology/historical-senate-predictions.csv', 'csv', {'state', 'year', 'forecast_prob', 'winflag'}),
    ('historical-senate-readme.txt', RAW + 'forecast-methodology/README.md', 'text', set()),
    ('votehub-methodology.pdf', 'https://votehub.com/wp-content/uploads/2026/05/2026_votehub_midterm_methodology.pdf', 'pdf', set()),
    ('aapor-2024-summary.pdf', 'https://aapor.org/wp-content/uploads/2025/10/Task-Force-on-2024-Pre-Election-Polling-Report-Executive-Summary.pdf', 'pdf', set()),
    ('fec-2010.pdf', 'https://www.fec.gov/documents/1674/federalelections2010.pdf', 'pdf', set()),
    ('medsl-senate-metadata.json', 'https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/PEJ5QU', 'json', set()),
    ('medsl-house-metadata.json', 'https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/IG0UN2', 'json', set()),
    ('legacy-538-senate.csv', 'https://projects.fivethirtyeight.com/2022-general-election-forecast-data/senate_state_toplines_2022.csv', 'csv', {'forecastdate', 'state'}),
]
RTTWH = 'https://www.racetothewh.com/senate/26'


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(body, kind, expected=()):
    if kind == 'pdf':
        if not body.startswith(b'%PDF-'):
            raise ValueError('Expected PDF signature')
        return None
    value = body.decode('utf-8-sig')
    if kind == 'json':
        return json.loads(value)
    if kind in ('csv', 'tsv'):
        if value.lstrip().startswith('<'):
            raise ValueError('HTML response, not CSV')
        rows = csv.DictReader(io.StringIO(value), delimiter='\t' if kind == 'tsv' else ',')
        if not set(expected).issubset(rows.fieldnames or []):
            raise ValueError(f'CSV missing required headers: {sorted(set(expected) - set(rows.fieldnames or []))}')
        return list(rows)
    return value


class Archive:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.entries = []

    def get(self, name, url, kind='text', expected=()):
        item = {'file': name, 'url': url, 'retrievedAt': now()}
        self.entries.append(item)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ElectionResearch/0.1 (public read-only snapshot)'})
            with urllib.request.urlopen(req, timeout=25) as response:
                body = response.read(20_000_001)
                item.update(finalUrl=response.url, statusCode=response.status,
                            contentType=response.headers.get('Content-Type'), bytes=len(body))
            if len(body) > 20_000_000:
                raise ValueError('Source exceeds 20 MB collection limit')
            result = validate(body, kind, expected)
            (self.directory / name).write_bytes(body)
            item.update(status='ok', sha256=hashlib.sha256(body).hexdigest())
            if kind in ('csv', 'tsv'):
                item['rows'] = len(result)
            return result
        except Exception as exc:
            item.update(status='unavailable_or_rejected', error=f'{type(exc).__name__}: {exc}')
            return None


def embedded_json(html, variable):
    match = re.search(r'window\.' + re.escape(variable) + r'\s*=\s*', html)
    if not match:
        raise ValueError(f'Missing public embed variable: {variable}')
    return json.JSONDecoder().raw_decode(html[match.end():])[0]


def sheets(payload):
    names, data = payload['sheetNames'], payload['data']
    if len(names) != len(data) or len(names) != len(set(names)):
        raise ValueError('Ambiguous sheet names/data alignment')
    return dict(zip(names, data))


def parse_forecasts(payload):
    table = sheets(payload)
    rows = table['Win']
    if not rows or rows[0] != ['', 'D', 'R', 'Ind']:
        raise ValueError('Forecast schema changed; review party/candidate semantics')
    result, issues = [], []
    for row in rows[1:]:
        if not row or not row[0] or str(row[0]).startswith('Special '):
            continue  # Unfilled template rows, not real special-election identifiers.
        if len(row) != len(rows[0]):
            raise ValueError(f'Forecast row length changed in {row[0]}')
        candidates = []
        for label, cell in zip(rows[0][1:], row[1:]):
            if not cell:
                continue
            match = re.fullmatch(r'(.+):\s*(\d+(?:\.\d+)?)%', str(cell))
            if not match or not 0 <= float(match[2]) <= 100:
                raise ValueError(f'Invalid candidate probability in {row[0]}')
            candidates.append({'candidate': match[1], 'sourceColumn': label,
                               'p': float(match[2]) / 100, 'raw': cell})
        total = sum(c['p'] for c in candidates)
        if not candidates or abs(total - 1) > .002:
            issues.append({'race': row[0], 'reason': 'Probabilities do not sum approximately to one', 'sum': total})
        result.append({'race': row[0], 'candidates': candidates,
                       'mappingApproved': False,
                       'warning': 'Source column is NOT verified ballot party or SIG settlement identity.'})
    return {'races': result, 'issues': issues,
            'sourceAsOfLabel': table.get('Last Update'),
            'transportRefreshedAt': payload.get('refreshed'),
            'chamberControl': table.get('Chance to Win'),
            'note': 'Display update label lacks year/timezone precision; transport refresh is not forecast issuance.'}


def parse_polls(payload):
    result, seen = [], set()
    for state, rows in sheets(payload).items():
        if not rows or len(rows[0]) < 2 or rows[0][1] != 'Poll (Includes Link)':
            continue
        for row in rows[1:]:
            if len(row) < 4 or not isinstance(row[1], dict):
                continue
            link = row[1]
            if not str(link.get('href', '')).startswith(('https://', 'http://')):
                continue
            key = (state, link['href'], str(link.get('value')), str(row[2:]))
            if key in seen:
                continue
            seen.add(key)
            result.append({'race': state, 'sourceUrl': link['href'],
                           'label': link.get('value'), 'sourceHeaders': rows[0], 'rawCells': row,
                           'warning': 'Dates and party/candidate identities require validation before modeling.'})
    return result


def collect_current(archive):
    page = archive.get('racetothewh-senate.html', RTTWH)
    if page is None:
        return {'error': 'Forecast page unavailable'}
    urls = re.findall(r'https://e\.infogram\.com/[^\s"<>]+', page)
    # Public embed observed in the forecast page, not an authenticated API.
    if not urls:
        return {'error': 'No public Infogram embed discovered'}
    result = {'forecasts': 0, 'pollRows': 0, 'issues': []}
    for index, url in enumerate(dict.fromkeys(urls)):
        html = archive.get(f'rttwh-embed-{index}.html', url.replace('&amp;', '&'))
        if html is None:
            continue
        try:
            data = embedded_json(html, 'infographicData')
            config = embedded_json(html, 'publicViewConfig')
            if config.get('liveDataURL') != 'https://live-data.jifo.co/':
                raise ValueError('Unrecognized public live-data host')
            entities = data['elements']['content']['content']['entities']
            selected = {}
            for entity in entities.values():
                live = entity.get('props', {}).get('chartData', {}).get('custom', {}).get('live', {})
                title = live.get('title')
                if title in ('Sen 26 - Main Graphics', 'Sen 26 - Publish Poll List'):
                    selected.setdefault(title, live['key'])
            for title, key in selected.items():
                if not re.fullmatch(r'[a-f0-9-]{36}', key):
                    raise ValueError('Unexpected public chart identifier')
                payload = archive.get(f'rttwh-{key}.json', config['liveDataURL'] + key, 'json')
                if payload is None:
                    continue
                if title.endswith('Main Graphics'):
                    forecasts = parse_forecasts(payload)
                    forecasts.update(sourceUrl=RTTWH, collectedAt=now())
                    save_json(archive.directory / 'current-senate-forecasts.json', forecasts)
                    result['forecasts'] = len(forecasts['races'])
                    result['forecastAsOf'] = forecasts['sourceAsOfLabel']
                    result['issues'].extend(forecasts['issues'])
                else:
                    polls = parse_polls(payload)
                    save_json(archive.directory / 'current-senate-polls.json', {
                        'sourceUrl': RTTWH, 'collectedAt': now(),
                        'transportRefreshedAt': payload.get('refreshed'), 'polls': polls})
                    result['pollRows'] = len(polls)
            if result['forecasts'] and result['pollRows']:
                break
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            result['issues'].append({'embed': url, 'error': str(exc)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    directory = args.directory or ROOT / 'data/forecast-research' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    archive = Archive(directory)
    for name, url, kind, required in SOURCES:
        value = archive.get(name, url, kind, required)
        print(f'{name}: {archive.entries[-1]["status"]}', flush=True)
        if value is not None and name.startswith('medsl-'):
            for item in value.get('data', {}).get('latestVersion', {}).get('files', []):
                file = item['dataFile']
                if item.get('restricted') or file.get('restricted'):
                    continue
                filename = file['filename']
                if filename.startswith('1976-') and filename.endswith('.tab'):
                    chamber = name.split('-')[1]
                    archive.get(f'medsl-{chamber}-results.tsv',
                                f'https://dataverse.harvard.edu/api/access/datafile/{int(file["id"])}',
                                'tsv', {'year', 'state', 'candidate', 'candidatevotes'})
    current = collect_current(archive)
    manifest = {'collectedAt': now(), 'sources': archive.entries, 'current': current,
                'quarantine': {'historical-senate-QUARANTINED.csv':
                    'Arizona 2010 labels Glassman winner and McCain loser, contrary to FEC. Do not score or train on this file.'},
                'constraints': ['No trading calls', 'No calibrated 2026 model',
                    'Current source columns are not approved SIG party mappings',
                    '2023 pollster grades are future information for earlier-cycle backtests']}
    save_json(directory / 'manifest.json', manifest)
    save_json(ROOT / 'data/forecast-research/latest.json', {'directory': str(directory.resolve()), 'completedAt': now()})
    print(json.dumps({'directory': str(directory), 'current': current}, indent=2))


if __name__ == '__main__':
    main()
