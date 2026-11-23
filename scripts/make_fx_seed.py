"""Write dbt_project/seeds/fx_rates.csv: synthetic business-day USD->CAD rates (seeded random walk).

The values are made up for the demo. In production this table would come from a rates feed.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

rng = random.Random(2025)
d, end = date(2024, 12, 31), date(2026, 7, 31)
rate = 1.36
out = Path(__file__).resolve().parent.parent / "dbt_project" / "seeds" / "fx_rates.csv"
with open(out, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["rate_date", "currency", "cad_per_unit"])
    while d <= end:
        if d.weekday() < 5:
            rate = min(1.46, max(1.30, rate + rng.gauss(0, 0.0035) + (1.37 - rate) * 0.02))
            w.writerow([d.isoformat(), "USD", f"{rate:.6f}"])
        d += timedelta(days=1)
