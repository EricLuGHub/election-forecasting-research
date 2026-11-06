"""Retrospective polling-error audit, NOT an as-of trading backtest.

Latest poll per pollster within the final 21 days, equal pollster weights.
An intentionally simple Gaussian margin-error model trains on earlier years
only. Publication timestamps and historical dataset vintages are unavailable.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, stdev

from .client import ROOT, save_json

OFFICES = ('Sen-G', 'Gov-G', 'House-G')


def normalize(row, max_days=21):
    if row['type_simple'] not in OFFICES:
        return None, 'other_office'
    parties = (row['cand1_party'], row['cand2_party'])
    if set(parties) != {'DEM', 'REP'}:
        return None, 'not_dem_rep_pair'
    try:
        poll = datetime.strptime(row['polldate'], '%m/%d/%Y').date()
        election = datetime.strptime(row['electiondate'], '%m/%d/%Y').date()
        days = (election - poll).days
        if not 0 <= days <= max_days:
            return None, 'outside_final_window'
        direction = 1 if parties[0] == 'DEM' else -1
        margin = direction * float(row['margin_poll'])
        actual = direction * float(row['margin_actual'])
        if not all(math.isfinite(x) and abs(x) <= 100 for x in (margin, actual)) or actual == 0:
            return None, 'invalid_or_tied_margin'
        year = int(row['year'])
        if year != election.year or not row['race_id'] or not row['pollster']:
            return None, 'invalid_identity'
        return dict(year=year, raceId=row['race_id'], race=row['race'], office=row['type_simple'],
                    pollDate=poll.isoformat(), electionDate=election.isoformat(), daysToElection=days,
                    pollster=row['pollster_rating_id'] or row['pollster'],
                    pollId=row['poll_id'], questionId=row['question_id'],
                    margin=margin, actual=actual, error=margin-actual), None
    except (ValueError, KeyError):
        return None, 'malformed'


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['year'], row['raceId'])].append(row)
    races, conflicts = [], []
    for key, values in sorted(groups.items()):
        if len({(x['office'], x['electionDate']) for x in values}) != 1 or max(x['actual'] for x in values) - min(x['actual'] for x in values) > .05:
            conflicts.append({'race': key, 'reason': 'Inconsistent outcome/identity'})
            continue
        pollsters = defaultdict(list)
        for row in values:
            pollsters[row['pollster']].append(row)
        estimates = []
        for polls in pollsters.values():
            last = max(x['pollDate'] for x in polls)
            # Same-date questions/populations are averaged, exact question IDs deduplicated.
            selected = {(x['pollId'], x['questionId']): x for x in polls if x['pollDate'] == last}
            estimates.append(mean(x['margin'] for x in selected.values()))
        first = values[0]
        item = {k: first[k] for k in ('year', 'raceId', 'race', 'office', 'electionDate')}
        item.update(margin=mean(estimates), actual=mean(x['actual'] for x in values),
                    pollsters=len(estimates), sourceRows=len(values),
                    latestPollDate=max(x['pollDate'] for x in values))
        item['error'] = item['margin'] - item['actual']
        races.append(item)
    return races, conflicts


def error_summary(rows):
    errors = [x['error'] for x in rows]
    return {'n': len(rows), 'biasDemPoints': mean(errors) if errors else None,
            'maePoints': mean(abs(x) for x in errors) if errors else None,
            'rmsePoints': math.sqrt(mean(x*x for x in errors)) if errors else None,
            'errorSdPoints': stdev(errors) if len(errors) > 1 else None}


def score(rows):
    if not rows:
        return {'n': 0}
    probabilities = [min(1-1e-6, max(1e-6, x['pDem'])) for x in rows]
    outcomes = [int(x['actual'] > 0) for x in rows]
    bins = []
    for lo in range(10):
        subset = [(p,y) for p,y in zip(probabilities, outcomes) if min(9, int(p*10)) == lo]
        if subset:
            bins.append({'lower': lo/10, 'n': len(subset), 'meanP': mean(p for p,y in subset), 'demWinRate': mean(y for p,y in subset)})
    return {'n': len(rows), 'brier': mean((p-y)**2 for p,y in zip(probabilities, outcomes)),
            'logLoss': -mean(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(probabilities, outcomes)),
            'callAccuracy': mean((p > .5) == bool(y) for p,y in zip(probabilities, outcomes)),
            'reliabilityBins': bins}


def walk_forward(races, test_years=(2018, 2020, 2022)):
    predictions, fits = [], []
    for year in test_years:
        for office in OFFICES:
            train = [x for x in races if x['year'] < year and x['office'] == office]
            test = [x for x in races if x['year'] == year and x['office'] == office]
            if len(train) < 30 or not test:
                continue
            bias = mean(x['error'] for x in train)
            sigma = max(1., stdev(x['error'] for x in train))
            fits.append({'testYear': year, 'office': office, 'trainingYears': sorted({x['year'] for x in train}),
                         'trainingRaces': len(train), 'biasDemPoints': bias, 'sigmaPoints': sigma})
            for row in test:
                p = .5 * (1 + math.erf((row['margin']-bias)/(sigma*math.sqrt(2))))
                predictions.append(dict(row, pDem=p, model='past-cycle-office-error-normal'))
    return predictions, fits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    directory = args.directory or Path(json.loads((ROOT / 'data/forecast-research/latest.json').read_text())['directory'])
    path = directory / 'raw-polls.csv'
    with path.open(newline='') as handle:
        raw = list(csv.DictReader(handle))
    normalized, excluded = [], Counter()
    for row in raw:
        value, reason = normalize(row)
        if value is None:
            excluded[reason] += 1
        else:
            normalized.append(value)
    races, conflicts = aggregate(normalized)
    predictions, fits = walk_forward(races)
    report = {'source': str(path), 'sourceSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'rawRows': len(raw), 'eligibleRows': len(normalized), 'excluded': dict(excluded),
              'raceAverages': len(races), 'conflicts': conflicts,
              'pollLevelError': error_summary(normalized), 'raceAverageError': error_summary(races),
              'byOfficeAndYear': [{'office': office, 'year': year, **error_summary([x for x in races if x['office']==office and x['year']==year])}
                                  for office, year in sorted({(x['office'], x['year']) for x in races})],
              'walkForwardFits': fits, 'walkForwardScore': score(predictions),
              'scoresByYear': {str(y): score([x for x in predictions if x['year']==y]) for y in (2018,2020,2022)},
              'competitiveScore': score([x for x in predictions if abs(x['margin']) <= 5]),
              'limitations': [
                  'Retrospective 2023-vintage dataset, not archived publication-time inputs.',
                  'Final 21-day field-end window is NOT a September/October 1 forecasting horizon.',
                  'Only polled DEM/REP matchups; independents, unpolled races and source omissions excluded.',
                  'Race errors within a cycle are correlated; race count is not independent evidence count.',
                  'Simple Gaussian baseline: no fundamentals, pollster grades, recency weights or shared-cycle simulation.',
                  'Year splits prevent outcome-fitting on test cycles, not all data-vintage or release-time leakage.',
                  'No quotes, fills, fees, exit liquidity or returns were tested.']}
    save_json(directory / 'polling-audit.json', report)
    save_json(directory / 'polling-race-averages.json', races)
    save_json(directory / 'polling-walk-forward-predictions.json', predictions)
    print(json.dumps({k:v for k,v in report.items() if k not in ('byOfficeAndYear', 'walkForwardFits', 'scoresByYear')}, indent=2))


if __name__ == '__main__':
    main()
