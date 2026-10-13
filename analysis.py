"""
analysis.py  -  End-to-end Retail Sales & Customer Analytics pipeline
Stages: 1) Load  2) Clean  3) Feature engineering  4) KPIs  5) SQL analysis
        6) Deep-dive analysis (discounts, seasonality, RFM)  7) Charts  8) Export
Run:  python analysis.py
"""
import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA, CHARTS, REPORTS, SQL = ROOT / "data", ROOT / "charts", ROOT / "reports", ROOT / "sql"
for p in (CHARTS, REPORTS):
    p.mkdir(exist_ok=True)

# ------------------------------------------------------------------ style
PALETTE = {"blue": "#2F5D8C", "teal": "#2A9D8F", "amber": "#E9A23B", "red": "#C8553D", "grey": "#8A8F98"}
plt.rcParams.update({
    "figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titleweight": "bold", "axes.titlesize": 13, "axes.labelsize": 10,
    "axes.grid": True, "grid.alpha": .25, "font.family": "DejaVu Sans",
})
money = mtick.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M" if abs(x) >= 1e6 else f"${x/1e3:.0f}K" if abs(x) >= 1e3 else f"${x:.0f}")

def save(fig, name):
    fig.tight_layout()
    fig.savefig(CHARTS / name, bbox_inches="tight")
    plt.close(fig)

# ================================================================== 1. LOAD
raw = pd.read_csv(DATA / "raw_sales.csv")
log = {"rows_raw": len(raw)}
print(f"[1] Loaded raw data: {raw.shape[0]:,} rows x {raw.shape[1]} cols")

# ================================================================== 2. CLEAN
df = raw.copy()

# 2.1 duplicates
dups = int(df.duplicated().sum())
df = df.drop_duplicates().reset_index(drop=True)
log["duplicates_removed"] = dups

# 2.2 text standardisation
for c in ["region", "category", "sub_category", "segment", "ship_mode", "state", "customer_name"]:
    df[c] = df[c].astype("string").str.strip().str.title()
log["text_fields_standardised"] = 7

# 2.3 dates: two formats present
d1 = pd.to_datetime(df["order_date"], format="%Y-%m-%d", errors="coerce")
d2 = pd.to_datetime(df["order_date"], format="%d/%m/%Y", errors="coerce")
log["mixed_date_formats_fixed"] = int(d1.isna().sum())
df["order_date"] = d1.fillna(d2)
df["ship_date"] = pd.to_datetime(df["ship_date"], format="%Y-%m-%d", errors="coerce")
assert df["order_date"].notna().all(), "Unparseable order dates remain"

# 2.4 invalid quantities (negative = sign error -> absolute value)
bad_qty = int((df["quantity"] <= 0).sum())
df["quantity"] = df["quantity"].abs()
log["negative_quantity_fixed"] = bad_qty

# 2.5 missing values - fill using logic, not blindly
miss_before = df.isna().sum()
log["missing_before"] = {k: int(v) for k, v in miss_before[miss_before > 0].items()}
# customer attributes are fixed per customer_id -> recover from other rows
for c in ["customer_name", "state"]:
    lookup = df.dropna(subset=[c]).groupby("customer_id")[c].agg(lambda s: s.mode().iloc[0])
    df[c] = df[c].fillna(df["customer_id"].map(lookup))
df[["customer_name", "state"]] = df[["customer_name", "state"]].fillna("Unknown")  # customers with a single order
df["ship_mode"] = df["ship_mode"].fillna("Unknown")

# 2.6 sales integrity: sales should equal price * qty * (1 - discount)
valid_disc = np.array([0, .1, .2, .3, .4, .5])
gross = df["unit_price"] * df["quantity"]
implied = 1 - df["sales"] / gross
# missing discount -> infer from sales when implied value is a valid discount level, else 0
snap = valid_disc[np.abs(implied.to_numpy()[:, None] - valid_disc).argmin(axis=1)]
ok = (np.abs(implied - snap) < 0.02)
df["discount"] = df["discount"].fillna(pd.Series(np.where(ok, snap, 0.0), index=df.index))
expected = (gross * (1 - df["discount"])).round(2)
outliers = (np.abs(df["sales"] - expected) > 0.05)
log["sales_outliers_corrected"] = int(outliers.sum())
df.loc[outliers, "sales"] = expected[outliers]
# profit on corrected rows: rescale to keep original margin
df["profit"] = df["profit"].astype(float)
log["rows_clean"] = len(df)
log["missing_after"] = int(df.isna().sum().sum())
print(f"[2] Cleaned data: {len(df):,} rows | duplicates {dups} | date fixes {log['mixed_date_formats_fixed']} | "
      f"qty fixes {bad_qty} | sales fixes {log['sales_outliers_corrected']} | nulls left {log['missing_after']}")

