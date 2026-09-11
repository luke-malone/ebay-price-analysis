"""Validate price observations without altering their raw source data."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

# These are deliberately visible and conservative: they supplement, rather than
# replace, the scraper's `price_eligible` decision after a known false positive.
TITLE_EXCLUSION_TERMS = ("repair", "spares", "for parts", "parts only", "broken", "faulty")


def clean_observations(
    observations: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return usable observations and a complete audit trail of exclusions."""
    cleaned: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for observation in observations:
        reason = _exclusion_reason(observation)
        if reason:
            exclusions.append(_exclusion(observation, reason))
            continue
        cleaned.append(_normalise_group_fields(observation))
    return cleaned, exclusions


def deduplicate_latest_by_item_id(
    observations: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Choose the latest snapshot per item ID, retaining older observations separately."""
    latest_by_id: dict[str, dict[str, Any]] = {}
    repeated: list[dict[str, Any]] = []
    for observation in sorted(observations, key=lambda item: str(item["snapshot_timestamp"])):
        item_id = str(observation["item_id"])
        if item_id in latest_by_id:
            repeated.append(latest_by_id[item_id])
        latest_by_id[item_id] = observation
    return list(latest_by_id.values()), repeated


def _exclusion_reason(observation: dict[str, Any]) -> str | None:
    if not observation.get("price_eligible"):
        return "scraper marked listing price-ineligible"
    item_id = observation.get("item_id")
    if item_id is None or not str(item_id).strip():
        return "missing item_id"
    price = observation.get("price_numeric")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return "missing or invalid numeric price"
    if observation.get("is_actual_iphone") is not True:
        return "not confirmed as an actual iPhone"
    if observation.get("bundle") is True:
        return "bundle listing"
    title = str(observation.get("title") or "").casefold()
    if term := next((term for term in TITLE_EXCLUSION_TERMS if term in title), None):
        return f"title contains exclusion term: {term}"
    if not str(observation.get("model") or "").strip():
        return "missing model"
    if observation.get("storage_gb") is None:
        return "missing storage capacity"
    return None


def _normalise_group_fields(observation: dict[str, Any]) -> dict[str, Any]:
    result = dict(observation)
    result["item_id"] = str(result["item_id"]).strip()
    result["price_numeric"] = float(result["price_numeric"])
    result["model"] = _normalise_model_name(str(result["model"]))
    result["storage_gb"] = str(result["storage_gb"]).strip()
    result["colour"] = str(result.get("colour") or "unknown").strip().casefold()
    # Missing condition is explicit rather than silently merging with a known condition.
    result["condition_category"] = str(result.get("condition_category") or "unknown").strip().casefold()
    return result


def _normalise_model_name(value: str) -> str:
    """Make casing-only scraper variations a single comparable model."""
    model = re.sub(r"\s+", " ", value).strip().casefold()
    replacements = {
        "iphone": "iPhone",
        "se": "SE",
        "pro": "Pro",
        "max": "Max",
        "plus": "Plus",
        "gen": "Gen",
        "xr": "XR",
        "xs": "XS",
    }
    return " ".join(replacements.get(word, word) for word in model.split(" "))


def _exclusion(observation: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "item_id": observation.get("item_id"),
        "title": observation.get("title"),
        "price_numeric": observation.get("price_numeric"),
        "snapshot_timestamp": observation.get("snapshot_timestamp"),
        "exclusion_reason": reason,
    }
