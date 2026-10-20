"""
04_generate_fx_rates.py
Generates daily exchange rates for the dim_fx_rate table (PostgreSQL, database fraud_project).
eur_rate = price of 1 unit of the currency in EUR, so: amount_in_eur = amount * eur_rate.
Rates are synthetic (approximate level + random daily moves), not real market quotes.
Output: data/dim_fx_rate.csv
Run from the project root: python python/04_generate_fx_rates.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
dates = pd.date_range("2026-01-01", "2026-06-30", freq="D")   # transaction period

rng = np.random.default_rng(SEED)

# Currencies used in transactions: (approximate starting rate in EUR, daily volatility, daily drift)
currencies = {
    "EUR": (1.0,    0.0,    0.0),
    "PLN": (0.235,  0.003,  0.0),
    "GBP": (1.17,   0.003,  0.0),
    "RON": (0.20,   0.002,  0.0),
    "USD": (0.92,   0.004,  0.0),
    "CNY": (0.127,  0.003,  0.0),
    "AED": (0.25,   0.004,  0.0),
    "SGD": (0.68,   0.003,  0.0),
    "TRY": (0.026,  0.006, -0.0008),   # Turkish lira: gradual depreciation
}

rows = []
for cur, (start, vol, drift) in currencies.items():
    # Random walk: each day = previous day * (1 + drift + random change)
    changes = 1 + drift + rng.normal(0, vol, len(dates))
    changes[0] = 1
    rates = start * np.cumprod(changes)
    rows.append(pd.DataFrame({"rate_date": dates.date, "currency": cur, "eur_rate": rates.round(6)}))

fx = pd.concat(rows, ignore_index=True)

data_dir = Path(__file__).resolve().parent.parent / "data"   # <project>/data
data_dir.mkdir(exist_ok=True)
fx.to_csv(data_dir / "dim_fx_rate.csv", index=False)

# Short summary for checking
print(f"Saved {len(fx)} rates ({len(currencies)} currencies x {len(dates)} days) to {data_dir / 'dim_fx_rate.csv'}")
print(fx.groupby("currency")["eur_rate"].agg(["first", "min", "max", "last"]).round(4))
