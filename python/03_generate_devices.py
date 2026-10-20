"""
03_generate_devices.py
Generates customer devices for the dim_device table (PostgreSQL, database fraud_project).
Requires: data/dim_customer.csv (run 01_generate_customers.py first)
Output: data/dim_device.csv
Run from the project root: python python/03_generate_devices.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
PERIOD_END = pd.Timestamp("2026-06-30 23:59:59")   # end of the transaction period

rng = np.random.default_rng(SEED)
data_dir = Path(__file__).resolve().parent.parent / "data"   # <project>/data

customers = pd.read_csv(data_dir / "dim_customer.csv", parse_dates=["signup_date"])
n = len(customers)

# Devices per customer: most have 1, some 2 or 3
n_devices = rng.choice([1, 2, 3], n, p=[0.65, 0.27, 0.08])
devices = customers.loc[customers.index.repeat(n_devices), ["customer_id", "country", "signup_date"]].reset_index(drop=True)
devices["device_no"] = devices.groupby("customer_id").cumcount()   # 0 = first (primary) device

# Device country: usually the customer's country, ~3% of devices registered in another country
other_countries = ["PL", "GB", "DE", "FR", "ES", "IT", "RO", "LT", "IE", "NL", "US", "AE"]
foreign = rng.random(len(devices)) < 0.03
devices["device_country"] = np.where(foreign, rng.choice(other_countries, len(devices)), devices["country"])

# first_seen: primary device = signup day (+ random time of day),
# additional devices = random moment between signup and the end of the period
span_sec = (PERIOD_END - devices["signup_date"]).dt.total_seconds().to_numpy()
offset_sec = np.where(
    devices["device_no"] == 0,
    rng.uniform(0, 86_400, len(devices)),          # within the first day
    rng.uniform(0, 1, len(devices)) * span_sec,    # any time later
)
devices["first_seen"] = devices["signup_date"] + pd.to_timedelta(offset_sec, unit="s")
devices["first_seen"] = devices["first_seen"].clip(upper=PERIOD_END)

# last_seen: most devices stay active until the end of the period,
# ~20% of additional (non-primary) devices stopped being used earlier
retired = (devices["device_no"] > 0) & (rng.random(len(devices)) < 0.20)
active_sec = (PERIOD_END - devices["first_seen"]).dt.total_seconds().to_numpy()
devices["last_seen"] = np.where(
    retired,
    devices["first_seen"] + pd.to_timedelta(rng.uniform(0, 1, len(devices)) * active_sec, unit="s"),
    PERIOD_END,
)
devices["last_seen"] = pd.to_datetime(devices["last_seen"])

devices["first_seen"] = devices["first_seen"].dt.floor("s")
devices["last_seen"] = devices["last_seen"].dt.floor("s")
n_foreign = int((devices["device_country"] != devices["country"]).sum())
devices.insert(0, "device_id", np.arange(1, len(devices) + 1))
devices = devices[["device_id", "customer_id", "device_country", "first_seen", "last_seen"]]

devices.to_csv(data_dir / "dim_device.csv", index=False)

# Short summary for checking
print(f"Saved {len(devices)} devices to {data_dir / 'dim_device.csv'}")
print(devices.head(), "\n")
print("Devices per customer:\n", devices.groupby("customer_id").size().value_counts().sort_index(), "\n")
print("Devices in a different country than the customer:", n_foreign)
print("Check: first_seen <= last_seen for all devices:", bool((devices["first_seen"] <= devices["last_seen"]).all()))
