"""
05_generate_transactions.py
Generates transactions for the fact_transaction table (PostgreSQL, database fraud_project),
including controlled fraud cases and legitimate transactions that look suspicious
(the source of false positives).

Requires files from the previous steps: data/dim_customer.csv, dim_merchant.csv, dim_device.csv, dim_fx_rate.csv
Output:  data/fact_transaction.csv
         data/dim_device.csv       (overwritten: devices used by fraudsters are appended)
         data/dim_device_base.csv  (copy of the devices from step 03, so this script can be re-run safely)
If you re-run 03_generate_devices.py, delete data/dim_device_base.csv first.
Run from the project root: python python/05_generate_transactions.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_NORMAL_TX = 250_000                       # target number of normal transactions
PERIOD_START = pd.Timestamp("2026-01-01")
PERIOD_END = pd.Timestamp("2026-06-30 23:59:59")

rng = np.random.default_rng(SEED)
data_dir = Path(__file__).resolve().parent.parent / "data"   # <project>/data

customers = pd.read_csv(data_dir / "dim_customer.csv", parse_dates=["signup_date"])
merchants = pd.read_csv(data_dir / "dim_merchant.csv")
# On the first run keep a copy of the devices from step 03 (dim_device_base.csv),
# so that later runs do not append the fraud devices a second time.
base_path = data_dir / "dim_device_base.csv"
if not base_path.exists():
    pd.read_csv(data_dir / "dim_device.csv").to_csv(base_path, index=False)
devices = pd.read_csv(base_path, parse_dates=["first_seen", "last_seen"])
fx = pd.read_csv(data_dir / "dim_fx_rate.csv", parse_dates=["rate_date"])

# The currency follows the merchant's country
CURRENCY = {"PL": "PLN", "GB": "GBP", "RO": "RON", "US": "USD", "CN": "CNY",
            "AE": "AED", "SG": "SGD", "TR": "TRY"}            # all other countries = EUR
merchants["currency"] = merchants["country"].map(CURRENCY).fillna("EUR")

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def random_times(start, end, size):
    """Random moments between start and end (arrays), more often during the day than at night."""
    start = pd.to_datetime(start).to_numpy()
    end = pd.to_datetime(end).to_numpy()
    t = start + ((end - start) * rng.random(size))
    t = pd.to_datetime(t)
    # hour of day: daily profile peaking around 13-19, few transactions at night
    hour_w = np.array([1, 0.5, 0.3, 0.3, 0.4, 0.8, 2, 4, 6, 7, 8, 9,
                       10, 10, 9, 9, 9, 10, 10, 9, 7, 5, 3, 2], dtype=float)
    hours = rng.choice(24, size, p=hour_w / hour_w.sum())
    t = t.normalize() + pd.to_timedelta(hours, unit="h") + pd.to_timedelta(rng.integers(0, 3600, size), unit="s")
    return pd.Series(t).clip(lower=pd.Series(pd.to_datetime(start)), upper=pd.Series(pd.to_datetime(end)))


def pick_merchants_fast(categories, cust_country, foreign_share=0.12):
    """For each transaction picks a merchant from the given category: usually from the customer's country, sometimes abroad."""
    out = np.empty(len(categories), dtype=int)
    want_foreign = rng.random(len(categories)) < foreign_share
    df = pd.DataFrame({"cat": categories, "cc": cust_country, "foreign": want_foreign})
    for (cat, cc, foreign), g in df.groupby(["cat", "cc", "foreign"]):
        pool = merchants[merchants["merchant_category"] == cat]
        local = pool[pool["country"] == cc]
        src = pool if (foreign or local.empty) else local
        ids = src["merchant_id"].to_numpy()
        out[g.index.to_numpy()] = ids[rng.integers(len(ids), size=len(g))]
    return out


def to_local_amount(amount_eur, merchant_ids, times):
    """Converts an amount from EUR to the merchant's currency at the rate of the transaction day."""
    cur = merchants.set_index("merchant_id").loc[merchant_ids, "currency"].to_numpy()
    key = pd.DataFrame({"rate_date": pd.to_datetime(times).dt.normalize().to_numpy(), "currency": cur})
    rate = key.merge(fx, on=["rate_date", "currency"], how="left")["eur_rate"].to_numpy()
    return np.round(amount_eur / rate, 2), cur


