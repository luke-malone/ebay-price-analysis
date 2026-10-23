"""Read timestamped scraper outputs from Google Cloud Storage."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

import google.auth
from google.cloud import storage
from google.oauth2.service_account import Credentials

DEFAULT_BUCKET = "server-413715-iphone-scraper"
DATA_PREFIX = "data/"
PRICE_ELIGIBLE_FILE = "price_eligible.json"
SNAPSHOT_PATTERN = re.compile(r"^data/([^/]+)/price_eligible\.json$")


def _storage_client(
    project: str | None, credentials_override: Any | None = None
) -> storage.Client:
    """Create a storage client using an optional explicit credential override."""
    if credentials_override is not None:
        return storage.Client(
            project=project or getattr(credentials_override, "project_id", None) or "gcs-data-reader",
            credentials=credentials_override,
        )
    credentials, detected_project = google.auth.default()
    return storage.Client(
        project=project or detected_project or "gcs-data-reader",
        credentials=credentials,
    )


def list_price_eligible_snapshots(
    bucket_name: str, project: str | None = None, credentials_override: Any | None = None
) -> list[str]:
    """Return available scraper snapshot timestamps in chronological order."""
    client = _storage_client(project, credentials_override)
    bucket = client.bucket(bucket_name)
    snapshots = {
        match.group(1)
        for blob in client.list_blobs(bucket, prefix=DATA_PREFIX)
        if (match := SNAPSHOT_PATTERN.match(blob.name))
    }
    return sorted(snapshots)


def load_price_eligible_snapshots(
    bucket_name: str,
    snapshots: Sequence[str] | None = None,
    project: str | None = None,
    credentials_override: Any | None = None,
) -> list[dict[str, Any]]:
    """Load price-eligible records and attach immutable source snapshot metadata."""
    client = _storage_client(project, credentials_override)
    bucket = client.bucket(bucket_name)
    selected = list(snapshots) if snapshots else list_price_eligible_snapshots(
        bucket_name, project, credentials_override
    )
    if not selected:
        raise ValueError(
            f"No {PRICE_ELIGIBLE_FILE} files found under gs://{bucket_name}/{DATA_PREFIX}"
        )

    observations: list[dict[str, Any]] = []
    for timestamp in selected:
        blob_name = f"{DATA_PREFIX}{timestamp}/{PRICE_ELIGIBLE_FILE}"
        blob = bucket.blob(blob_name)
        try:
            payload = json.loads(blob.download_as_text(encoding="utf-8"))
        except Exception as error:
            raise RuntimeError(f"Could not load gs://{bucket_name}/{blob_name}: {error}") from error
        if not isinstance(payload, list):
            raise ValueError(f"gs://{bucket_name}/{blob_name} must contain a JSON list")
        observations.extend(_attach_snapshot_metadata(payload, timestamp, blob_name))
    return observations


def _attach_snapshot_metadata(
    records: Iterable[Any], timestamp: str, source_file: str
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            observations.append(
                {"snapshot_timestamp": timestamp, "source_file": source_file, "source_index": index}
            )
            continue
        observation = dict(record)
        observation["snapshot_timestamp"] = timestamp
        observation["source_file"] = source_file
        observation["source_index"] = index
        observations.append(observation)
    return observations


def upload_report(
    bucket_name: str,
    report: dict[str, Any],
    timestamp: str,
    prefix: str = "analysis",
    project: str | None = None,
) -> list[str]:
    """Upload an immutable run report and replace the convenient latest copy."""
    clean_prefix = prefix.strip("/")
    if not clean_prefix:
        raise ValueError("Upload prefix cannot be empty")
    bucket = _storage_client(project).bucket(bucket_name)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    paths = [
        f"{clean_prefix}/{timestamp}/mad_analysis.json",
        f"{clean_prefix}/latest/mad_analysis.json",
    ]
    for path in paths:
        bucket.blob(path).upload_from_string(payload, content_type="application/json")
    return paths
