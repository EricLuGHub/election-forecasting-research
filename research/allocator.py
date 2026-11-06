"""Capital allocator across Engine1-6. Conservative by design.

Scores each engine on attributed realized performance: net PnL marked to
executable liquidation, divided by capital-days deployed. Weights shift toward
winners subject to: a floor per engine (keeps probing so a dead edge can prove
revival, and lets shadow engines audition on paper), a cap per engine (no
single-engine dominance), per-cycle change limits (hysteresis against noise), a
drawdown brake (halt an engine on sustained loss with cooldown), and a
late-tournament rank override hook (prize gaps, applied by the caller, not here).

Ledger lives in data/engine_ledger.json (git-ignored). Live weights stay zero
until the competition gate opens AND an engine has live (not paper) history.
"""
import json
from pathlib import Path
from .client import ROOT

ENGINES = ('E1', 'E2', 'E3', 'E4', 'E5', 'E6')
SHADOW_ONLY = frozenset({'E6'})


class Allocator:
    def __init__(self, floor=0.05, cap=0.40, max_shift=0.10,
                 drawdown_halt=-500.0, cooldown_cycles=20,
                 ledger_path=None):
        self.floor = floor
        self.cap = cap
        self.max_shift = max_shift
        self.drawdown_halt = drawdown_halt
        self.cooldown_cycles = cooldown_cycles
        self.ledger_path = Path(ledger_path or ROOT / 'data/engine_ledger.json')
        self.weights = {e: 1.0 / len(ENGINES) for e in ENGINES}
        self.cycle = 0
        self.cooldown = {e: 0 for e in ENGINES}
        self.live_open = False
        self.live_weights = {e: 0.0 for e in ENGINES}

    def record(self, engine, pnl, capital_days):
        """Append attributed performance; returns nothing. Caller persists."""
        ledger = self._load()
        ledger.setdefault(engine, []).append(
            {'cycle': self.cycle, 'pnl': pnl, 'capital_days': capital_days})
        self._save(ledger)

    def score(self, engine):
        rows = self._load().get(engine, [])
        pnl = sum(r['pnl'] for r in rows[-50:])
        days = sum(r['capital_days'] for r in rows[-50:]) or 1.0
        return pnl / days

    def update(self):
        """Recompute weights from scores with floor/cap/hysteresis/brake."""
        self.cycle += 1
        scores = {e: self.score(e) for e in ENGINES}
        for e in ENGINES:
            rows = self._load().get(e, [])
            recent = sum(r['pnl'] for r in rows[-20:])
            if recent < self.drawdown_halt:
                self.cooldown[e] = self.cooldown_cycles
        for e in ENGINES:
            if self.cooldown[e] > 0:
                self.cooldown[e] -= 1
        active = [e for e in ENGINES if self.cooldown[e] == 0]
        total = sum(max(0.0, scores[e]) for e in active) or 1.0
        target = {}
        for e in ENGINES:
            if e not in active:
                target[e] = self.floor
            else:
                raw = max(0.0, scores[e]) / total
                target[e] = self.floor + (1 - len(ENGINES) * self.floor) * raw
        for e in ENGINES:
            t = min(max(target[e], self.floor), self.cap)
            w = self.weights[e]
            shift = max(-self.max_shift, min(self.max_shift, t - w))
            self.weights[e] = round(w + shift, 4)
        if not self.live_open:
            self.live_weights = {e: 0.0 for e in ENGINES}
        else:
            self.live_weights = {e: (0.0 if e in SHADOW_ONLY else w) for e, w in self.weights.items()}
        return dict(self.weights)

    def allocate(self, total_capital):
        base = self.live_weights if self.live_open else {e: 0.0 for e in ENGINES}
        return {e: round(total_capital * base.get(e, 0.0), 2) for e in ENGINES}

    def _load(self):
        if self.ledger_path.exists():
            return json.loads(self.ledger_path.read_text())
        return {}

    def _save(self, ledger):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