# ---------------------------------------------------------------------------
# 1. Normal transactions
# ---------------------------------------------------------------------------
# Customer activity: most make a few transactions per month, a small group makes a lot
activity = rng.lognormal(0, 0.9, len(customers))
active_from = customers["signup_date"].clip(lower=PERIOD_START)   # from signup or from the start of the period
active_share = ((PERIOD_END - active_from).dt.total_seconds() / (PERIOD_END - PERIOD_START).total_seconds()).clip(0, 1)
expected = activity * active_share
n_tx = rng.poisson(expected / expected.sum() * N_NORMAL_TX)

# Average customer amount in EUR: usually 30-150
cust_avg = np.clip(rng.lognormal(np.log(60), 0.45, len(customers)), 15, 250)

tx_cust_idx = np.repeat(np.arange(len(customers)), n_tx)
n = len(tx_cust_idx)
tx_customer = customers["customer_id"].to_numpy()[tx_cust_idx]
tx_cust_country = customers["country"].to_numpy()[tx_cust_idx]
tx_time = random_times(active_from.to_numpy()[tx_cust_idx], np.full(n, PERIOD_END), n)

# Categories for normal purchases: (share, amount multiplier relative to the customer's average)
normal_cats = {"grocery": (0.28, 0.6), "restaurants": (0.18, 0.7), "transport": (0.12, 0.4),
               "online_shopping": (0.17, 1.3), "travel": (0.04, 3.0), "gaming": (0.05, 0.6),
               "cash_withdrawal": (0.06, 1.5), "electronics": (0.05, 3.0), "gift_cards": (0.03, 1.0),
               "crypto": (0.02, 2.0)}
cat_list = list(normal_cats)
tx_cat = rng.choice(cat_list, n, p=[v[0] for v in normal_cats.values()])
mult = np.array([normal_cats[c][1] for c in tx_cat])
tx_amount_eur = np.round(np.clip(cust_avg[tx_cust_idx] * mult * rng.lognormal(0, 0.5, n), 1, 1500), 2)
tx_merchant = pick_merchants_fast(tx_cat, tx_cust_country)

# Device: random one of the customer's devices active at the time of the transaction, otherwise the primary one
devices = devices.sort_values(["customer_id", "device_id"]).reset_index(drop=True)   # lowest device_id = primary device
dev_first_idx = devices.groupby("customer_id").cumcount() == 0
primary = devices[dev_first_idx].set_index("customer_id")["device_id"]
dev_start = devices.reset_index().groupby("customer_id")["index"].min()
dev_count = devices.groupby("customer_id").size()
k = (rng.random(n) * dev_count.loc[tx_customer].to_numpy()).astype(int)
cand = dev_start.loc[tx_customer].to_numpy() + k
cand_ok = ((devices["first_seen"].to_numpy()[cand] <= tx_time.to_numpy())
           & (devices["last_seen"].to_numpy()[cand] >= tx_time.to_numpy()))
tx_device = np.where(cand_ok, devices["device_id"].to_numpy()[cand], primary.loc[tx_customer].to_numpy())

normal = pd.DataFrame({"customer_id": tx_customer, "tx_datetime": tx_time.to_numpy(),
                       "amount_eur": tx_amount_eur, "merchant_id": tx_merchant,
                       "device_id": tx_device, "is_fraud": False, "scenario": "normal"})

# ---------------------------------------------------------------------------
# 2. Legitimate transactions that look suspicious (false positives)
# ---------------------------------------------------------------------------
legit_parts = []
foreign_countries = ["US", "AE", "TR", "SG", "CN", "ES", "IT", "FR", "GB", "DE"]

# 2a. Travel: ~3% of customers make a series of normal purchases abroad within one week
trav = customers.sample(frac=0.03, random_state=SEED)
for _, c in trav.iterrows():
    start = random_times([max(c["signup_date"], PERIOD_START)], [PERIOD_END - pd.Timedelta(days=7)], 1).iloc[0]
    k_tx = rng.integers(4, 12)
    dest = rng.choice([x for x in foreign_countries if x != c["country"]])
    pool = merchants[(merchants["country"] == dest) & merchants["merchant_category"].isin(
        ["restaurants", "transport", "travel", "grocery", "online_shopping", "electronics", "gaming"])]
    if pool.empty:
        pool = merchants[merchants["country"] == dest]
    times = start + pd.to_timedelta(np.sort(rng.uniform(0, 7 * 86400, k_tx)), unit="s")
    legit_parts.append(pd.DataFrame({
        "customer_id": c["customer_id"], "tx_datetime": times,
        "amount_eur": np.round(rng.lognormal(np.log(70), 0.6, k_tx), 2),
        "merchant_id": pool["merchant_id"].to_numpy()[rng.integers(len(pool), size=k_tx)],
        "device_id": primary.loc[c["customer_id"]], "is_fraud": False, "scenario": "legit_travel"}))

