# How to price these markets

Our first competitive advantage should be knowing when we have **no edge**.
The initial live-data scan found SIG's seed midpoints nearly identical to
Kalshi's in most comparable contracts, with SIG charging an eight-point spread.
A model that merely reproduces the consensus will usually lose by crossing it.

## 1. Price the exact settlement event

Before assigning a probability, record jurisdiction, office, election year,
race/stage ID, party or candidate, general versus special election, runoff
treatment, determination source, and refund conditions. Store the actual rules
beside the estimate. Recheck when rules or candidates change.

SIG's nodes are much more informative than titles. For example, Nebraska's
"Independent Party" market uses `winnerName=Nonpartisan`; Montana uses
`Independent`. A candidate-specific external contract can fail to match a
party-winner contract if the nominee changes. An election winner and the person
eventually sworn in can also differ.

Treat the four chamber markets separately until the treatment of a 50–50 Senate,
independent caucusing, vacancies and delayed seating is clear. Their current
freeform language says majority control/majority of seats when Congress is
seated, with manual resolution following news calls. Kalshi's Senate control
contract has a President-pro-tempore fallback. Similar headlines do not prove
identical payouts. The script flags every external mapping for review.

## 2. Use outside prices as an initial estimate

For a liquid matched contract, begin with its current bid/ask interval. Store
displayed size, retrieval time and recent activity. A last trade may be stale;
a displayed 99% with negligible size is not equivalent to a deep 99% book.
The current collector accesses [Kalshi's public market data](https://docs.kalshi.com/api-reference/market/get-markets).

The midpoint is an initial estimate, not a truth label or confidence interval.
Widen our uncertainty for broad spreads, thin books, stale observations,
inconsistent sources and settlement differences. The code's three-point haircut
is a sensitivity setting, not a statistically calibrated 95% bound.

Use a second source when accessible, but do not treat multiple venues as
independent samples: they may share traders, polling inputs and bots. Polymarket
Gamma returned HTTP 403 in this environment, so this run has no usable Polymarket
API reference. Do not fill the gap with search-snippet prices.

## 3. Build an independent election estimate where it matters

For a two-candidate race, model the final vote margin, not just today's poll
lead. Start with historical partisan lean adjusted to current district lines,
incumbency, candidate information and the national environment; update with
dated polls. Pool sparse races with comparable races. Keep multiple-candidate
and ranked-choice races in a model that actually represents their outcomes.

A transparent starting approximation is:

`final margin = expected margin + national error + state/regional error + race error`

Under a normal approximation, `P(win) = Φ(expected margin / total error SD)`.
The SD must include correlated polling bias, turnout/model error and movement
between today and election day. Poll sampling error alone is inadequate. Fit
these components on archived forecasts at the same days-to-election horizon;
heavy-tailed alternatives should be compared out of sample.

The implemented sensitivity experiment shows how much this matters:

| Assumed lead | Total error SD | Implied win probability |
| --- | --- | --- |
| 3 points | 3 points | 84.1% |
| 3 points | 5 points | 72.6% |
| 3 points | 7 points | 66.6% |

These are synthetic examples, not estimates for any actual race. Getting the
error distribution right can matter more than moving the polling average by
half a point. Do not convert a qualitative "Lean" or "Likely" rating into a
precise probability without measuring its historical performance. [Cook's own
rating definitions](https://www.cookpolitical.com/ratings/senate-race-ratings)
describe competitiveness rather than supplying calibrated numerical odds.

## 4. Earn any adjustment away from the baseline

Keep three estimates: the external consensus, our independent model, and a
combined forecast. Fit the combination's weights on earlier election cycles,
using only information available at the forecast timestamp. Do not invent
weights such as "70% market, 30% polls" and describe them as validated.

For each disagreement, write down the mechanism: newly released polling,
candidate withdrawal, redistricting, an incorrectly interpreted settlement
rule, or a repeatable error established on historical data. A narrative alone
does not establish an edge. A large disagreement is a prompt to inspect both
models and the contract mapping.

We should only concentrate research on disagreements large enough to survive
the executable price and uncertainty allowance. We do not need superior
forecasts for all 237 contracts to find a few useful trades.

## 5. Derive chamber probabilities from a joint model

Single-race probabilities do not uniquely determine Senate or House control.
Simulate shared national/regional shocks and race-specific errors, resolve
independent caucusing and special elections, then count seats in each draw.
Include unlisted races: SIG offers only 34 Senate races and 46 House races in
this snapshot, not a complete chamber model.

Our synthetic example gives a party 44 certain seats and eight races at 65%
each, needing 51 seats. With identical marginal probabilities:

| Latent Gaussian correlation | Simulated control probability |
| --- | --- |
| 0 | 17.2% |
| 0.25 | 29.7% |
| 0.50 | 39.2% |

These 30,000-draw results demonstrate sensitivity, not a 2026 forecast. Latent
correlation is not the correlation of the binary results. The model in
`pricing.py` has only one common factor; production work needs richer dependence
and historically fitted parameters. Monte Carlo error is much smaller than
the uncertainty about model structure.

## 6. Convert probability into a price decision

For YES, per-share expected profit held to binary settlement is `p - cost`.
For NO it is `(1-p) - cost`. Use the book's depth-weighted cost, not the midpoint.
The SIG book is YES-normalized, so the NO ask is `1 - YES bid`.

Use a conservative probability for entry: a low estimate for YES, or one minus
the high YES estimate for NO. Subtract fees, expected slippage and any basis
allowance. For example, a YES estimate of 60.5% does not justify paying 64.5%.
The paper planner reproduces this on the Senate-control book.

Resting orders can improve economics. With an assumed fair price of 60.5%, a
58.5% bid and 62.5% ask each have a two-point unconditional cushion. That cushion
must pay for forecast error and adverse selection. A buyer of our ask may know
something that has already moved the fair price above 62.5%.

Quarter-Kelly for an isolated YES purchase has cash fraction
`0.25 * max(0, (p-cost)/(1-cost))`; the sample function also caps it at 1%.
These are illustrative parameters. Do not apply that cap independently to
dozens of positively correlated races. Portfolio risk must include all open
orders filling, same-race exposures, national political factors and cash tied
up until settlement. Prize maximization can require a different objective than
log-bankroll growth.


!!! why not a full kelly, why quarter kelly. are we pussies or what?

## 7. Measure accuracy and executable profitability separately

Archive immutable forecasts before outcomes. Evaluate several older cycles,
holding out entire cycles when fitting model parameters or combination weights.
Use the same horizon and event set for every baseline. Historical outcome data
is available from the [MIT Election Lab](https://electionlab.mit.edu/data);
timestamped historical forecasts and polling vintages must be sourced separately.

`research.evaluate` computes Brier score, log loss and reliability bins, and
rejects obvious timestamp leakage and duplicate event/model observations.
Bootstrap whole election cycles or correlated clusters when estimating score
uncertainty; individual races are not independent replications. Avoid tuning
until the same held-out sample looks good.

For trading, replay quotes, sizes, latency, partial fills and fees. For market
making, count queue ahead of our orders and measure post-fill price movement.
A price touching our limit does not prove a fill. The current snapshots are
not a maker backtest and do not measure fill probabilities. Start collecting
these observations after the contest opens.

The missing ingredients for claiming accurate probabilities are archived,
timestamped training/validation inputs and demonstrated out-of-sample results.
The code now supports the measurement and basic models; it does not manufacture
that evidence.