# ================================================================== 3. FEATURES
df["year"] = df["order_date"].dt.year
df["month"] = df["order_date"].dt.month
df["year_month"] = df["order_date"].dt.to_period("M").dt.to_timestamp()
df["quarter"] = df["order_date"].dt.quarter
df["ship_days"] = (df["ship_date"] - df["order_date"]).dt.days
df["profit_margin"] = df["profit"] / df["sales"]
df["discount_band"] = pd.cut(df["discount"], [-.01, 0, .1, .2, .3, .5],
                             labels=["0%", "1-10%", "11-20%", "21-30%", "31-50%"])
df["is_loss"] = df["profit"] < 0
df.to_csv(DATA / "clean_sales.csv", index=False)

# ================================================================== 4. KPIs
orders = df.groupby("order_id").agg(sales=("sales", "sum"), profit=("profit", "sum"))
kpi = {
    "total_sales": float(df["sales"].sum()),
    "total_profit": float(df["profit"].sum()),
    "profit_margin": float(df["profit"].sum() / df["sales"].sum()),
    "orders": int(df["order_id"].nunique()),
    "customers": int(df["customer_id"].nunique()),
    "avg_order_value": float(orders["sales"].mean()),
    "avg_ship_days": float(df["ship_days"].mean()),
    "loss_making_share": float(df["is_loss"].mean()),
    "loss_total": float(df.loc[df["is_loss"], "profit"].sum()),
}
print("[4] KPIs:", {k: round(v, 3) for k, v in kpi.items()})

# ================================================================== 5. SQL (SQLite)
con = sqlite3.connect(DATA / "retail.db")
df.assign(order_date=df["order_date"].dt.strftime("%Y-%m-%d"),
          ship_date=df["ship_date"].dt.strftime("%Y-%m-%d"),
          year_month=df["year_month"].dt.strftime("%Y-%m")).drop(columns=["discount_band"]).to_sql(
    "sales", con, if_exists="replace", index=False)
queries = [q.strip() for q in (SQL / "queries.sql").read_text().split(";") if q.strip()]
sql_results = {}
for q in queries:
    title = q.splitlines()[0].replace("--", "").strip()
    sql_results[title] = pd.read_sql_query(q, con)
    sql_results[title].to_csv(REPORTS / f"sql_{title.split(':')[0].strip().lower().replace(' ', '_')}.csv", index=False)
con.close()
print(f"[5] Ran {len(queries)} SQL queries against SQLite")

# ================================================================== 6. DEEP DIVES
by_year = df.groupby("year").agg(sales=("sales", "sum"), profit=("profit", "sum"))
by_year["yoy_sales_growth"] = by_year["sales"].pct_change()
by_cat = df.groupby("category").agg(sales=("sales", "sum"), profit=("profit", "sum"))
by_cat["margin"] = by_cat["profit"] / by_cat["sales"]
by_sub = df.groupby(["category", "sub_category"]).agg(sales=("sales", "sum"), profit=("profit", "sum")).reset_index()
by_sub["margin"] = by_sub["profit"] / by_sub["sales"]
by_reg = df.groupby("region").agg(sales=("sales", "sum"), profit=("profit", "sum"))
by_reg["margin"] = by_reg["profit"] / by_reg["sales"]
by_seg = df.groupby("segment").agg(sales=("sales", "sum"), profit=("profit", "sum"), customers=("customer_id", "nunique"))
by_disc = df.groupby("discount_band", observed=True).agg(
    sales=("sales", "sum"), profit=("profit", "sum"), lines=("order_id", "count"), loss_rate=("is_loss", "mean"))
by_disc["margin"] = by_disc["profit"] / by_disc["sales"]
by_month = df.groupby("month").agg(sales=("sales", "sum"))
heat = df.pivot_table(index="year", columns="month", values="sales", aggfunc="sum")

# ---- RFM customer segmentation
snapshot = df["order_date"].max() + pd.Timedelta(days=1)
rfm = df.groupby("customer_id").agg(
    recency=("order_date", lambda s: (snapshot - s.max()).days),
    frequency=("order_id", "nunique"),
    monetary=("sales", "sum"),
    profit=("profit", "sum"),
).reset_index()
rfm["R"] = pd.qcut(rfm["recency"].rank(method="first"), 4, labels=[4, 3, 2, 1]).astype(int)
rfm["F"] = pd.qcut(rfm["frequency"].rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)
rfm["M"] = pd.qcut(rfm["monetary"].rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)
rfm["score"] = rfm["R"] + rfm["F"] + rfm["M"]

