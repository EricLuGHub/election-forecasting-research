"""Engine5: chamber-vs-components aggregation (stub; needs joint simulator).

Until the correlated race simulator (FORECASTING.md section 5: shared national /
regional shocks + race-specific error, fitted on earlier cycles) exists and beats
the sum-of-parts baseline out of sample, this engine emits no intents. Single-race
probabilities do not determine chamber control; trading the gap without the joint
model is an unpriced correlation bet.
"""
from .base import Engine


class ChamberAggregation(Engine):
    name = 'chamber_aggregation'
    engine_id = 'E5'

    def quote(self, market_state):
        return []
