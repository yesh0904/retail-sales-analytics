"""
app.py - Interactive dashboard.   Run:  streamlit run app.py
Requires data/clean_sales.csv (created by analysis.py).
"""
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Retail Sales Analytics", page_icon="📊", layout="wide")


@st.cache_data
def load():
    return pd.read_csv("data/clean_sales.csv", parse_dates=["order_date", "ship_date", "year_month"])


df = load()
st.title("📊 Retail Sales & Customer Analytics")
st.caption("Interactive companion to the analysis report. Use the filters in the sidebar.")

# ---------------- filters
st.sidebar.header("Filters")
years = st.sidebar.multiselect("Year", sorted(df["year"].unique()), default=sorted(df["year"].unique()))
regions = st.sidebar.multiselect("Region", sorted(df["region"].unique()), default=sorted(df["region"].unique()))
cats = st.sidebar.multiselect("Category", sorted(df["category"].unique()), default=sorted(df["category"].unique()))
segs = st.sidebar.multiselect("Segment", sorted(df["segment"].unique()), default=sorted(df["segment"].unique()))
max_disc = st.sidebar.slider("Max discount", 0.0, 0.5, 0.5, 0.1, format="%.1f")

f = df[df["year"].isin(years) & df["region"].isin(regions) & df["category"].isin(cats)
       & df["segment"].isin(segs) & (df["discount"] <= max_disc)]
if f.empty:
    st.warning("No data for the selected filters.")
    st.stop()

# ---------------- KPIs
sales, profit = f["sales"].sum(), f["profit"].sum()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Sales", f"${sales:,.0f}")
c2.metric("Profit", f"${profit:,.0f}")
c3.metric("Profit margin", f"{profit / sales:.1%}")
c4.metric("Orders", f"{f['order_id'].nunique():,}")
c5.metric("Customers", f"{f['customer_id'].nunique():,}")

tab1, tab2, tab3, tab4 = st.tabs(["📈 Trends", "🛒 Products", "🏷️ Discounts", "👥 Customers"])

with tab1:
    m = f.groupby("year_month", as_index=False).agg(sales=("sales", "sum"), profit=("profit", "sum"))
    st.plotly_chart(px.line(m, x="year_month", y=["sales", "profit"], title="Monthly sales & profit",
                            labels={"value": "USD", "year_month": ""}), use_container_width=True)
    a, b = st.columns(2)
    reg = f.groupby("region", as_index=False).agg(sales=("sales", "sum"), profit=("profit", "sum"))
    a.plotly_chart(px.bar(reg, x="region", y=["sales", "profit"], barmode="group", title="By region"),
                   use_container_width=True)
    seg = f.groupby("segment", as_index=False).agg(sales=("sales", "sum"), profit=("profit", "sum"))
    b.plotly_chart(px.bar(seg, x="segment", y=["sales", "profit"], barmode="group", title="By segment"),
                   use_container_width=True)

with tab2:
    sub = f.groupby(["category", "sub_category"], as_index=False).agg(sales=("sales", "sum"), profit=("profit", "sum"))
    sub["margin"] = sub["profit"] / sub["sales"]
    st.plotly_chart(px.bar(sub.sort_values("profit"), x="profit", y="sub_category", color="margin", orientation="h",
                           color_continuous_scale="RdYlGn", title="Profit by sub-category (colour = margin)"),
                    use_container_width=True)
    st.dataframe(sub.sort_values("profit", ascending=False).style.format(
        {"sales": "${:,.0f}", "profit": "${:,.0f}", "margin": "{:.1%}"}), use_container_width=True)

with tab3:
    d = f.groupby("discount_band", as_index=False, observed=True).agg(
        profit=("profit", "sum"), loss_rate=("is_loss", "mean"), lines=("order_id", "count"))
    a, b = st.columns(2)
    a.plotly_chart(px.bar(d, x="discount_band", y="profit", color="profit", color_continuous_scale="RdYlGn",
                          title="Profit by discount band"), use_container_width=True)
    b.plotly_chart(px.line(d, x="discount_band", y="loss_rate", markers=True,
                           title="Share of order lines making a loss"), use_container_width=True)
    st.info("Tip: drag the 'Max discount' slider to 0.2 to see profit if discounts above 20% were capped.")

with tab4:
    rfm = pd.read_csv("reports/rfm_customers.csv")
    seg_sum = rfm.groupby("rfm_segment", as_index=False).agg(
        customers=("customer_id", "count"), revenue=("monetary", "sum"))
    a, b = st.columns(2)
    a.plotly_chart(px.pie(seg_sum, names="rfm_segment", values="revenue", title="Revenue by RFM segment", hole=.4),
                   use_container_width=True)
    b.plotly_chart(px.bar(seg_sum, x="rfm_segment", y="customers", title="Customers by RFM segment"),
                   use_container_width=True)
    pick = st.selectbox("List customers in segment", sorted(rfm["rfm_segment"].unique()))
    st.dataframe(rfm[rfm["rfm_segment"] == pick].sort_values("monetary", ascending=False).head(25),
                 use_container_width=True)
