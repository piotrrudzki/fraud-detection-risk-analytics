"""
09_anomaly_detection.py
Section 11 of the plan, part 2: statistical anomaly detection (IQR, z-score),
a check how well the rule-based risk score matches is_fraud, and CSV export for Power BI.

Requires: risk_score_v2 columns in fact_transaction_risk and fact_customer_risk (run sql/03_risk_scoring.sql and
sql/05_risk_score_v2.sql first) and pip install matplotlib.
Output: powerbi_data/transactions_scored.csv, powerbi_data/customers_risk.csv,
        charts/06_fraud_rate_by_risk_score.png  (folders in the project root)
Run from the project root: python python/09_anomaly_detection.py
"""
import getpass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = {"host": "localhost", "port": 5432, "dbname": "fraud_project", "user": "postgres"}

root = Path(__file__).resolve().parent.parent
charts_dir = root / "charts"
export_dir = root / "powerbi_data"
charts_dir.mkdir(exist_ok=True)
export_dir.mkdir(exist_ok=True)

TX_QUERY = """
SELECT r.transaction_id, r.customer_id, r.tx_datetime, r.amount_eur::float8 AS amount_eur, r.is_fraud,
       t.country, t.currency, m.merchant_category,
       r.s_amount_3x_avg, r.s_new_device, r.s_new_country, r.s_5_tx_in_10_min,
       r.s_risky_category, r.s_fraud_history, r.s_night_hour,
       r.risk_score, r.risk_level, r.risk_score_v2, r.risk_level_v2
FROM fact_transaction_risk r
JOIN fact_transaction t USING (transaction_id)
JOIN dim_merchant m USING (merchant_id)
"""
CUSTOMER_QUERY = """
SELECT c.customer_id, c.country, c.age, c.plan, c.signup_date,
       r.previous_fraud, r.chargebacks,
       r.risk_score::float8 AS risk_score, r.risk_level,
       r.risk_score_v2::float8 AS risk_score_v2, r.risk_level_v2
FROM dim_customer c
JOIN fact_customer_risk r USING (customer_id)
"""


def read_sql(conn, query):
    """Run a query and return the result as a pandas DataFrame."""
    cur = conn.execute(query)
    return pd.DataFrame(cur.fetchall(), columns=[col.name for col in cur.description])


password = getpass.getpass("Password for user postgres: ")
with psycopg.connect(**DB, password=password) as conn:
    tx = read_sql(conn, TX_QUERY)
    customers = read_sql(conn, CUSTOMER_QUERY)

# A signal that could not be calculated (e.g. no history before the 1st transaction) = off
signal_cols = [c for c in tx.columns if c.startswith("s_")]
tx[signal_cols] = tx[signal_cols].fillna(False).astype(bool)


def evaluate(flag, name):
    """Compare a True/False flag with is_fraud: how many flagged, precision and recall."""
    tp = int((flag & tx["is_fraud"]).sum())
    flagged = int(flag.sum())
    return {
        "method": name,
        "flagged": flagged,
        "fraud_caught": tp,
        "precision_pct": round(100 * tp / flagged, 1) if flagged else 0.0,
        "recall_pct": round(100 * tp / int(tx["is_fraud"].sum()), 1),
    }


# ------------------------------------------------------------
# 1. IQR on the amount (one threshold for everybody)
#    outlier = amount above Q3 + 1.5 * IQR, where IQR = Q3 - Q1
# ------------------------------------------------------------
q1, q3 = tx["amount_eur"].quantile([0.25, 0.75])
iqr_limit = q3 + 1.5 * (q3 - q1)
tx["iqr_outlier"] = tx["amount_eur"] > iqr_limit
print(f"\n=== 1. IQR: Q1 = {q1:.2f}, Q3 = {q3:.2f}, upper limit = {iqr_limit:.2f} EUR ===")

# ------------------------------------------------------------
# 2. z-score per customer: how many standard deviations the amount is
#    above the customer's own average (only customers with at least 5 transactions)
# ------------------------------------------------------------
per_customer = tx.groupby("customer_id")["amount_eur"]
tx["customer_mean"] = per_customer.transform("mean")
tx["customer_std"] = per_customer.transform("std")
tx["customer_tx"] = per_customer.transform("count")
tx["z_score"] = (tx["amount_eur"] - tx["customer_mean"]) / tx["customer_std"]
tx["z_outlier"] = (tx["customer_tx"] >= 5) & (tx["z_score"] > 3)
print("=== 2. z-score: outlier = amount more than 3 std above the customer's average ===")

