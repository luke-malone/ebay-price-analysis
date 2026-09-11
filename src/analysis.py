"""Comparable-group analysis and serialisable price-estimate reporting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from statistics import median
from typing import Any

from src.mad import median_absolute_deviation, modified_z_score

PRICE_GROUPS: dict[str, tuple[str, ...]] = {
    "model": ("model",),
    "model_storage": ("model", "storage_gb"),
    "model_storage_colour": ("model", "storage_gb", "colour"),
}


def analyse_price_levels(
    observations: Iterable[dict[str, Any]], min_sample_size: int, z_threshold: float
) -> dict[str, list[dict[str, Any]]]:
    """Produce MAD-based estimates at each requested comparable-group level."""
    records = list(observations)
    return {
        name: analyse_groups(records, min_sample_size, z_threshold, fields)
        for name, fields in PRICE_GROUPS.items()
    }


def analyse_groups(
    observations: Iterable[dict[str, Any]],
    min_sample_size: int,
    z_threshold: float,
    group_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Calculate group medians, MADs, and per-listing outlier decisions."""
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        groups[tuple(str(observation[field]) for field in group_fields)].append(observation)

    results: list[dict[str, Any]] = []
    for key in sorted(groups):
        members = groups[key]
        prices = [member["price_numeric"] for member in members]
        sample_size = len(members)
        group_result: dict[str, Any] = {
            **dict(zip(group_fields, key, strict=True)),
            "sample_size": sample_size,
            "minimum_sample_size": min_sample_size,
        }
        if sample_size < min_sample_size:
            group_result.update(
                {"analysis_status": "insufficient_sample", "listings": _unscored(members)}
            )
            results.append(group_result)
            continue

        centre = float(median(prices))
        mad = median_absolute_deviation(prices, centre)
        listings = []
        for member in members:
            score = modified_z_score(member["price_numeric"], centre, mad)
            listings.append(
                _listing_result(member, score, score is not None and abs(score) > z_threshold)
            )
        non_outlier_prices = [row["price"] for row in listings if not row["is_outlier"]]
        group_result.update(
            {
                "analysis_status": "analysed" if mad > 0 else "zero_mad",
                "median_price": centre,
                "mad": mad,
                "modified_z_threshold": z_threshold,
                "outlier_count": sum(row["is_outlier"] for row in listings),
                "robust_market_price_estimate": (
                    float(median(non_outlier_prices)) if non_outlier_prices else None
                ),
                "listings": listings,
            }
        )
        results.append(group_result)
    return results


def build_report(
    *,
    bucket: str,
    raw_observations: list[dict[str, Any]],
    cleaned_observations: list[dict[str, Any]],
    exclusions: list[dict[str, Any]],
    repeated_observations: list[dict[str, Any]],
    price_estimates: dict[str, list[dict[str, Any]]],
    min_sample_size: int,
    z_threshold: float,
    generated_at: str,
) -> dict[str, Any]:
    """Produce an auditable report; estimates are not true market prices."""
    return {
        "generated_at": generated_at,
        "methodology": {
            "source_bucket": bucket,
            "core_analysis": "one latest observation per eBay item_id",
            "price_estimate_levels": PRICE_GROUPS,
            "median": "median(price)",
            "mad": "median(abs(price - median(price)))",
            "modified_z_score": "0.6745 * (price - median) / MAD, when MAD > 0",
            "market_price_note": "A robust sample estimate, not a true market price.",
            "min_sample_size": min_sample_size,
            "modified_z_threshold": z_threshold,
        },
        "summary": {
            "raw_observation_count": len(raw_observations),
            "usable_observation_count": len(cleaned_observations),
            "unique_listing_count": len(cleaned_observations) - len(repeated_observations),
            "repeated_observation_count": len(repeated_observations),
            "excluded_observation_count": len(exclusions),
            "groups_by_estimate_level": {
                name: len(groups) for name, groups in price_estimates.items()
            },
        },
        "exclusions": exclusions,
        "repeated_observations": repeated_observations,
        "price_estimates": price_estimates,
    }


def _listing_result(
    observation: dict[str, Any], score: float | None, is_outlier: bool
) -> dict[str, Any]:
    return {
        "item_id": observation["item_id"],
        "title": observation.get("title"),
        "price": observation["price_numeric"],
        "snapshot_timestamp": observation["snapshot_timestamp"],
        "robust_z_score": score,
        "is_outlier": is_outlier,
    }


def _unscored(members: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_listing_result(member, None, False) for member in members]
