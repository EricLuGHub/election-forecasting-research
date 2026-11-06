"""One-shot account tape: fills (8h/24h), positions, orders, PnL."""
import json
from datetime import datetime, timedelta, timezone
from research.client import Client

c = Client()
now = datetime.now(timezone.utc)
f = c.get("/tournaments/midterm-elections/portfolio/fills", limit=100)
rows = f.get("data", f) if isinstance(f, dict) else f
rows = rows if isinstance(rows, list) else []
for hours in (8, 24):
    cut = now - timedelta(hours=hours)
    recent = [r for r in rows if r.get("filledAt", "") > cut.isoformat()]
    print(f"fills last {hours}h: {len(recent)}")
for r in rows[:12]:
    print("  ", r.get("filledAt"), r.get("exchangeId"), r.get("side"),
          r.get("quantity"), r.get("price"))
p = c.get("/tournaments/midterm-elections/portfolio/pnl")
print("pnl:", round(p.get("periodPnl", 0), 2),
      "acct:", round(p.get("totalAccountValue", 0), 2))
pos = c.get("/tournaments/midterm-elections/portfolio/positions").get("positions", [])
print("positions:", len(pos), "uPnl:",
      round(sum(x.get("unrealizedPnl", 0) for x in pos), 2))
o = c.get("/orders", status="open", limit=100)
rows2 = o.get("data", o) if isinstance(o, dict) else o
print("open orders:", len(rows2) if isinstance(rows2, list) else rows2)
