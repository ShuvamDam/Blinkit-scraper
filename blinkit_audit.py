#!/usr/bin/env python3
"""
Blinkit delivery-time / availability audit for boAt vs Noise SKUs.

Uses the Apify actor krazee_kaushik/blinkit-product-results-scraper (chosen
after confirming it returns live, real Blinkit search results: price, stock,
ETA, geocoded location). Direct requests to blinkit.com from this environment
are blocked at the network edge (403 via curl, connection reset via headless
Chromium) so scraping goes through Apify's actor infrastructure instead.

Requires APIFY_API_TOKEN in the environment.
"""
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

import requests

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN")
if not APIFY_TOKEN:
    sys.exit("APIFY_API_TOKEN not set in environment")

ACTOR = "krazee_kaushik~blinkit-product-results-scraper"
RUN_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"

# Final SKU list. Several original names from the task brief do not exist in
# Blinkit's live catalog (verified by direct search); each such case was
# confirmed with the requester and replaced with a real product below. See
# NOTES.md for the full substitution log.
SKUS = [
    ("boAt", "Airdopes 311 Pro"),          # replaces "Airdopes Prime 701 ANC" (not found)
    ("boAt", "Nirvana Ion ANC"),
    ("boAt", "Airdopes 141 Elite ANC"),
    ("boAt", "Chrome Horizon Smart Watch"),  # replaces "Wave Storm Verge" (not found)
    ("boAt", "Lunar Vista"),
    ("Noise", "Buds VS102 Plus"),           # replaces "Buds VS104 Max" (not found)
    ("Noise", "Buds N2 Pro"),
    ("Noise", "Alt Buds"),
    ("Noise", "Alt Watch 1"),               # replaces "ColorFit Icon 4" (line not found)
    ("Noise", "NoiseFit Twist Go"),         # replaces "ColorFit Ultra 3" (line not found)
]

# Pincode -> a real, well-known serviceable Blinkit locality in that city.
# The actor geocodes a free-text location string (no raw lat/long input in
# its schema); these localities were supplied by the requester.
LOCATIONS = [
    ("400001", "Mumbai", "Bandra West, Mumbai"),
    ("560001", "Bangalore", "Koramangala, Bangalore"),
    ("110001", "Delhi", "Connaught Place, New Delhi"),
    ("122001", "Gurgaon", "Cyber City, Gurgaon"),
    ("160001", "Chandigarh", "Sector 17, Chandigarh"),
    ("411001", "Pune", "Koregaon Park, Pune"),
    ("302001", "Jaipur", "Malviya Nagar, Jaipur"),
    ("226001", "Lucknow", "Hazratganj, Lucknow"),
    ("452001", "Indore", "Vijay Nagar, Indore"),
    ("380001", "Ahmedabad", "Navrangpura, Ahmedabad"),
]

PRODUCTS_LIMIT = 25
RAW_DIR = Path(__file__).parent / "raw_results"
RAW_DIR.mkdir(exist_ok=True)


def norm(s):
    return "".join(ch.lower() for ch in s if ch.isalnum())


def matches_sku(product_name, sku_name):
    """A product name matches a SKU if every significant token of the SKU
    name appears in the product name (case/space/punct-insensitive)."""
    pn = norm(product_name)
    tokens = [t for t in sku_name.lower().split() if len(norm(t)) > 0]
    return all(norm(t) in pn for t in tokens)


def run_location(locality):
    payload = {
        "searchQueries": [f"{brand} {model}" for brand, model in SKUS],
        "locations": [locality],
        "productsLimit": PRODUCTS_LIMIT,
        "includeEtaDetails": True,
    }
    params = {"token": APIFY_TOKEN, "memory": 1024, "timeout": 300}
    resp = requests.post(RUN_SYNC_URL, params=params, json=payload, timeout=400)
    if resp.status_code >= 400:
        return None, resp.status_code, resp.text
    return resp.json(), resp.status_code, None


