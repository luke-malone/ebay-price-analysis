"""Interactive dashboard for exploring scraped eBay iPhone listings."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from google.oauth2.service_account import Credentials

from src.load_data import DEFAULT_BUCKET, list_price_eligible_snapshots, load_price_eligible_snapshots

st.set_page_config(page_title="eBay iPhone Price Explorer", page_icon="📱", layout="wide")
st.title("📱 eBay iPhone Price Explorer")
st.caption("Explore scraped listings, compare models, and identify potential bargains.")

with st.sidebar:
    st.header("Data source")
    bucket_name = st.text_input("Google Cloud Storage bucket", value=os.getenv("EBAY_BUCKET", DEFAULT_BUCKET))
    st.caption("Locally uses Google Cloud Application Default Credentials; hosted deployments can use Streamlit secrets.")
    refresh = st.button("Refresh data", use_container_width=True)

@st.cache_data(ttl=300, show_spinner="Loading listing snapshots from Google Cloud Storage…")
def get_data(bucket: str, refresh_token: int = 0, credentials_info: dict | None = None) -> tuple[pd.DataFrame, int]:
    credentials = Credentials.from_service_account_info(credentials_info) if credentials_info else None
    snapshots = list_price_eligible_snapshots(bucket, credentials_override=credentials)
    records = load_price_eligible_snapshots(bucket, snapshots, credentials_override=credentials)
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame, len(snapshots)
    if "price_numeric" in frame:
        frame["price_numeric"] = pd.to_numeric(frame["price_numeric"], errors="coerce")
    if "snapshot_timestamp" in frame:
        frame["snapshot_timestamp"] = pd.to_datetime(frame["snapshot_timestamp"], errors="coerce", utc=True)
    for field in ("model", "storage_gb", "colour", "condition_category", "title", "item_id"):
        if field not in frame:
            frame[field] = "Unknown"
        frame[field] = frame[field].fillna("Unknown").astype(str)
    frame = frame.dropna(subset=["price_numeric"])
    frame = frame[frame["price_numeric"] > 0]
    return frame, len(snapshots)

try:
    token = int(datetime.utcnow().timestamp()) if refresh else 0
    try:
        credentials_info = dict(st.secrets["gcp_service_account"])
    except Exception:
        credentials_info = None
    data, snapshot_count = get_data(bucket_name.strip(), token, credentials_info)
except Exception as exc:
    st.error("Could not load the scraper data.")
    st.markdown(
        "Check that Google Cloud credentials are configured and have permission to read "
        f"gs://{bucket_name}/data/. Locally, run gcloud auth application-default login."
    )
    st.exception(exc)
    st.stop()

if data.empty:
    st.warning("No price-eligible listings were found in the selected bucket.")
    st.stop()

st.sidebar.header("Filter listings")
models = sorted(data["model"].unique().tolist())
selected_models = st.sidebar.multiselect("iPhone model", models, default=models)
model_data = data[data["model"].isin(selected_models)]

def choices(frame: pd.DataFrame, field: str) -> list[str]:
    return sorted(frame[field].dropna().astype(str).unique().tolist())

storages = choices(model_data, "storage_gb")
selected_storage = st.sidebar.multiselect("Storage", storages, default=storages)
storage_data = model_data[model_data["storage_gb"].isin(selected_storage)]
colours = choices(storage_data, "colour")
selected_colours = st.sidebar.multiselect("Colour", colours, default=colours)
colour_data = storage_data[storage_data["colour"].isin(selected_colours)]
conditions = choices(colour_data, "condition_category")
selected_conditions = st.sidebar.multiselect("Condition", conditions, default=conditions)
filtered = colour_data[colour_data["condition_category"].isin(selected_conditions)].copy()

minimum = float(filtered["price_numeric"].min()) if not filtered.empty else 0.0
maximum = float(filtered["price_numeric"].max()) if not filtered.empty else 0.0
if maximum > minimum:
    low, high = st.sidebar.slider("Price range (£)", min_value=minimum, max_value=maximum, value=(minimum, maximum))
    filtered = filtered[filtered["price_numeric"].between(low, high)]

search_text = st.sidebar.text_input("Search listing title or item ID").strip().casefold()
if search_text:
    filtered = filtered[
        filtered["title"].str.casefold().str.contains(search_text, na=False)
        | filtered["item_id"].str.casefold().str.contains(search_text, na=False)
    ]

latest_items = (
    filtered.sort_values("snapshot_timestamp").drop_duplicates("item_id", keep="last")
    if "snapshot_timestamp" in filtered else filtered.drop_duplicates("item_id", keep="last")
)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Listing observations", f"{len(filtered):,}")
col2.metric("Unique items in selection", f"{latest_items['item_id'].nunique():,}")
col3.metric("Average asking price", f"£{latest_items['price_numeric'].mean():,.2f}" if not latest_items.empty else "—")
col4.metric("Snapshots loaded", f"{snapshot_count:,}")

if filtered.empty:
    st.info("No listings match these filters. Widen the filters in the sidebar.")
    st.stop()

tab_overview, tab_prices, tab_listings, tab_deals, tab_trends, tab_anomalies = st.tabs(["Overview", "Price analysis", "Listings", "Deal finder", "Market trends", "Anomaly explorer"])
with tab_overview:
    left, right = st.columns(2)
    with left:
        price_fig = px.histogram(latest_items, x="price_numeric", nbins=30, title="Current asking-price distribution",
                                 labels={"price_numeric": "Asking price (£)", "count": "Listings"})
        price_fig.update_layout(bargap=0.08)
        st.plotly_chart(price_fig, use_container_width=True)
    with right:
        model_summary = latest_items.groupby("model", as_index=False).agg(
            listings=("item_id", "nunique"), median_price=("price_numeric", "median")
        ).sort_values("listings", ascending=False)
        model_fig = px.bar(model_summary, x="model", y="listings", title="Unique listings by iPhone model",
                           labels={"model": "Model", "listings": "Unique listings"})
        st.plotly_chart(model_fig, use_container_width=True)
    if "snapshot_timestamp" in filtered and filtered["snapshot_timestamp"].notna().any():
        history = filtered.dropna(subset=["snapshot_timestamp"]).groupby("snapshot_timestamp", as_index=False).agg(
            median_price=("price_numeric", "median"), observations=("item_id", "size")
        ).sort_values("snapshot_timestamp")
        history_fig = px.line(history, x="snapshot_timestamp", y="median_price", markers=True,
                              title="Median asking price per snapshot",
                              labels={"snapshot_timestamp": "Snapshot time", "median_price": "Median price (£)"})
        st.plotly_chart(history_fig, use_container_width=True)

with tab_prices:
    st.subheader("Compare prices by model and storage")
    group_fields = [field for field in ("model", "storage_gb", "condition_category", "colour") if field in latest_items]
    summary = latest_items.groupby(group_fields, dropna=False, as_index=False).agg(
        unique_listings=("item_id", "nunique"), median_price=("price_numeric", "median"),
        mean_price=("price_numeric", "mean"), minimum_price=("price_numeric", "min"),
        maximum_price=("price_numeric", "max")
    ).sort_values(["unique_listings", "median_price"], ascending=[False, True])
    summary = summary.rename(columns={
        "model": "Model", "storage_gb": "Storage (GB)", "condition_category": "Condition", "colour": "Colour",
        "unique_listings": "Unique listings", "median_price": "Median (£)", "mean_price": "Mean (£)",
        "minimum_price": "Lowest (£)", "maximum_price": "Highest (£)"
    })
    st.dataframe(summary.style.format({
        "Median (£)": "£{:.2f}", "Mean (£)": "£{:.2f}", "Lowest (£)": "£{:.2f}", "Highest (£)": "£{:.2f}"
    }), use_container_width=True, hide_index=True)
    st.caption("Asking prices are not confirmed sale prices or guaranteed market values.")

with tab_listings:
    display_columns = [field for field in (
        "model", "storage_gb", "colour", "condition_category", "price_numeric", "title", "item_id",
        "snapshot_timestamp", "url", "item_url"
    ) if field in filtered.columns]
    listing_table = filtered[display_columns].copy().rename(columns={
        "model": "Model", "storage_gb": "Storage (GB)", "colour": "Colour",
        "condition_category": "Condition", "price_numeric": "Price (£)", "title": "Listing title",
        "item_id": "eBay item ID", "snapshot_timestamp": "Snapshot time", "url": "URL", "item_url": "Item URL"
    })
    st.dataframe(listing_table.sort_values("Price (£)", ascending=True), use_container_width=True, hide_index=True,
                 column_config={
                     "Price (£)": st.column_config.NumberColumn(format="£%.2f"),
                     "Snapshot time": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm"),
                     "URL": st.column_config.LinkColumn(display_text="Open listing"),
                     "Item URL": st.column_config.LinkColumn(display_text="Open listing"),
                 })
    st.download_button("Download filtered listings as CSV", data=listing_table.to_csv(index=False).encode("utf-8"),
                       file_name="filtered_iphone_listings.csv", mime="text/csv")


with tab_deals:
    st.subheader("Find potentially underpriced listings")
    st.caption("Compares each item's latest asking price with similar model, storage, and condition listings in the current selection.")
    deal_base = latest_items.copy()
    compare_fields = [c for c in ("model", "storage_gb", "condition_category") if c in deal_base.columns]
    compare_stats = deal_base.groupby(compare_fields, dropna=False).agg(
        market_median=("price_numeric", "median"), comparable_count=("item_id", "nunique")
    ).reset_index()
    deals = deal_base.merge(compare_stats, on=compare_fields, how="left")
    deals["discount_pct"] = (deals["market_median"] - deals["price_numeric"]) / deals["market_median"] * 100
    deals["potential_deal"] = (deals["discount_pct"] >= 10) & (deals["comparable_count"] >= 3)
    d1, d2, d3 = st.columns(3)
    d1.metric("Potential deals", f"{int(deals['potential_deal'].sum()):,}")
    d2.metric("Best observed discount", f"{deals['discount_pct'].max():.1f}%" if not deals.empty else "—")
    d3.metric("Discount threshold", "10%")
    deal_fig = px.scatter(
        deals, x="price_numeric", y="discount_pct", color="model", symbol="condition_category",
        hover_name="title",
        hover_data={"item_id": True, "storage_gb": True, "colour": True, "market_median": ":.2f",
                    "comparable_count": True, "discount_pct": ":.1f", "price_numeric": ":.2f"},
        title="Asking price versus discount from comparable median",
        labels={"price_numeric": "Asking price (£)", "discount_pct": "Discount from comparable median (%)"},
    )
    deal_fig.add_hline(y=10, line_dash="dash", annotation_text="10% below median")
    st.plotly_chart(deal_fig, use_container_width=True)
    shortlist = deals[deals["potential_deal"]].sort_values("discount_pct", ascending=False)
    st.markdown("**Potential deal shortlist**")
    if shortlist.empty:
        st.info("No listings meet the 10% discount threshold with at least three comparable items.")
    else:
        cols = [c for c in ("model", "storage_gb", "condition_category", "price_numeric", "market_median",
                            "discount_pct", "comparable_count", "title", "url", "item_url") if c in shortlist.columns]
        table = shortlist[cols].rename(columns={
            "model": "Model", "storage_gb": "Storage (GB)", "condition_category": "Condition",
            "price_numeric": "Asking price (£)", "market_median": "Comparable median (£)",
            "discount_pct": "Discount (%)", "comparable_count": "Comparables", "title": "Listing",
            "url": "URL", "item_url": "Item URL"})
        st.dataframe(table, use_container_width=True, hide_index=True, column_config={
            "Asking price (£)": st.column_config.NumberColumn(format="£%.2f"),
            "Comparable median (£)": st.column_config.NumberColumn(format="£%.2f"),
            "Discount (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "URL": st.column_config.LinkColumn(display_text="Open listing"),
            "Item URL": st.column_config.LinkColumn(display_text="Open listing")})
    st.caption("A discount is a screening signal, not proof of a bargain. Check condition, seller, postage, and listing details.")

with tab_trends:
    st.subheader("Price history and market inventory")
    if "snapshot_timestamp" in filtered.columns and filtered["snapshot_timestamp"].notna().any():
        available_models = sorted(filtered["model"].unique().tolist())
        trend_models = st.multiselect("Models to compare", available_models, default=available_models[:5], key="trend_models")
        history_frame = filtered[filtered["model"].isin(trend_models)].dropna(subset=["snapshot_timestamp"])
        history = history_frame.groupby(["snapshot_timestamp", "model"], as_index=False).agg(
            median_price=("price_numeric", "median"), observations=("item_id", "size")).sort_values("snapshot_timestamp")
        if not history.empty:
            trend_fig = px.line(history, x="snapshot_timestamp", y="median_price", color="model", markers=True,
                title="Median asking price per snapshot",
                labels={"snapshot_timestamp": "Snapshot time", "median_price": "Median asking price (£)", "model": "Model"},
                hover_data={"observations": True})
            st.plotly_chart(trend_fig, use_container_width=True)
            st.caption("Snapshots show prices observed at collection times; they do not necessarily represent the price history of a single item.")
    else:
        st.info("No valid snapshot timestamps are available for this selection.")

    inventory = latest_items.groupby(["model", "storage_gb"], as_index=False).agg(
        listings=("item_id", "nunique"), median_price=("price_numeric", "median"))
    tree_fig = px.treemap(inventory, path=["model", "storage_gb"], values="listings", color="median_price",
        color_continuous_scale="Viridis", title="Inventory treemap: size = listings, colour = median price",
        hover_data={"listings": True, "median_price": ":.2f"},
        labels={"listings": "Unique listings", "median_price": "Median asking price (£)", "storage_gb": "Storage"})
    st.plotly_chart(tree_fig, use_container_width=True)

with tab_prices:
    st.subheader("Price distribution by model")
    box_fig = px.box(latest_items, x="model", y="price_numeric", color="model", points="outliers",
        title="Asking-price distribution by iPhone model",
        labels={"model": "iPhone model", "price_numeric": "Asking price (£)"})
    st.plotly_chart(box_fig, use_container_width=True)
    st.caption("Boxes show the median and interquartile range. Outlier points are statistical observations to investigate, not necessarily bad listings.")

    st.subheader("Model versus storage heatmap")
    heat_data = latest_items.groupby(["model", "storage_gb"], as_index=False).agg(
        median_price=("price_numeric", "median"), listings=("item_id", "nunique"))
    heat_pivot = heat_data.pivot(index="model", columns="storage_gb", values="median_price")
    if not heat_pivot.empty:
        heat_fig = px.imshow(heat_pivot, text_auto=".0f", aspect="auto", color_continuous_scale="Viridis",
            labels={"x": "Storage (GB)", "y": "iPhone model", "color": "Median price (£)"},
            title="Median asking price by model and storage")
        st.plotly_chart(heat_fig, use_container_width=True)
    st.caption("Empty heatmap cells indicate model/storage combinations absent from the selected data.")

with tab_anomalies:
    st.subheader("Anomaly detection explorer")
    anomaly_data = latest_items.copy()
    group_cols = [c for c in ("model", "storage_gb", "condition_category") if c in anomaly_data.columns]
    grouped_prices = anomaly_data.groupby(group_cols, dropna=False)["price_numeric"]
    anomaly_data["group_median"] = grouped_prices.transform("median")
    abs_dev = (anomaly_data["price_numeric"] - anomaly_data["group_median"]).abs()
    anomaly_data["mad"] = abs_dev.groupby([anomaly_data[c] for c in group_cols], dropna=False).transform("median")
    anomaly_data["modified_z"] = abs_dev / (1.4826 * anomaly_data["mad"].replace(0, float("nan")))
    zero_mad = anomaly_data["mad"].eq(0) & abs_dev.gt(0)
    anomaly_data["is_anomaly"] = anomaly_data["modified_z"].gt(3.5) | zero_mad
    anomaly_data.loc[zero_mad, "modified_z"] = float("inf")
    anomaly_data["modified_z"] = anomaly_data["modified_z"].fillna(0)
    a1, a2 = st.columns(2)
    flagged_count = int(anomaly_data["is_anomaly"].sum())
    a1.metric("Unusual prices flagged", f"{flagged_count:,}")
    a2.metric("Share flagged", f"{100 * flagged_count / len(anomaly_data):.1f}%" if len(anomaly_data) else "0.0%")
    anomaly_fig = px.histogram(anomaly_data, x="price_numeric", color="is_anomaly", nbins=35, barmode="overlay",
        title="Price distribution: typical observations versus MAD flags",
        labels={"price_numeric": "Asking price (£)", "is_anomaly": "MAD outlier"})
    st.plotly_chart(anomaly_fig, use_container_width=True)
    st.caption("Modified z-score uses median absolute deviation within model/storage/condition groups; values above 3.5 are flagged. Zero-MAD groups flag prices differing from the median. Flags are prompts for inspection, not automatic exclusions.")
    only_flagged = st.checkbox("Show only flagged prices", value=True)
    anomaly_view = anomaly_data[anomaly_data["is_anomaly"]] if only_flagged else anomaly_data
    anomaly_cols = [c for c in ("model", "storage_gb", "condition_category", "price_numeric", "group_median",
        "modified_z", "title", "item_id", "url", "item_url") if c in anomaly_view.columns]
    anomaly_table = anomaly_view[anomaly_cols].rename(columns={
        "model": "Model", "storage_gb": "Storage (GB)", "condition_category": "Condition",
        "price_numeric": "Asking price (£)", "group_median": "Group median (£)",
        "modified_z": "Modified z-score", "title": "Listing", "item_id": "eBay item ID",
        "url": "URL", "item_url": "Item URL"})
    st.dataframe(anomaly_table, use_container_width=True, hide_index=True, column_config={
        "Asking price (£)": st.column_config.NumberColumn(format="£%.2f"),
        "Group median (£)": st.column_config.NumberColumn(format="£%.2f"),
        "Modified z-score": st.column_config.NumberColumn(format="%.2f"),
        "URL": st.column_config.LinkColumn(display_text="Open listing"),
        "Item URL": st.column_config.LinkColumn(display_text="Open listing")})


st.caption("Data is cached for five minutes. Use Refresh data to reload snapshots.")