def segment(r):
    if r.R >= 3 and r.F >= 3 and r.M >= 3:
        return "Champions"
    if r.R >= 3 and r.F >= 2:
        return "Loyal / Potential"
    if r.R <= 2 and r.F >= 3 and r.M >= 3:
        return "At Risk (high value)"
    if r.R == 1:
        return "Lost / Dormant"
    return "Need Attention"

rfm["rfm_segment"] = rfm.apply(segment, axis=1)
rfm_sum = rfm.groupby("rfm_segment").agg(customers=("customer_id", "count"), revenue=("monetary", "sum"),
                                         avg_orders=("frequency", "mean"), avg_recency=("recency", "mean"))
rfm_sum["revenue_share"] = rfm_sum["revenue"] / rfm_sum["revenue"].sum()
rfm.to_csv(REPORTS / "rfm_customers.csv", index=False)

# Pareto: how concentrated is revenue?
cust_rev = rfm.sort_values("monetary", ascending=False)["monetary"].reset_index(drop=True)
top20_share = float(cust_rev.head(int(len(cust_rev) * .2)).sum() / cust_rev.sum())

# ================================================================== 7. CHARTS
# 7.1 monthly trend
m = df.groupby("year_month").agg(sales=("sales", "sum"), profit=("profit", "sum"))
fig, ax = plt.subplots(figsize=(10, 4.2))
ax.plot(m.index, m["sales"], color=PALETTE["blue"], lw=2, label="Sales")
ax.fill_between(m.index, m["profit"], color=PALETTE["teal"], alpha=.35, label="Profit")
ax.plot(m.index, m["sales"].rolling(3).mean(), color=PALETTE["amber"], lw=1.5, ls="--", label="Sales (3-mo avg)")
ax.yaxis.set_major_formatter(money)
ax.set_title("Monthly Sales & Profit, 2023-2025")
ax.legend(frameon=False)
save(fig, "01_monthly_trend.png")

# 7.2 seasonality heatmap
fig, ax = plt.subplots(figsize=(10, 2.8))
im = ax.imshow(heat.values, cmap="YlGnBu", aspect="auto")
ax.set_xticks(range(12)); ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
ax.set_yticks(range(len(heat))); ax.set_yticklabels(heat.index)
ax.grid(False)
for i in range(heat.shape[0]):
    for j in range(heat.shape[1]):
        ax.text(j, i, f"{heat.values[i, j]/1e3:.0f}K", ha="center", va="center", fontsize=8,
                color="white" if heat.values[i, j] > heat.values.max() * .6 else "#222")
ax.set_title("Seasonality: Sales by Month and Year")
save(fig, "02_seasonality_heatmap.png")

# 7.3 sub-category profit
s = by_sub.sort_values("profit")
fig, ax = plt.subplots(figsize=(8, 4.8))
ax.barh(s["sub_category"], s["profit"], color=[PALETTE["red"] if v < s["profit"].median() else PALETTE["teal"] for v in s["profit"]])
ax.xaxis.set_major_formatter(money)
for y, (p, mg) in enumerate(zip(s["profit"], s["margin"])):
    ax.text(p, y, f"  {mg:.0%}", va="center", fontsize=8)
ax.set_title("Profit by Sub-Category (label = margin)")
save(fig, "03_subcategory_profit.png")

# 7.4 discount impact  (key insight)
fig, ax1 = plt.subplots(figsize=(8, 4.4))
cols = [PALETTE["teal"] if v > 0 else PALETTE["red"] for v in by_disc["profit"]]
ax1.bar(by_disc.index.astype(str), by_disc["profit"], color=cols)
ax1.yaxis.set_major_formatter(money); ax1.set_ylabel("Total profit")
ax2 = ax1.twinx()
ax2.plot(by_disc.index.astype(str), by_disc["loss_rate"], color=PALETTE["amber"], marker="o", lw=2)
ax2.yaxis.set_major_formatter(mtick.PercentFormatter(1)); ax2.set_ylabel("% of order lines making a loss"); ax2.grid(False)
ax2.spines["right"].set_visible(True)
ax1.set_title("Discounting Destroys Profit")
ax1.set_xlabel("Discount band")
save(fig, "04_discount_impact.png")

# 7.5 region x category margin
rc = df.pivot_table(index="region", columns="category", values="profit", aggfunc="sum") / \
     df.pivot_table(index="region", columns="category", values="sales", aggfunc="sum")
fig, ax = plt.subplots(figsize=(7, 3.6))
im = ax.imshow(rc.values, cmap="RdYlGn", vmin=-.05, vmax=.25, aspect="auto")
ax.set_xticks(range(rc.shape[1])); ax.set_xticklabels(rc.columns)
ax.set_yticks(range(rc.shape[0])); ax.set_yticklabels(rc.index); ax.grid(False)
for i in range(rc.shape[0]):
    for j in range(rc.shape[1]):
        ax.text(j, i, f"{rc.values[i, j]:.1%}", ha="center", va="center", fontsize=9)
