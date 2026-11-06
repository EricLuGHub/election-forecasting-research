"""Reproducible synthetic sensitivity tests; these are NOT return backtests."""
import json
from .client import ROOT, save_json
from .pricing import margin_probability, simulate_seats, quote


def main():
    results = {
        'label': 'SYNTHETIC ILLUSTRATIONS; NOT FITTED 2026 FORECASTS OR PROFIT BACKTESTS',
        'marginUncertainty': [{'leadPoints': lead, 'totalErrorSD': sd,
                               'winProbability': margin_probability(lead, sd)}
                              for lead in (1, 3, 5) for sd in (3, 5, 7)],
        'seatCorrelation': [simulate_seats([.65]*8, safe_seats=44, majority=51, rho=rho)
                            for rho in (0, .25, .5)],
        'makerSelection': [
            {'yesBid': .46, 'yesAsk': .54, 'probabilityYesConditionalOnBidFill': conditional,
             'expectedProfitPerBidFill': conditional-.46,
             'explanation': 'The probability conditional on being filled matters more than the unconditional midpoint.'}
            for conditional in (.50, .46, .42)],
        'quoteInventory': [dict(inventory=inventory, **quote(.60, inventory=inventory))
                           for inventory in (-1000, 0, 1000)],
    }
    save_json(ROOT / 'data/experiments.json', results)
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
