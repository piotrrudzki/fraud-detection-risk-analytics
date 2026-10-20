"""
07_generate_customer_history.py
Generates each customer's fraud / chargeback history from BEFORE the analysed period
for the fact_customer_risk table (PostgreSQL, database fraud_project).
  previous_fraud = the customer had a confirmed fraud case before 2026-01-01
  chargebacks    = number of chargebacks in the 12 months before 2026-01-01
risk_score and risk_level stay empty here: they are calculated later in SQL (04_risk_scoring.sql).

Requires: data/dim_customer.csv and data/fact_transaction.csv (run 01-05 first)
Output: data/fact_customer_risk.csv
Run from the project root: python python/07_generate_customer_history.py
Then reload the database: python python/06_load_to_postgres.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
PERIOD_START = pd.Timestamp("2026-01-01")

rng = np.random.default_rng(SEED + 7)          # own random stream, does not change the other data
data_dir = Path(__file__).resolve().parent.parent / "data"   # <project>/data

customers = pd.read_csv(data_dir / "dim_customer.csv", parse_dates=["signup_date"])
tx = pd.read_csv(data_dir / "fact_transaction.csv", usecols=["customer_id", "is_fraud"])

# Customers who are fraud victims in the period are more often customers with a risky past
# (in real life repeat victims / weakly protected accounts). The link is deliberately weak,
# so the history signal helps the score but does not give the answer away.
fraud_in_period = tx.groupby("customer_id")["is_fraud"].any()
risky = customers["customer_id"].map(fraud_in_period).fillna(False).to_numpy(dtype=bool)

# Customers who opened the account during the period have no history before it
has_history = (customers["signup_date"] < PERIOD_START).to_numpy()

p_prev = np.where(risky, 0.12, 0.02)
previous_fraud = (rng.random(len(customers)) < p_prev) & has_history

lam = np.where(risky, 0.35, 0.05) + np.where(previous_fraud, 0.8, 0.0)
chargebacks = np.where(has_history, rng.poisson(lam), 0)

history = pd.DataFrame({
    "customer_id": customers["customer_id"],
    "previous_fraud": previous_fraud,
    "chargebacks": chargebacks,
})
history.to_csv(data_dir / "fact_customer_risk.csv", index=False)

# Short summary for checking
with_history = previous_fraud | (chargebacks > 0)
print(f"Saved {len(history)} customers to {data_dir / 'fact_customer_risk.csv'}")
print("Customers with previous fraud:      ", int(previous_fraud.sum()))
print("Customers with at least 1 chargeback:", int((chargebacks > 0).sum()))
print("Chargebacks per customer:\n", pd.Series(chargebacks).value_counts().sort_index().to_string())
print(f"Share with fraud in period: with history {risky[with_history].mean():.1%}, "
      f"without history {risky[~with_history].mean():.1%}")