# ------------------------------------------------------------
# 3. Statistics vs rules: which method finds fraud best?
# ------------------------------------------------------------
results = pd.DataFrame([
    evaluate(tx["iqr_outlier"], "IQR on amount (global)"),
    evaluate(tx["z_outlier"], "z-score > 3 (per customer)"),
    evaluate(tx["risk_score"] >= 60, "risk score v1 >= 60"),
    evaluate(tx["risk_score_v2"] >= 60, "risk score v2 >= 60"),
    evaluate(tx["risk_score_v2"] >= 50, "risk score v2 >= 50"),
])
print("\n=== 3. Methods compared with is_fraud ===")
print(results.to_string(index=False))

# ------------------------------------------------------------
# 4. Do the single rules correlate with is_fraud?
#    lift = fraud rate when the signal is on / overall fraud rate
# ------------------------------------------------------------
base_rate = tx["is_fraud"].mean()
rows = []
for col in signal_cols:
    on = tx[col]
    rows.append({
        "signal": col,
        "tx_with_signal": int(on.sum()),
        "fraud_rate_on_pct": round(100 * tx.loc[on, "is_fraud"].mean(), 2),
        "fraud_rate_off_pct": round(100 * tx.loc[~on, "is_fraud"].mean(), 2),
        "lift": round(tx.loc[on, "is_fraud"].mean() / base_rate, 1),
        "correlation": round(on.astype(int).corr(tx["is_fraud"].astype(int)), 3),
    })
signals = pd.DataFrame(rows).sort_values("lift", ascending=False)
print("\n=== 4. Single rules vs is_fraud ===")
print(signals.to_string(index=False))
print("\nCorrelation of the whole score with is_fraud:",
      f"v1 = {tx['risk_score'].corr(tx['is_fraud'].astype(int)):.3f},",
      f"v2 = {tx['risk_score_v2'].corr(tx['is_fraud'].astype(int)):.3f}")

# ------------------------------------------------------------
# 5. Chart: fraud rate for each value of risk_score_v2
# ------------------------------------------------------------
by_score = tx.groupby("risk_score_v2").agg(transactions=("is_fraud", "size"), fraud_rate=("is_fraud", "mean"))
by_score = by_score[by_score["transactions"] >= 30]          # skip scores with very few transactions
BLUE, INK, MUTED, GRID = "#2a78d6", "#0b0b0b", "#52514e", "#e5e4df"
plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
})
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.bar(by_score.index, 100 * by_score["fraud_rate"], width=3.5, color=BLUE)
for level_start, label in [(30, "MEDIUM"), (60, "HIGH"), (80, "CRITICAL")]:
    ax.axvline(level_start - 2.5, color=MUTED, linewidth=0.8, linestyle="--")
    ax.text(level_start - 1.5, 102, label, color=MUTED, fontsize=8)
ax.set_title("Fraud rate by risk score (v2)", loc="left", color=INK, fontsize=12, pad=18)
ax.set_xlabel("Risk score v2 (scores with at least 30 transactions)")
ax.set_ylabel("Fraud rate (%)")
ax.set_ylim(0, 100)
ax.grid(axis="y", color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
fig.tight_layout()
fig.savefig(charts_dir / "06_fraud_rate_by_risk_score.png", dpi=150)
plt.close(fig)

# ------------------------------------------------------------
# 6. Export for Power BI
# ------------------------------------------------------------
export_cols = ["transaction_id", "customer_id", "tx_datetime", "amount_eur", "country", "currency",
               "merchant_category", "is_fraud", *signal_cols, "risk_score", "risk_level",
               "risk_score_v2", "risk_level_v2", "iqr_outlier", "z_score", "z_outlier"]
tx_out = tx[export_cols].sort_values("transaction_id")
tx_out["amount_eur"] = tx_out["amount_eur"].round(2)
tx_out["z_score"] = tx_out["z_score"].round(2)
tx_out.to_csv(export_dir / "transactions_scored.csv", index=False)
customers.sort_values("customer_id").to_csv(export_dir / "customers_risk.csv", index=False)

print(f"\nSaved chart to {charts_dir / '06_fraud_rate_by_risk_score.png'}")
print(f"Saved {len(tx_out):,} transactions to {export_dir / 'transactions_scored.csv'}")
print(f"Saved {len(customers):,} customers to {export_dir / 'customers_risk.csv'}")
