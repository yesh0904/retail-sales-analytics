"""
generate_data.py
Creates data/raw_sales.csv - a SYNTHETIC retail orders dataset (2023-2025).

NOTE: This data is simulated for demonstration. The analysis pipeline works on any
dataset with the same columns, so you can replace data/raw_sales.csv with a real
dataset (e.g. Kaggle "Superstore") and re-run analysis.py unchanged.

Messiness is injected on purpose (duplicates, missing values, inconsistent text,
bad dates, outliers) so the cleaning step is meaningful.
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
N_ORDERS = 6000

# ---------- Master data ----------
catalog = {
    "Technology": {"Phones": (300, 900), "Laptops": (600, 1800), "Accessories": (15, 120)},
    "Furniture": {"Chairs": (80, 450), "Tables": (150, 900), "Bookcases": (90, 500)},
    "Office Supplies": {"Paper": (5, 40), "Binders": (4, 30), "Storage": (20, 150)},
}
margin = {  # base profit margin per sub-category
    "Phones": 0.22, "Laptops": 0.14, "Accessories": 0.35,
    "Chairs": 0.18, "Tables": 0.08, "Bookcases": 0.12,
    "Paper": 0.40, "Binders": 0.30, "Storage": 0.25,
}
regions = {
    "West": ["California", "Washington", "Oregon"],
    "East": ["New York", "Pennsylvania", "Massachusetts"],
    "Central": ["Texas", "Illinois", "Ohio"],
    "South": ["Florida", "Georgia", "North Carolina"],
}
region_w = {"West": 0.34, "East": 0.28, "Central": 0.20, "South": 0.18}
segments = ["Consumer", "Corporate", "Home Office"]
seg_w = [0.52, 0.30, 0.18]
ship_modes = ["Standard Class", "Second Class", "First Class", "Same Day"]
ship_w = [0.58, 0.20, 0.15, 0.07]

# ---------- Customers ----------
n_cust = 900
cust = pd.DataFrame({
    "customer_id": [f"C{1000+i}" for i in range(n_cust)],
    "customer_name": [f"Customer {i+1}" for i in range(n_cust)],
    "segment": rng.choice(segments, n_cust, p=seg_w),
})
cust["region"] = rng.choice(list(region_w), n_cust, p=list(region_w.values()))
cust["state"] = cust["region"].map(lambda r: rng.choice(regions[r]))
# repeat-buying propensity (heavy tail -> some loyal customers)
cust["weight"] = rng.pareto(2.2, n_cust) + 0.3
cust["weight"] /= cust["weight"].sum()

# ---------- Orders ----------
dates = pd.date_range("2023-01-01", "2025-12-31")
# seasonality: Nov/Dec peak, growth over time
month_boost = {1: .8, 2: .75, 3: .9, 4: .95, 5: 1.0, 6: 1.0, 7: .95, 8: 1.0, 9: 1.15, 10: 1.1, 11: 1.5, 12: 1.6}
day_w = np.array([month_boost[d.month] * (1 + 0.18 * (d.year - 2023)) for d in dates])
day_w /= day_w.sum()
order_dates = rng.choice(dates, N_ORDERS, p=day_w)

rows = []
prod_id = 0
for i in range(N_ORDERS):
    c = cust.iloc[rng.choice(n_cust, p=cust["weight"])]
    od = pd.Timestamp(order_dates[i])
    ship_mode = rng.choice(ship_modes, p=ship_w)
    lag = {"Same Day": 0, "First Class": 2, "Second Class": 3, "Standard Class": 5}[ship_mode] + int(rng.integers(0, 3))
    for _ in range(int(rng.choice([1, 2, 3, 4], p=[.5, .28, .15, .07]))):
        cat = rng.choice(list(catalog), p=[.30, .27, .43])
        sub = rng.choice(list(catalog[cat]))
        lo, hi = catalog[cat][sub]
        unit_price = round(float(rng.uniform(lo, hi)), 2)
        qty = int(rng.choice([1, 2, 3, 4, 5], p=[.40, .27, .17, .10, .06]))
        discount = float(rng.choice([0, .1, .2, .3, .4, .5], p=[.45, .15, .17, .12, .07, .04]))
        sales = round(unit_price * qty * (1 - discount), 2)
        # profit: base margin minus discount drag -> deep discounts lose money
        base = margin[sub] - discount * 0.75
        profit = round(sales * (base + rng.normal(0, 0.03)), 2)
        rows.append([
            f"ORD-{od.year}-{i+1:05d}", od, od + pd.Timedelta(days=lag), ship_mode,
            c.customer_id, c.customer_name, c.segment, c.region, c.state,
            f"P{prod_id % 400:04d}", cat, sub, unit_price, qty, discount, sales, profit,
        ])
        prod_id += 1

cols = ["order_id", "order_date", "ship_date", "ship_mode", "customer_id", "customer_name",
        "segment", "region", "state", "product_id", "category", "sub_category",
        "unit_price", "quantity", "discount", "sales", "profit"]
df = pd.DataFrame(rows, columns=cols)

# ---------- Inject data-quality problems ----------
df["order_date"] = df["order_date"].dt.strftime("%Y-%m-%d")
df["ship_date"] = df["ship_date"].dt.strftime("%Y-%m-%d")

# 1) exact duplicates
df = pd.concat([df, df.sample(60, random_state=1)], ignore_index=True)
# 2) missing values
for seed, (col, frac) in enumerate([("state", .02), ("ship_mode", .01), ("discount", .015), ("customer_name", .01)], start=20):
    df.loc[df.sample(frac=frac, random_state=seed).index, col] = np.nan
# 3) inconsistent text casing / whitespace
idx = df.sample(frac=.04, random_state=3).index
df.loc[idx, "region"] = df.loc[idx, "region"].str.upper()
idx = df.sample(frac=.03, random_state=4).index
df.loc[idx, "category"] = " " + df.loc[idx, "category"].str.lower() + " "
# 4) mixed date formats
idx = df.sample(frac=.03, random_state=5).index
df.loc[idx, "order_date"] = pd.to_datetime(df.loc[idx, "order_date"]).dt.strftime("%d/%m/%Y")
# 5) impossible values (negative quantity, absurd outliers)
df.loc[df.sample(12, random_state=6).index, "quantity"] = -1
df.loc[df.sample(6, random_state=7).index, "sales"] *= 40

df = df.sample(frac=1, random_state=9).reset_index(drop=True)
df.to_csv("data/raw_sales.csv", index=False)
print(f"Wrote data/raw_sales.csv  rows={len(df):,}  cols={df.shape[1]}")
