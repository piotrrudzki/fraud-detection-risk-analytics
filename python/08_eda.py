"""
08_eda.py
Exploratory data analysis (EDA) in pandas, section 11 of the plan, part 1.
Reads the data straight from PostgreSQL (database fraud_project), prints the checks
in the terminal and saves charts as PNG files to charts/ (folder in the project root).

Requires: pip install matplotlib   (pandas and psycopg are already installed)
Run from the project root: python python/08_eda.py
"""
import getpass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                     # draw to files, no window needed
import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = {"host": "localhost", "port": 5432, "dbname": "fraud_project", "user": "postgres"}

charts_dir = Path(__file__).resolve().parent.parent / "charts"   # <project>/charts
charts_dir.mkdir(exist_ok=True)

# One row per transaction, with merchant category, customer plan and the amount in EUR.
# ::float8 turns NUMERIC into a normal float (otherwise pandas gets Python Decimal objects).
QUERY = """
SELECT t.transaction_id, t.customer_id, t.tx_datetime, t.amount::float8 AS amount, t.currency,
       t.country, t.is_fraud,
       m.merchant_category, c.plan, c.country AS customer_country,
       (t.amount * fx.eur_rate)::float8 AS amount_eur
FROM fact_transaction t
JOIN dim_merchant m USING (merchant_id)
JOIN dim_customer c USING (customer_id)
JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
"""

password = getpass.getpass("Password for user postgres: ")
with psycopg.connect(**DB, password=password) as conn:
    cur = conn.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[col.name for col in cur.description])

# ------------------------------------------------------------
# 1. Basic checks: shape, types, missing values, duplicates
# ------------------------------------------------------------
print("\n=== 1. Basic checks ===")
print("Shape (rows, columns):", df.shape)
print("\nColumn types:\n", df.dtypes.to_string())
print("\nMissing values per column:\n", df.isna().sum().to_string())
print("\nDuplicate rows:", int(df.duplicated().sum()))
print("Duplicate transaction_id:", int(df["transaction_id"].duplicated().sum()))

# ------------------------------------------------------------
# 2. Amount distribution (EUR)
# ------------------------------------------------------------
print("\n=== 2. Amount in EUR ===")
print(df["amount_eur"].describe(percentiles=[0.5, 0.9, 0.99, 0.999]).round(2).to_string())

# ------------------------------------------------------------
# 3. Normal vs fraud transactions
# ------------------------------------------------------------
print("\n=== 3. Normal vs fraud ===")
df["hour"] = df["tx_datetime"].dt.hour
df["abroad"] = df["country"] != df["customer_country"]
compare = df.groupby("is_fraud").agg(
    transactions=("transaction_id", "count"),
    avg_eur=("amount_eur", "mean"),
    median_eur=("amount_eur", "median"),
    p90_eur=("amount_eur", lambda s: s.quantile(0.9)),
    share_abroad_pct=("abroad", lambda s: 100 * s.mean()),
    share_night_pct=("hour", lambda s: 100 * s.between(0, 4).mean()),
).round(2)
print(compare.to_string())

# ------------------------------------------------------------
# 4. Fraud rate by country, merchant category and plan
# ------------------------------------------------------------
def fraud_rate(column):
    """Transactions, frauds and fraud rate (%) per value of one column, highest rate first."""
    out = df.groupby(column).agg(transactions=("is_fraud", "size"), frauds=("is_fraud", "sum"))
    out["fraud_rate_pct"] = (100 * out["frauds"] / out["transactions"]).round(2)
    return out.sort_values("fraud_rate_pct", ascending=False)

by_country = fraud_rate("country")
by_category = fraud_rate("merchant_category")
by_plan = fraud_rate("plan")
print("\n=== 4. Fraud rate by transaction country ===\n", by_country.to_string())
print("\n=== Fraud rate by merchant category ===\n", by_category.to_string())
print("\n=== Fraud rate by customer plan ===\n", by_plan.to_string())

# ------------------------------------------------------------
# 5. Charts (PNG files in charts/)
# ------------------------------------------------------------
BLUE, ORANGE = "#2a78d6", "#eb6834"       # normal = blue, fraud = orange (same colours on every chart)
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e5e4df"
plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
})


def bar_chart(table, title, file_name):
    """Horizontal bars of fraud rate, highest at the top, value written at the end of each bar."""
    data = table["fraud_rate_pct"].sort_values()
    fig, ax = plt.subplots(figsize=(8, 0.4 * len(data) + 1.2))
    ax.barh(data.index, data.values, color=BLUE, height=0.6)
    for y, value in enumerate(data.values):
        ax.text(value, y, f" {value:.2f}%", va="center", color=INK, fontsize=9)
    ax.set_title(title, loc="left", color=INK, fontsize=12)
    ax.set_xlabel("Fraud rate (%)")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(charts_dir / file_name, dpi=150)
    plt.close(fig)


bar_chart(by_category, "Fraud rate by merchant category", "01_fraud_rate_by_category.png")
bar_chart(by_country, "Fraud rate by transaction country", "02_fraud_rate_by_country.png")
bar_chart(by_plan, "Fraud rate by customer plan", "03_fraud_rate_by_plan.png")

# Amount distribution: normal vs fraud, as a share of each group (log scale, amounts differ a lot)
fig, ax = plt.subplots(figsize=(8, 4.5))
bins = [10 ** (x / 20) for x in range(0, 81)]            # 1 EUR ... 10,000 EUR, evenly on log scale
for flag, color, label in [(False, BLUE, "Normal"), (True, ORANGE, "Fraud")]:
    amounts = df.loc[df["is_fraud"] == flag, "amount_eur"]
    ax.hist(amounts, bins=bins, color=color, alpha=0.6, label=label,
            weights=[100 / len(amounts)] * len(amounts))
ax.set_xscale("log")
ax.set_title("Transaction amount: normal vs fraud", loc="left", color=INK, fontsize=12)
ax.set_xlabel("Amount in EUR (log scale)")
ax.set_ylabel("% of transactions in the group")
ax.legend(frameon=False)
ax.grid(axis="y", color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
fig.tight_layout()
fig.savefig(charts_dir / "04_amount_normal_vs_fraud.png", dpi=150)
plt.close(fig)

# Fraud rate by hour of day
by_hour = df.groupby("hour")["is_fraud"].mean() * 100
fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(by_hour.index, by_hour.values, color=BLUE, linewidth=2, marker="o", markersize=4)
ax.set_title("Fraud rate by hour of day", loc="left", color=INK, fontsize=12)
ax.set_xlabel("Hour")
ax.set_ylabel("Fraud rate (%)")
ax.set_xticks(range(0, 24, 2))
ax.set_ylim(bottom=0)
ax.grid(axis="y", color=GRID, linewidth=0.8)
fig.tight_layout()
fig.savefig(charts_dir / "05_fraud_rate_by_hour.png", dpi=150)
plt.close(fig)

print(f"\nSaved 5 charts to {charts_dir}")
