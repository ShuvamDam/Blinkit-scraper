#!/usr/bin/env python3
"""
Amazon.in sponsored-ad / keyword-placement audit for boAt vs Noise TWS
earbuds and wearables.

Uses the Apify actor scrapeify/amazon-scraper, which returns Amazon search
results (SERP) per keyword with a `position`, `page` and `isSponsored` flag
per item -- exactly what's needed to measure ad share-of-voice and
placement without touching Amazon's Ads API.

For each keyword this script runs the actor once (one keyword per run, per
its input schema), tags every result with a brand ("boAt" / "Noise" /
"Other: <guessed brand>") by matching whole words in the title, and writes:
  - raw_results/amazon/<keyword-slug>.json  (full actor output, per keyword)
  - amazon_ads_audit_results.csv            (flattened rows for analysis)
plus a printed summary (sponsored share-of-voice and average sponsored
position per brand, per keyword).

Requires APIFY_API_TOKEN in the environment.
"""
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN")
if not APIFY_TOKEN:
    sys.exit("APIFY_API_TOKEN not set in environment")

ACTOR = "scrapeify~amazon-scraper"
RUN_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
MARKETPLACE = "IN"

# Target SKUs for this audit (TWS + wearables, boAt vs Noise).
SKUS = [
    ("boAt", "Nirvana Ion ANC"),
    ("Noise", "Buds N2 Pro"),
    ("boAt", "Chrome Horizon"),
    ("boAt", "Lunar Vista"),
    ("Noise", "ColorFit Ultra 3"),
    ("Noise", "Alt Watch 1"),
]

# Exact-SKU searches: does the SKU itself show up sponsored, and which
# competitor SKUs/brands run conquesting ads against its own name?
SKU_KEYWORDS = [f"{brand} {model}" for brand, model in SKUS]

# Category keywords relevant to these specific SKUs (ANC TWS, calling-enabled
# wearables) -- where do these product lines show up on generic searches
# shoppers actually use, before they've picked a brand?
CATEGORY_KEYWORDS = [
    "wireless earbuds",
    "earbuds with anc",
    "bluetooth earbuds under 2000",
    "smartwatch with bluetooth calling",
    "smartwatch under 2000",
    "smartwatch under 3000",
]

# Brand-defense / conquesting keywords: who advertises against the other
# brand's name at the brand level (not just SKU level)?
BRAND_KEYWORDS = [
    "boat earbuds",
    "boat smartwatch",
    "noise earbuds",
    "noise smartwatch",
]

KEYWORDS = SKU_KEYWORDS + CATEGORY_KEYWORDS + BRAND_KEYWORDS

# Results per keyword (~2 SERP pages). Keep this modest: the actor bills
# per result ($8 / 1,000 as of the scrapeify listing), so
# len(KEYWORDS) * MAX_RESULTS results per full run.
MAX_RESULTS = 48

RAW_DIR = Path(__file__).parent / "raw_results" / "amazon"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def guess_brand(title):
    w = words(title)
    if "boat" in w:
        return "boAt"
    if "noise" in w and "noisefit" not in w:
        return "Noise"
    if "noisefit" in w:
        return "Noise"
    first = re.match(r"[A-Za-z0-9]+", title or "")
    return f"Other: {first.group(0)}" if first else "Other: ?"


def matched_sku(title):
    """Whole-word match against our 6 target SKUs (brand + model words all
    present in the title), same convention as the Blinkit audit's matcher."""
    tw = words(title)
    for brand, model in SKUS:
        if words(f"{brand} {model}").issubset(tw):
            return f"{brand} {model}"
    return ""


def slug(keyword):
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")


def run_keyword(keyword):
    payload = {"keyword": keyword, "marketplace": MARKETPLACE, "maxResults": MAX_RESULTS}
    params = {"token": APIFY_TOKEN, "memory": 1024, "timeout": 300}
    resp = requests.post(RUN_SYNC_URL, params=params, json=payload, timeout=400)
    if resp.status_code >= 400:
        return None, resp.status_code, resp.text
    return resp.json(), resp.status_code, None


def main():
    rows = []
    for keyword in KEYWORDS:
        print(f"=== {keyword!r} ===", flush=True)
        data, status, err = run_keyword(keyword)
        raw_path = RAW_DIR / f"{slug(keyword)}.json"
        if data is None:
            print(f"  FAILED: HTTP {status} {err}", flush=True)
            raw_path.write_text(err or "")
            continue

        raw_path.write_text(json.dumps(data, indent=2))
        print(f"  got {len(data)} results", flush=True)

        for item in data:
            title = item.get("title", "")
            rows.append({
                "keyword": keyword,
                "position": item.get("position"),
                "page": item.get("page"),
                "is_sponsored": "Yes" if item.get("isSponsored") else "No",
                "brand": guess_brand(title),
                "matched_sku": matched_sku(title),
                "asin": item.get("asin", ""),
                "title": title,
                "price": item.get("price", ""),
                "product_url": item.get("productUrl", ""),
            })

        time.sleep(1)

    out_path = Path(__file__).parent / "amazon_ads_audit_results.csv"
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "keyword", "position", "page", "is_sponsored", "brand", "matched_sku",
            "asin", "title", "price", "product_url",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {out_path}")

    print_summary(rows)


def print_summary(rows):
    print("\n--- SUMMARY ---")

    print("\nSponsored share-of-voice by brand (sponsored slots only):")
    sponsored = [r for r in rows if r["is_sponsored"] == "Yes"]
    counts = {}
    for r in sponsored:
        counts[r["brand"]] = counts.get(r["brand"], 0) + 1
    total = len(sponsored) or 1
    for brand, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {brand}: {n} sponsored slots ({100 * n / total:.1f}%)")

    print("\nAverage sponsored position by brand (lower = more prominent):")
    for brand in ("boAt", "Noise"):
        positions = [r["position"] for r in sponsored if r["brand"] == brand and r["position"] is not None]
        if positions:
            print(f"  {brand}: {sum(positions) / len(positions):.1f} (n={len(positions)})")
        else:
            print(f"  {brand}: no sponsored placements found")

    print("\nSKU-level conquesting: competitor sponsored ads on each SKU's own name search:")
    sku_keyword_brand = {f"{brand} {model}".lower(): brand for brand, model in SKUS}
    found_sku_conquest = False
    for r in sponsored:
        own_brand = sku_keyword_brand.get(r["keyword"].lower())
        if own_brand and r["brand"] != own_brand:
            found_sku_conquest = True
            print(f"  '{r['keyword']}': sponsored slot at position {r['position']} "
                  f"taken by {r['brand']} -- {r['title'][:70]}")
    if not found_sku_conquest:
        print("  None")

    print("\nBrand-level conquesting: competitor sponsored ads on the other brand's name search:")
    for kw, target_brand in (("boat earbuds", "Noise"), ("boat smartwatch", "Noise"),
                              ("noise earbuds", "boAt"), ("noise smartwatch", "boAt")):
        hits = [r for r in sponsored if r["keyword"] == kw and r["brand"] == target_brand]
        if hits:
            print(f"  '{kw}': {target_brand} bought {len(hits)} sponsored slot(s) "
                  f"(positions {[h['position'] for h in hits]})")
    print("  (nothing printed above for a keyword means no conquesting ad found)")


if __name__ == "__main__":
    main()
