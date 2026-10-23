"""Interactive dashboard for exploring scraped eBay iPhone listings."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from src.load_data import DEFAULT_BUCKET, list_price_eligible_snapshots, load_price_eligible_snapshots

st.set_page_config(page_title="eBay iPhone Price Explorer", page_icon="📱", layout="wide")
st.title("📱 eBay iPhone Price Explorer")
st.caption("Explore scraped listings, compare models, and identify potential bargains.")

with st.sidebar:
    st.header("Data source")
    bucket_name = st.text_input("Google Cloud Storage bucket", value=os.getenv("EBAY_BUCKET", DEFAULT_BUCKET))
    st.caption("Reads price-eligible snapshots using Google Cloud Application Default Credentials.")
    refresh = st.button("Refresh data", use_container_width=True)

@st.cache_data(ttl=300, show_spinner="Loading listing snapshots from Google Cloud Storage…")
def get_data(bucket: str, refresh_token: int = 0) -> tuple[pd.DataFrame, int]:
    snapshots = list_price_eligible_snapshots(bucket)
    records = load_price_eligible_snapshots(bucket, snapshots)
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
    data, snapshot_count = get_data(bucket_name.strip(), token)
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

tab_overview, tab_prices, tab_listings = st.tabs(["Overview", "Price analysis", "Listings"])
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

st.caption("Data is cached for five minutes. Use Refresh data to reload snapshots.")