def pick_best(items, brand, model):
    target = f"{brand} {model}"
    candidates = [it for it in items if matches_sku(it.get("name", ""), model) and brand.lower() in it.get("name", "").lower()]
    if not candidates:
        return None
    # Prefer in-stock, then lowest product_id (stable tie-break)
    candidates.sort(key=lambda it: (it.get("out_of_stock", True), str(it.get("product_id", ""))))
    return candidates[0], len(candidates)


def main():
    rows = []
    for pincode, city, locality in LOCATIONS:
        print(f"=== {city} ({pincode}) -> {locality} ===", flush=True)
        data, status, err = run_location(locality)
        raw_path = RAW_DIR / f"{pincode}_{city}.json"
        if data is None:
            print(f"  FAILED: HTTP {status} {err}", flush=True)
            raw_path.write_text(err or "")
            for brand, model in SKUS:
                rows.append({
                    "pincode": pincode, "city": city, "brand": brand, "sku": model,
                    "available": "No", "delivery_time": "Not available", "price": "",
                    "in_stock": "No", "notes": f"Location/actor run failed: HTTP {status}",
                })
            continue

        raw_path.write_text(json.dumps(data, indent=2))
        print(f"  got {len(data)} product records", flush=True)

        for brand, model in SKUS:
            result = pick_best(data, brand, model)
            if result is None:
                rows.append({
                    "pincode": pincode, "city": city, "brand": brand, "sku": model,
                    "available": "No", "delivery_time": "Not available", "price": "",
                    "in_stock": "No", "notes": "Not found in search results",
                })
                continue
            item, n_variants = result
            eta = item.get("eta_in_minutes")
            delivery_time = f"{eta} mins" if eta is not None else "Not available"
            in_stock = "No" if item.get("out_of_stock") else "Yes"
            notes = f"{n_variants} variant(s) matched; showing {item.get('name')}" if n_variants > 1 else ""
            rows.append({
                "pincode": pincode, "city": city, "brand": brand, "sku": model,
                "available": "Yes", "delivery_time": delivery_time,
                "price": item.get("price", ""), "in_stock": in_stock, "notes": notes,
            })

        time.sleep(random.uniform(2, 4))

    out_path = Path(__file__).parent / "blinkit_audit_results.csv"
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "pincode", "city", "brand", "sku", "available",
            "delivery_time", "price", "in_stock", "notes",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {out_path}")

    print_summary(rows)


def print_summary(rows):
    def avg_eta(brand):
        etas = []
        for r in rows:
            if r["brand"] != brand or r["delivery_time"] == "Not available":
                continue
            try:
                etas.append(int(r["delivery_time"].split()[0]))
            except (ValueError, IndexError):
                pass
        return sum(etas) / len(etas) if etas else None

    print("\n--- SUMMARY ---")
    for brand in ("boAt", "Noise"):
        avg = avg_eta(brand)
        print(f"Average delivery time ({brand}): {avg:.1f} mins" if avg is not None else f"Average delivery time ({brand}): n/a")

    print("\nPincodes where one brand fully unavailable but the other isn't:")
    by_loc = {}
    for r in rows:
        by_loc.setdefault((r["pincode"], r["city"]), {"boAt": [], "Noise": []})[r["brand"]].append(r["available"])
    found_any = False
    for (pincode, city), avail in by_loc.items():
        boat_avail = "Yes" in avail["boAt"]
        noise_avail = "Yes" in avail["Noise"]
        if boat_avail != noise_avail:
            found_any = True
            print(f"  {city} ({pincode}): boAt available={boat_avail}, Noise available={noise_avail}")
    if not found_any:
        print("  None")

    print("\nPrice differences for the same SKU across pincodes:")
    by_sku = {}
    for r in rows:
        if r["price"] == "":
            continue
        by_sku.setdefault((r["brand"], r["sku"]), {}).setdefault(r["price"], []).append(f"{r['city']} ({r['pincode']})")
    for (brand, sku), price_map in by_sku.items():
        if len(price_map) > 1:
            print(f"  {brand} {sku}:")
            for price, cities in price_map.items():
                print(f"    {price}: {', '.join(cities)}")


if __name__ == "__main__":
    main()
