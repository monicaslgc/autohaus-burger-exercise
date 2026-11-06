#!/usr/bin/env python3
"""Quality gate for an inventory.json produced by a dealer scraper.

Usage:  python validate_inventory.py inventory.json [--expect 126] [--structure dealership_structure.csv]

Exit code 0 = no errors (warnings are fine), 1 = at least one error. Run it after EVERY scrape.
Checks: count vs expectation, duplicates, required keys, numeric types, impossible values,
missing-rate per field (so you can tell "site does not publish it" from "my parser missed it"),
image URL sanity, new/used mix, hierarchy integrity of the structure CSV.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter

REQUIRED = ["listing_url", "condition", "make", "model", "variant", "price", "mileage_km", "equipment", "images"]
ESSENTIAL = {"listing_url", "condition", "make", "model", "price", "images"}  # empty = ERROR; the rest only warns (a site may not publish it)
NUMERIC = ["year", "mileage_km", "power_kw", "power_ps", "engine_displacement_ccm"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory")
    ap.add_argument("--expect", type=int, help="number of vehicles the site itself shows (listing + sitemap)")
    ap.add_argument("--structure", help="dealership_structure.csv to check too")
    a = ap.parse_args()
    errors, warns = [], []
    d = json.load(open(a.inventory, encoding="utf-8"))
    n = len(d)
    print(f"{n} vehicles; conditions={dict(Counter(c.get('condition') for c in d))}")

    if n == 0:
        errors.append("empty inventory: no vehicles")
    if a.expect is not None and n != a.expect:
        errors.append(f"count {n} != expected {a.expect} (did you union listing + sitemap + new-car page?)")
    if len({c.get("listing_url") for c in d}) != n:
        errors.append("duplicate listing_url")
    if "new" not in {c.get("condition") for c in d}:
        warns.append("no 'new' cars at all - check the new-car page/sitemap before assuming the dealer has none")

    for i, c in enumerate(d):
        tag = c.get("listing_url", f"#{i}")
        for k in REQUIRED:
            if k not in c or c[k] in (None, "", []):
                if k in ("mileage_km",) and c.get("condition") == "new":
                    continue
                (errors if k in ESSENTIAL else warns).append(f"{tag}: empty {k}")
        for k in NUMERIC:
            if c.get(k) is not None and not isinstance(c[k], (int, float)):
                errors.append(f"{tag}: {k} is {type(c[k]).__name__}, must be number")
        p = (c.get("price") or {}).get("amount")
        if "price" in ESSENTIAL and p is None and c.get("price") not in (None, "", []):
            errors.append(f"{tag}: price has no amount")
        if p is not None and (not isinstance(p, (int, float)) or p <= 0):
            errors.append(f"{tag}: bad price {p!r}")
        if isinstance(p, float) and abs(p - round(p)) > 0 and abs(p * 100 - round(p * 100)) > 1e-6:
            warns.append(f"{tag}: odd price {p}")
        if isinstance(p, (int, float)) and p and (p < 1000 or p > 500000):
            warns.append(f"{tag}: price {p} outside 1k-500k")
        y = c.get("year")
        if y is not None and not (1990 <= y <= 2030):
            errors.append(f"{tag}: year {y}")
        if c.get("condition") == "used" and (c.get("mileage_km") or 0) < 10:
            warns.append(f"{tag}: used car with {c.get('mileage_km')} km")
        imgs = c.get("images") or []
        if len(imgs) != len(set(imgs)):
            errors.append(f"{tag}: duplicate image URLs")
        bad = [u for u in imgs if not re.match(r"https?://", u)]
        if bad:
            errors.append(f"{tag}: non-absolute image URL {bad[0]}")
        if not str(c.get("listing_url", "")).startswith("http"):
            errors.append(f"{tag}: listing_url not absolute")

    print("\nmissing-rate per field (high = site does not publish it OR parser miss; open one page to decide):")
    keys = sorted({k for c in d for k in c})
    for k in keys:
        miss = sum(1 for c in d if c.get(k) in (None, "", [], {}))
        if miss:
            print(f"  {k:28s} {miss:4d}/{n} ({miss * 100 // n}%)")

    if a.structure:
        rows = list(csv.DictReader(open(a.structure, encoding="utf-8")))
        ids = {r["id"] for r in rows}
        for r in rows:
            if r["parent_id"] and r["parent_id"] not in ids:
                errors.append(f"structure: {r['id']} parent {r['parent_id']} missing")
        if sum(1 for r in rows if not r["parent_id"]) != 1:
            errors.append("structure: expected exactly one root row")
        print(f"\nstructure rows: {len(rows)}, levels={dict(Counter(r['level'] for r in rows))}")

    print(f"\nwarnings: {len(warns)}" + ("" if not warns else "  (first 8)"))
    for w in warns[:8]:
        print("  W", w)
    print(f"errors: {len(errors)}")
    for e in errors[:20]:
        print("  E", e)
    sys.exit(1 if errors else 0)


def _bootstrap():
    """Make the script usable on any machine: clear error on old Python, UTF-8 output on any terminal."""
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9 or newer is required (found %s)" % sys.version.split()[0])
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _bootstrap()
    main()
