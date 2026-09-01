#!/usr/bin/env python3
"""Fetch the 2 additional ColorFit SKUs for all 10 locations and merge the
results into the existing raw_results/*.json files, without re-fetching the
other 10 SKUs already collected."""
import json
import os
import random
import sys
import time
from pathlib import Path

import requests

from blinkit_audit import LOCATIONS, ACTOR, RUN_SYNC_URL, RAW_DIR

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN")
if not APIFY_TOKEN:
    sys.exit("APIFY_API_TOKEN not set in environment")

QUERIES = ["Noise ColorFit Icon 4", "Noise ColorFit Ultra 3"]


def run_location(locality):
    payload = {
        "searchQueries": QUERIES,
        "locations": [locality],
        "productsLimit": 25,
        "includeEtaDetails": True,
    }
    params = {"token": APIFY_TOKEN, "memory": 1024, "timeout": 300}
    resp = requests.post(RUN_SYNC_URL, params=params, json=payload, timeout=400)
    if resp.status_code >= 400:
        return None, resp.status_code, resp.text
    return resp.json(), resp.status_code, None


for pincode, city, locality in LOCATIONS:
    print(f"=== {city} ({pincode}) -> {locality} ===", flush=True)
    data, status, err = run_location(locality)
    raw_path = RAW_DIR / f"{pincode}_{city}.json"
    existing = json.loads(raw_path.read_text())
    if data is None:
        print(f"  FAILED: HTTP {status} {err}", flush=True)
        continue
    print(f"  got {len(data)} new records, merging into {len(existing)} existing", flush=True)
    merged = existing + data
    raw_path.write_text(json.dumps(merged, indent=2))
    time.sleep(random.uniform(2, 4))

print("done")
