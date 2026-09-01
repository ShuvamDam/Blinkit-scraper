#!/usr/bin/env python3
"""Regenerate the final CSV from all raw_results/*.json using the corrected
whole-word matcher, and print the summary. Supersedes the CSV/summary the
live blinkit_audit.py process wrote with its old (buggy) matcher."""
import csv
import json
from pathlib import Path

from blinkit_audit import SKUS, LOCATIONS, pick_best, print_summary

RAW_DIR = Path(__file__).parent / "raw_results"

rows = []
for pincode, city, locality in LOCATIONS:
    raw_path = RAW_DIR / f"{pincode}_{city}.json"
    data = json.loads(raw_path.read_text())
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

out_path = Path(__file__).parent / "blinkit_audit_results.csv"
with out_path.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "pincode", "city", "brand", "sku", "available",
        "delivery_time", "price", "in_stock", "notes",
    ])
    writer.writeheader()
    writer.writerows(rows)
print(f"Wrote {len(rows)} rows to {out_path}")
print_summary(rows)
