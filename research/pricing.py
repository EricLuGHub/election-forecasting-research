"""Pricing primitives. Model assumptions are explicit; parameters are not fitted."""
from math import ceil, floor, isfinite, log, sqrt
from statistics import NormalDist
import random


def probability(value):
    if not isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Probability must be finite and in [0, 1]')
    return value


def margin_probability(mean_margin, total_error_sd):
    """Both inputs in percentage points; SD includes non-sampling election error."""
    if not isfinite(mean_margin) or not isfinite(total_error_sd) or total_error_sd <= 0:
        raise ValueError('Require a finite mean and positive total error SD')
    return NormalDist().cdf(mean_margin / total_error_sd)


def buy_levels(book, side):
    """Convert the unified YES book to ascending costs for buying YES or NO."""
    if side not in ('yes', 'no'):
        raise ValueError('side must be yes or no')
    return sorted([(float(x['price']) if side == 'yes' else 1 - float(x['price']),
                    float(x['quantity'])) for x in book['asks' if side == 'yes' else 'bids']
                   if float(x['quantity']) > 0])


def sweep(book, side, quantity):
    if quantity <= 0 or not isfinite(quantity):
        raise ValueError('quantity must be positive and finite')
    cost, filled, worst = 0., 0., None
    for price, available in buy_levels(book, side):
        take = min(available, quantity - filled)
        filled += take
        cost += price * take
        worst = price
        if filled >= quantity:
            break
    return {'requested': quantity, 'filled': filled, 'cost': cost,
            'vwap': cost / filled if filled else None, 'worstPrice': worst,
            'complete': filled >= quantity}


def fractional_kelly(p, cost, fraction=0.25, max_fraction=0.01):
    """Fraction of bankroll spent, for an isolated $1-or-$0 long contract.

    The cap and quarter-Kelly default are illustrative research settings, not a
    joint portfolio optimizer. Correlated bets cannot each use the full budget.
    """
    probability(p)
    if not 0 < cost < 1 or not 0 <= fraction <= 1 or not 0 <= max_fraction <= 1:
        raise ValueError('Invalid price or risk fraction')
    return min(max_fraction, fraction * max(0., (p - cost) / (1 - cost)))


def quote(p, uncertainty=0.025, fee=0., inventory=0., inventory_limit=1000., half_spread=0.01):
    """Inventory-skewed research quotes; returns YES bid and ask on 0.005 ticks."""
    probability(p)
    if min(uncertainty, fee, half_spread) < 0 or inventory_limit <= 0:
        raise ValueError('Invalid quoting parameters')
    center = p - 0.02 * max(-1, min(1, inventory / inventory_limit))
    width = uncertainty + fee + half_spread
    bid = floor((center - width + 1e-12) / .005) * .005
    ask = ceil((center + width - 1e-12) / .005) * .005
    return {'yesBid': round(bid, 3) if .005 <= bid <= .995 else None,
            'yesAsk': round(ask, 3) if .005 <= ask <= .995 else None}


def scores(predictions, outcomes):
    if not predictions or len(predictions) != len(outcomes):
        raise ValueError('Require equal nonempty prediction and outcome lists')
    for p, y in zip(predictions, outcomes):
        probability(p)
        if y not in (0, 1):
            raise ValueError('Outcomes must be binary')
    n = len(predictions)
    return {'n': n, 'brier': sum((p - y) ** 2 for p, y in zip(predictions, outcomes)) / n,
            'logLoss': -sum(y * log(max(1e-12, p)) + (1-y) * log(max(1e-12, 1-p))
                            for p, y in zip(predictions, outcomes)) / n}


def simulate_seats(probabilities, safe_seats, majority, rho=0.25, draws=30000, seed=7):
    """Gaussian-copula sensitivity model with a shared national shock.

    Rho is latent-normal correlation, not binary-outcome correlation. Inputs must
    cover ALL remaining relevant seats and treat independent caucusing correctly.
    """
    if not 0 <= rho < 1 or draws <= 0:
        raise ValueError('Invalid simulation parameters')
    for p in probabilities:
        probability(p)
    rng, normal = random.Random(seed), NormalDist()
    thresholds = [normal.inv_cdf(p) if 0 < p < 1 else (float('inf') if p == 1 else -float('inf')) for p in probabilities]
    totals = []
    for _ in range(draws):
        common = sqrt(rho) * rng.gauss(0, 1)
        totals.append(safe_seats + sum(common + sqrt(1-rho) * rng.gauss(0, 1) < z for z in thresholds))
    p = sum(n >= majority for n in totals) / draws
    totals.sort()
    return {'controlProbability': p, 'meanSeats': sum(totals)/draws,
            'seatP05': totals[int(.05 * draws)], 'seatP95': totals[int(.95 * draws)],
            'monteCarloSE': sqrt(p * (1-p) / draws), 'latentCorrelation': rho}
