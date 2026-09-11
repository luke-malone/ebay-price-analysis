# eBay iPhone price analysis

Updatable MAD (Median Absolute Deviation) filter ---> mean price for eBay iPhone listing prices collected by a
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

To analyse and update all estimated market prices for model, model + colour, model + colour + storage):

```powershell
python main.py
```

Or constrain the source data while checking a new scraper run:

```powershell
python main.py --snapshot 2026-09-11T19-50-03Z --min-sample-size 5 --z-threshold 3.5
```



The report is written to `output/mad_analysis.json`. It records exclusions,
repeated observations, methodology, group median/MAD, outlier decisions, and
three robust market-price estimate levels: `model`, `model_storage`, and
`model_storage_colour`. The estimate is not presented as a true market price.

To update using all newly available scraper snapshots and publish the report
back to the same bucket on GCP.

```powershell
python main.py --upload
```

This uploads an immutable report to `gs://BUCKET/analysis/TIMESTAMP/` and
replaces `gs://BUCKET/analysis/latest/mad_analysis.json`. Uploading is opt-in;
without `--upload`, the program only reads GCS and writes locally to mad_analysis.json :)

## Future 
Developing user interface to search for undervalued listings depending on user criteria (model, colour, storage, discount from MAD mean price)...
