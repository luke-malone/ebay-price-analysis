"""Run robust eBay iPhone price analysis from Google Cloud Storage."""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from src.analysis import analyse_price_levels, build_report
from src.cleaning import clean_observations, deduplicate_latest_by_item_id
from src.load_data import DEFAULT_BUCKET, load_price_eligible_snapshots, upload_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate MAD-based price analysis for eBay iPhone listings."
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="GCS bucket name.")
    parser.add_argument(
        "--project",
        default=os.getenv("GOOGLE_CLOUD_PROJECT"),
        help="Optional GCP project ID; defaults to GOOGLE_CLOUD_PROJECT when set.",
    )
    parser.add_argument(
        "--snapshot",
        action="append",
        dest="snapshots",
        help="UTC snapshot timestamp to load. Repeat to select several snapshots. "
        "Defaults to every snapshot under data/.",
    )
    parser.add_argument("--min-sample-size", type=int, default=5)
    parser.add_argument("--z-threshold", type=float, default=3.5)
    parser.add_argument(
        "--output", type=Path, default=Path("output/mad_analysis.json")
    )
    parser.add_argument("--upload", action="store_true", help="Upload the report to GCS.")
    parser.add_argument(
        "--upload-prefix", default="analysis", help="GCS folder used with --upload."
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    if args.min_sample_size < 1:
        raise ValueError("--min-sample-size must be at least 1")
    if args.z_threshold <= 0:
        raise ValueError("--z-threshold must be greater than zero")

    raw_observations = load_price_eligible_snapshots(args.bucket, args.snapshots, args.project)
    cleaned, exclusions = clean_observations(raw_observations)
    unique_observations, repeated_observations = deduplicate_latest_by_item_id(cleaned)
    price_estimates = analyse_price_levels(
        unique_observations, args.min_sample_size, args.z_threshold
    )
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    report = build_report(
        bucket=args.bucket,
        raw_observations=raw_observations,
        cleaned_observations=cleaned,
        exclusions=exclusions,
        repeated_observations=repeated_observations,
        price_estimates=price_estimates,
        min_sample_size=args.min_sample_size,
        z_threshold=args.z_threshold,
        generated_at=generated_at,
    )
    if args.upload:
        clean_prefix = args.upload_prefix.strip("/")
        if not clean_prefix:
            raise ValueError("--upload-prefix cannot be empty")
        upload_paths = [
            f"{clean_prefix}/{generated_at}/mad_analysis.json",
            f"{clean_prefix}/latest/mad_analysis.json",
        ]
        report["upload"] = {
            "bucket": args.bucket,
            "paths": upload_paths,
        }
        written_paths = upload_report(
                bucket_name=args.bucket,
                report=report,
                timestamp=generated_at,
                prefix=args.upload_prefix,
                project=args.project,
        )
        if written_paths != upload_paths:
            raise RuntimeError("Unexpected GCS upload paths")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info("Wrote %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