# 2b. Big but legitimate purchases (e.g. a laptop, holidays): ~4% of customers, one transaction of 800-2500 EUR
big = customers.sample(frac=0.04, random_state=SEED + 1)
pool = merchants[merchants["merchant_category"].isin(["electronics", "travel"])]
legit_parts.append(pd.DataFrame({
    "customer_id": big["customer_id"].to_numpy(),
    "tx_datetime": random_times(big["signup_date"].clip(lower=PERIOD_START).to_numpy(),
                                np.full(len(big), PERIOD_END), len(big)).to_numpy(),
    "amount_eur": np.round(rng.uniform(800, 2500, len(big)), 2),
    "merchant_id": pool["merchant_id"].to_numpy()[rng.integers(len(pool), size=len(big))],
    "device_id": primary.loc[big["customer_id"]].to_numpy(), "is_fraud": False, "scenario": "legit_big_purchase"}))

# ---------------------------------------------------------------------------
# 3. Fraud (several scenarios, often with several signals at once)
# ---------------------------------------------------------------------------
fraud_parts, new_devices = [], []
next_device_id = devices["device_id"].max() + 1
risky = merchants[merchants["merchant_category"].isin(["electronics", "gift_cards", "crypto"])]
risky_foreign = risky[~risky["country"].isin(["PL", "GB", "DE", "FR", "ES", "IT", "RO", "LT", "IE", "NL"])]
eligible = customers[customers["signup_date"] < PERIOD_END - pd.Timedelta(days=3)]

def new_fraud_device(cust_id, when, country):
    """Creates a new fraudster device (a new device is a strong risk signal)."""
    global next_device_id
    d = {"device_id": next_device_id, "customer_id": cust_id, "device_country": country,
         "first_seen": when, "last_seen": when + pd.Timedelta(hours=2)}
    next_device_id += 1
    new_devices.append(d)
    return d["device_id"]

# 3a. Account takeover: new device from another country + a burst of 5-15 transactions within 10-30 minutes
for _, c in eligible.sample(230, random_state=SEED + 2).iterrows():
    start = random_times([max(c["signup_date"], PERIOD_START)], [PERIOD_END - pd.Timedelta(hours=1)], 1).iloc[0]
    k_tx = rng.integers(5, 16)
    pool = risky_foreign if rng.random() < 0.7 else risky
    m = pool["merchant_id"].to_numpy()[rng.integers(len(pool), size=k_tx)]
    country = merchants.set_index("merchant_id").loc[m[0], "country"]
    dev = new_fraud_device(c["customer_id"], start, country)
    fraud_parts.append(pd.DataFrame({
        "customer_id": c["customer_id"],
        "tx_datetime": start + pd.to_timedelta(np.sort(rng.uniform(0, rng.uniform(600, 1800), k_tx)), unit="s"),
        "amount_eur": np.round(rng.uniform(150, 2000, k_tx), 2), "merchant_id": m,
        "device_id": dev, "is_fraud": True, "scenario": "fraud_account_takeover"}))

# 3b. Card testing: 10-20 tiny payments (1-5 EUR) within 10 minutes, then one big payment
for _, c in eligible.sample(60, random_state=SEED + 3).iterrows():
    start = random_times([max(c["signup_date"], PERIOD_START)], [PERIOD_END - pd.Timedelta(hours=1)], 1).iloc[0]
    k_tx = rng.integers(10, 21)
    pool = merchants[merchants["merchant_category"].isin(["online_shopping", "gaming", "gift_cards"])]
    m = pool["merchant_id"].to_numpy()[rng.integers(len(pool), size=k_tx + 1)]
    amounts = np.append(np.round(rng.uniform(1, 5, k_tx), 2), round(rng.uniform(500, 1500), 2))
    times = start + pd.to_timedelta(np.append(np.sort(rng.uniform(0, 600, k_tx)), 660), unit="s")
    dev = new_fraud_device(c["customer_id"], start, c["country"]) if rng.random() < 0.6 else primary.loc[c["customer_id"]]
    fraud_parts.append(pd.DataFrame({
        "customer_id": c["customer_id"], "tx_datetime": times, "amount_eur": amounts, "merchant_id": m,
        "device_id": dev, "is_fraud": True, "scenario": "fraud_card_testing"}))