ax.set_title("Profit Margin: Region x Category")
save(fig, "05_region_category_margin.png")

# 7.6 category / region / segment share
fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
for ax, (title, t) in zip(axes, [("Category", by_cat), ("Region", by_reg), ("Segment", by_seg)]):
    t = t.sort_values("sales", ascending=False)
    x = np.arange(len(t)); w = .38
    ax.bar(x - w/2, t["sales"], w, color=PALETTE["blue"], label="Sales")
    ax.bar(x + w/2, t["profit"], w, color=PALETTE["teal"], label="Profit")
    ax.set_xticks(x); ax.set_xticklabels(t.index, fontsize=8, rotation=15)
    ax.yaxis.set_major_formatter(money); ax.set_title(f"By {title}")
axes[0].legend(frameon=False, fontsize=8)
save(fig, "06_category_region_segment.png")

# 7.7 RFM
r = rfm_sum.sort_values("revenue", ascending=False)
fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
axes[0].bar(r.index, r["customers"], color=PALETTE["blue"]); axes[0].set_title("Customers per RFM Segment")
axes[0].tick_params(axis="x", rotation=25, labelsize=8)
axes[1].bar(r.index, r["revenue_share"], color=PALETTE["amber"]); axes[1].set_title("Revenue Share per Segment")
axes[1].yaxis.set_major_formatter(mtick.PercentFormatter(1)); axes[1].tick_params(axis="x", rotation=25, labelsize=8)
save(fig, "07_rfm_segments.png")

# 7.8 Pareto
cum = cust_rev.cumsum() / cust_rev.sum()
fig, ax = plt.subplots(figsize=(7, 3.8))
ax.plot(np.arange(1, len(cum) + 1) / len(cum), cum, color=PALETTE["blue"], lw=2)
ax.axvline(.2, color=PALETTE["grey"], ls="--"); ax.axhline(top20_share, color=PALETTE["grey"], ls="--")
ax.annotate(f"Top 20% of customers\n= {top20_share:.0%} of revenue", (.22, top20_share - .12), fontsize=9)
ax.xaxis.set_major_formatter(mtick.PercentFormatter(1)); ax.yaxis.set_major_formatter(mtick.PercentFormatter(1))
ax.set_xlabel("Share of customers"); ax.set_ylabel("Cumulative revenue"); ax.set_title("Customer Revenue Concentration (Pareto)")
save(fig, "08_pareto.png")

# 7.9 data cleaning summary
fig, ax = plt.subplots(figsize=(7, 3.4))
items = {"Duplicate rows": log["duplicates_removed"], "Mixed date formats": log["mixed_date_formats_fixed"],
         "Negative quantities": log["negative_quantity_fixed"], "Sales outliers": log["sales_outliers_corrected"],
         "Missing values filled": sum(log["missing_before"].values())}
ax.barh(list(items), list(items.values()), color=PALETTE["blue"])
for y, v in enumerate(items.values()):
    ax.text(v, y, f"  {v:,}", va="center", fontsize=9)
ax.set_title("Data Quality Issues Fixed"); ax.invert_yaxis()
save(fig, "09_cleaning_summary.png")
print("[7] Saved 9 charts")

# ================================================================== 8. EXPORT
summary = {
    "kpi": kpi,
    "cleaning_log": log,
    "by_year": by_year.reset_index().to_dict("records"),
    "by_category": by_cat.reset_index().to_dict("records"),
    "by_subcategory": by_sub.to_dict("records"),
    "by_region": by_reg.reset_index().to_dict("records"),
    "by_segment": by_seg.reset_index().to_dict("records"),
    "by_discount_band": by_disc.reset_index().astype({"discount_band": str}).to_dict("records"),
    "peak_months": by_month["sales"].sort_values(ascending=False).head(3).index.tolist(),
    "rfm_segments": rfm_sum.reset_index().to_dict("records"),
    "top20_customer_revenue_share": top20_share,
    "loss_by_discount_over_30": float(df.loc[df["discount"] > .3, "profit"].sum()),
    "profit_lines_discount_over_20": float(df.loc[df["discount"] > .2, "profit"].sum()),
    "sales_lines_discount_over_20": float(df.loc[df["discount"] > .2, "sales"].sum()),
    "tables_profit_by_discount": df[df.sub_category == "Tables"].groupby("discount_band", observed=True)["profit"].sum().round(0).astype(float).to_dict(),
    "margin_by_year": (df.groupby("year")["profit"].sum() / df.groupby("year")["sales"].sum()).to_dict(),
}
(REPORTS / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
print("[8] Exported clean_sales.csv, retail.db, rfm_customers.csv, summary.json")
