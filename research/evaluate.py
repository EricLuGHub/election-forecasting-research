"""Evaluate archived, out-of-sample binary probabilities against resolved outcomes.

CSV columns: forecast_date,event_date,event_id,model,p,outcome. Use one horizon
per event/model. Split model fitting by whole election cycles before using this.
"""
import argparse
import csv
from collections import defaultdict
from datetime import datetime
import json
from .pricing import scores


def evaluate(rows):
    models, seen = defaultdict(list), set()
    for row in rows:
        if datetime.fromisoformat(row['forecast_date']) >= datetime.fromisoformat(row['event_date']):
            raise ValueError('Forecast must precede event; post-event observations are not a backtest')
        key = row['model'], row['event_id']
        if key in seen:
            raise ValueError('Duplicate event/model; evaluate separate horizons in separate files')
        seen.add(key)
        models[row['model']].append((float(row['p']), int(row['outcome']), row['event_id']))
    if not models:
        raise ValueError('No observations')
    event_sets = [{r[2] for r in data} for data in models.values()]
    if any(ids != event_sets[0] for ids in event_sets):
        raise ValueError('Compare models on the same events')
    result = {}
    for name, data in models.items():
        entry = scores([r[0] for r in data], [r[1] for r in data])
        bins = defaultdict(list)
        for p, y, _ in data:
            bins[min(9, int(p*10))].append((p,y))
        entry['reliability'] = [{'bin': b, 'n': len(v), 'meanPrediction': sum(p for p,y in v)/len(v),
                                 'observedFrequency': sum(y for p,y in v)/len(v)} for b,v in sorted(bins.items())]
        result[name] = entry
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv')
    args = parser.parse_args()
    with open(args.csv, newline='') as f:
        print(json.dumps(evaluate(list(csv.DictReader(f))), indent=2))


if __name__ == '__main__':
    main()