# 3c. A single unusually high amount in a risky category, from a known device (only 1-2 signals)
single = eligible.sample(500, random_state=SEED + 4)
legit_like = rng.random(len(single)) < 0.5
pool = risky
fraud_parts.append(pd.DataFrame({
    "customer_id": single["customer_id"].to_numpy(),
    "tx_datetime": random_times(single["signup_date"].clip(lower=PERIOD_START).to_numpy(),
                                np.full(len(single), PERIOD_END), len(single)).to_numpy(),
    "amount_eur": np.round(np.where(legit_like, rng.uniform(300, 800, len(single)), rng.uniform(800, 2000, len(single))), 2),
    "merchant_id": pool["merchant_id"].to_numpy()[rng.integers(len(pool), size=len(single))],
    "device_id": primary.loc[single["customer_id"]].to_numpy(), "is_fraud": True, "scenario": "fraud_high_amount"}))

# 3d. New-account fraud: account opened during the period, crypto / gift card purchases within 1-5 days
new_acc = customers[(customers["signup_date"] >= PERIOD_START) & (customers["signup_date"] < PERIOD_END - pd.Timedelta(days=6))]
pool = merchants[merchants["merchant_category"].isin(["crypto", "gift_cards"])]
for _, c in new_acc.sample(min(80, len(new_acc)), random_state=SEED + 5).iterrows():
    k_tx = rng.integers(3, 9)
    times = c["signup_date"] + pd.Timedelta(days=1) + pd.to_timedelta(np.sort(rng.uniform(0, 4 * 86400, k_tx)), unit="s")
    fraud_parts.append(pd.DataFrame({
        "customer_id": c["customer_id"], "tx_datetime": times,
        "amount_eur": np.round(rng.uniform(200, 1500, k_tx), 2),
        "merchant_id": pool["merchant_id"].to_numpy()[rng.integers(len(pool), size=k_tx)],
        "device_id": primary.loc[c["customer_id"]], "is_fraud": True, "scenario": "fraud_new_account"}))

# ---------------------------------------------------------------------------
# 4. Combine, add currency and country, save
# ---------------------------------------------------------------------------
tx = pd.concat([normal, *legit_parts, *fraud_parts], ignore_index=True)
tx["tx_datetime"] = pd.to_datetime(tx["tx_datetime"]).dt.floor("s").clip(PERIOD_START, PERIOD_END)
# A transaction cannot happen before the device was first used (and therefore before customer signup)
all_first_seen = pd.concat([devices[["device_id", "first_seen"]], pd.DataFrame(new_devices)[["device_id", "first_seen"]]])
dev_first = all_first_seen.set_index("device_id")["first_seen"]
tx["tx_datetime"] = np.maximum(tx["tx_datetime"].to_numpy(), pd.to_datetime(dev_first.loc[tx["device_id"]]).dt.ceil("s").to_numpy())
tx = tx.sort_values("tx_datetime").reset_index(drop=True)
tx["amount"], tx["currency"] = to_local_amount(tx["amount_eur"].to_numpy(), tx["merchant_id"].to_numpy(), tx["tx_datetime"])
tx["country"] = merchants.set_index("merchant_id").loc[tx["merchant_id"], "country"].to_numpy()
tx.insert(0, "transaction_id", np.arange(1, len(tx) + 1))

out = tx[["transaction_id", "customer_id", "tx_datetime", "amount", "currency",
          "merchant_id", "device_id", "country", "is_fraud"]]
out.to_csv(data_dir / "fact_transaction.csv", index=False)

if new_devices:
    devices_all = pd.concat([devices, pd.DataFrame(new_devices)], ignore_index=True).sort_values("device_id")
    devices_all["first_seen"] = pd.to_datetime(devices_all["first_seen"]).dt.floor("s")
    devices_all["last_seen"] = pd.to_datetime(devices_all["last_seen"]).dt.floor("s")
    devices_all.to_csv(data_dir / "dim_device.csv", index=False)

# Short summary for checking
print(f"Saved {len(out):,} transactions to {data_dir / 'fact_transaction.csv'}")
print(f"Fraud: {int(out['is_fraud'].sum()):,} transactions ({out['is_fraud'].mean():.2%})")
print("\nScenarios (helper column, not loaded into the database):\n", tx["scenario"].value_counts())
print("\nCurrencies:\n", out["currency"].value_counts())
print("\nFraudster devices appended to dim_device.csv:", len(new_devices))
print("Check: no empty amounts:", bool(out["amount"].notna().all()))
