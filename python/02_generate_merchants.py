"""
02_generate_merchants.py
Generates synthetic merchants for the dim_merchant table (PostgreSQL, database fraud_project).
Output: data/dim_merchant.csv (data/ folder in the project root)
Run from the project root: python python/02_generate_merchants.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_MERCHANTS = 500

rng = np.random.default_rng(SEED)

# Categories: (share of merchants, base risk level)
categories = {
    "grocery":         (0.18, "low"),
    "restaurants":     (0.15, "low"),
    "transport":       (0.08, "low"),
    "online_shopping": (0.15, "medium"),
    "travel":          (0.08, "medium"),
    "gaming":          (0.07, "medium"),
    "cash_withdrawal": (0.06, "medium"),
    "electronics":     (0.10, "high"),
    "gift_cards":      (0.05, "high"),
    "crypto":          (0.08, "high"),
}
cat_names = list(categories)
cat_weights = [w for w, _ in categories.values()]

# Merchant countries: mostly Europe (same as customers) + non-EU countries.
# High-risk categories are more often registered outside Europe.
eu_countries = ["PL", "GB", "DE", "FR", "ES", "IT", "RO", "LT", "IE", "NL"]
eu_weights = [0.25, 0.18, 0.12, 0.10, 0.08, 0.08, 0.06, 0.05, 0.04, 0.04]
non_eu_countries = ["US", "CN", "AE", "SG", "TR"]

category = rng.choice(cat_names, N_MERCHANTS, p=cat_weights)
base_risk = np.array([categories[c][1] for c in category])

non_eu_prob = np.select([base_risk == "high", base_risk == "medium"], [0.35, 0.15], default=0.05)
is_non_eu = rng.random(N_MERCHANTS) < non_eu_prob
country = np.where(
    is_non_eu,
    rng.choice(non_eu_countries, N_MERCHANTS),
    rng.choice(eu_countries, N_MERCHANTS, p=eu_weights),
)

# Merchant risk level: base level from the category, +1 level for non-EU merchants,
# plus ~10% random adjustments up or down (so risk is not 1:1 with the category).
levels = ["low", "medium", "high"]
risk_idx = np.array([levels.index(r) for r in base_risk]) + is_non_eu.astype(int)
noise = rng.choice([-1, 0, 1], N_MERCHANTS, p=[0.05, 0.90, 0.05])
risk_idx = np.clip(risk_idx + noise, 0, 2)

merchants = pd.DataFrame({
    "merchant_id": np.arange(1, N_MERCHANTS + 1),
    "merchant_category": category,
    "country": country,
    "merchant_risk_category": [levels[i] for i in risk_idx],
})

out_dir = Path(__file__).resolve().parent.parent / "data"   # <project>/data
out_dir.mkdir(exist_ok=True)
merchants.to_csv(out_dir / "dim_merchant.csv", index=False)

# Short summary for checking
print(f"Saved {len(merchants)} merchants to {out_dir / 'dim_merchant.csv'}")
print(merchants.head(), "\n")
print("Categories:\n", merchants["merchant_category"].value_counts(), "\n")
print("Risk vs category:\n", pd.crosstab(merchants["merchant_category"], merchants["merchant_risk_category"]), "\n")
print("Non-EU merchants:", int(is_non_eu.sum()))
