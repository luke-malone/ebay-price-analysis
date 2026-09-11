# eBay iPhone price analysis

Robust, reproducible MAD-based analysis of eBay iPhone listings collected by a
separate scraper. Raw data remains in Google Cloud Storage; this repository does
not store credentials or scraped snapshots.

## Setup

Python 3.12+ and [Application Default Credentials](https://cloud.google.com/docs/authentication/provide-credentials-adc#local-dev)
are required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
gcloud auth application-default login
```

## Run

Analyse every available snapshot (using the latest observation of each eBay item
in the core calculation):

```powershell
python main.py
```

Or constrain the source data while checking a new scraper run:

```powershell
python main.py --snapshot 2026-09-11T19-50-03Z --min-sample-size 5 --z-threshold 3.5
```

If your ADC setup has no default project, pass one explicitly (the bucket still
remains independently configurable): `python main.py --project YOUR_PROJECT_ID`.

The report is written to `output/mad_analysis.json`. It records exclusions,
repeated observations, methodology, group median/MAD, outlier decisions, and
three robust market-price estimate levels: `model`, `model_storage`, and
`model_storage_colour`. The estimate is not presented as a true market price.

To recompute using all newly available scraper snapshots and publish the report
back to the same bucket:

```powershell
python main.py --upload
```

This uploads an immutable report to `gs://BUCKET/analysis/TIMESTAMP/` and
replaces `gs://BUCKET/analysis/latest/mad_analysis.json`. Uploading is opt-in;
without `--upload`, the program only reads GCS and writes locally.
