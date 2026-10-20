"""
01_generate_customers.py
Generates synthetic customers for the dim_customer table (PostgreSQL, database fraud_project).
Output: data/dim_customer.csv (data/ folder in the project root)
Run from the project root: python python/01_generate_customers.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42                                    # fixed seed = the same data on every run
N_CUSTOMERS = 10_000
REFERENCE_DATE = pd.Timestamp("2026-06-30")  # end of the transaction period (6 months: 2026-01-01 – 2026-06-30)

rng = np.random.default_rng(SEED)

# Customer countries with weights (sum = 1)
countries = ["PL", "GB", "DE", "FR", "ES", "IT", "RO", "LT", "IE", "NL"]
country_w = [0.25, 0.18, 0.12, 0.10, 0.08, 0.08, 0.06, 0.05, 0.04, 0.04]

# Account plans with weights
plans = ["standard", "plus", "premium", "metal"]
plan_w = [0.60, 0.20, 0.13, 0.07]

# Age: most customers 25–45, clipped to 18–80
age = np.clip(rng.normal(36, 11, N_CUSTOMERS).round(), 18, 80).astype(int)

# Signup date: from 2020-01-01 to the end of the period.
# About 8% of customers open the account during the transaction period (new accounts are a risk signal).
start_old, start_new = pd.Timestamp("2020-01-01"), pd.Timestamp("2026-01-01")
is_new = rng.random(N_CUSTOMERS) < 0.08
days_old = rng.integers(0, (start_new - start_old).days, N_CUSTOMERS)
days_new = rng.integers(0, (REFERENCE_DATE - start_new).days + 1, N_CUSTOMERS)
signup_date = np.where(
    is_new,
    start_new + pd.to_timedelta(days_new, unit="D"),
    start_old + pd.to_timedelta(days_old, unit="D"),
)
signup_date = pd.to_datetime(signup_date)

customers = pd.DataFrame({
    "customer_id": np.arange(1, N_CUSTOMERS + 1),
    "country": rng.choice(countries, N_CUSTOMERS, p=country_w),
    "age": age,
    "signup_date": signup_date.date,
    "plan": rng.choice(plans, N_CUSTOMERS, p=plan_w),
    "account_age_days": (REFERENCE_DATE - signup_date).days,
})

out_dir = Path(__file__).resolve().parent.parent / "data"   # <project>/data
out_dir.mkdir(exist_ok=True)
customers.to_csv(out_dir / "dim_customer.csv", index=False)

# Short summary for checking
print(f"Saved {len(customers)} customers to {out_dir / 'dim_customer.csv'}")
print(customers.head(), "\n")
print("Countries:\n", customers["country"].value_counts(normalize=True).round(3), "\n")
print("Plans:\n", customers["plan"].value_counts(normalize=True).round(3), "\n")
print("Age: min", customers["age"].min(), "| mean", round(customers["age"].mean(), 1), "| max", customers["age"].max())
print("New accounts (opened during the transaction period):", int(is_new.sum()))
