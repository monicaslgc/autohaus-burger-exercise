#!/usr/bin/env python3
"""Build the dealership-structure CSV (group > location > departments) from a small JSON facts file.

    python build_structure.py --facts <SKILL_DIR>/configs/autohaus-burger.structure.json --out dealership_structure.csv

The agent's job is to research the facts (contact page, imprint, footer, service/parts/fleet pages) and write them
into the facts file WITH a source URL per node. This script then does everything mechanical so the CSV is
consistent and importable: ids, parent names, depth, hierarchy path, one-line address, ';'-joined brands,
inherited address, a Google Maps search URL when the site has none, and strict integrity checks.

Facts file:
{
  "defaults": {"address": {"street","postal_code","city","country"}, "country_name": "Germany",
               "maps_query": "...", "website_url": "https://..."},
  "levels": {"group": 1, "location": 2, "department": 3},          # optional, these are the defaults
  "nodes": [ {"id","parent" (null for the single root),"level","name","department_type","brands":[...],
              "phone","fax","email","opening_hours" (OpenStreetMap syntax),"opening_hours_text",
              "google_maps_url" (omit to build a search URL from defaults.maps_query),
              "website_url","source_url","notes", "address": {...} (omit to inherit defaults)} ... ]
}
Rules enforced: exactly one root; parents listed before children; unique ids; level matches depth in the tree;
opening_hours looks like OSM syntax (warning only). Unknown/unpublished values stay EMPTY - never invent them.
"""
import argparse
import csv
import json
import re
import sys
from urllib.parse import quote_plus

COLS = ["id", "parent_id", "parent_name", "level", "depth", "hierarchy_path", "name", "department_type", "brands",
        "address", "street", "postal_code", "city", "country", "phone", "fax", "email", "opening_hours",
        "opening_hours_text_de", "google_maps_url", "website_url", "source_url", "notes"]
OSM_HOURS = re.compile(r"^(24/7|off|((Mo|Tu|We|Th|Fr|Sa|Su)(-(Mo|Tu|We|Th|Fr|Sa|Su))?(,(Mo|Tu|We|Th|Fr|Sa|Su))*)"
                       r"( (\d{2}:\d{2}-\d{2}:\d{2}(,\d{2}:\d{2}-\d{2}:\d{2})*|off))?"
                       r"(; ?((Mo|Tu|We|Th|Fr|Sa|Su)(-(Mo|Tu|We|Th|Fr|Sa|Su))?(,(Mo|Tu|We|Th|Fr|Sa|Su))*)"
                       r"( (\d{2}:\d{2}-\d{2}:\d{2}(,\d{2}:\d{2}-\d{2}:\d{2})*|off))?)*)$")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", required=True)
    ap.add_argument("--out", default="dealership_structure.csv")
    a = ap.parse_args()
    facts = json.load(open(a.facts, encoding="utf-8"))
    d = facts.get("defaults", {})
    levels = facts.get("levels", {"group": 1, "location": 2, "department": 3})
    errors, warns, out = [], [], {}
    for n in facts["nodes"]:
        nid = n["id"]
        if nid in out:
            errors.append(f"duplicate id {nid}")
            continue
        par = out.get(n.get("parent")) if n.get("parent") else None
        if n.get("parent") and par is None:
            errors.append(f"{nid}: parent {n['parent']!r} missing or listed after its child")
        if n["level"] not in levels:
            errors.append(f"{nid}: unknown level {n['level']!r}")
        depth = (par["_depth"] + 1) if par else 1
        if n["level"] in levels and levels[n["level"]] != depth:
            errors.append(f"{nid}: level {n['level']} expects depth {levels[n['level']]} but sits at depth {depth}")
        ad = n.get("address", d.get("address", {}))
        street, pc, city, country = (ad.get(k, "") for k in ("street", "postal_code", "city", "country"))
        full_addr = f"{street}, {pc} {city}, {d.get('country_name', country)}" if street else ""
        maps = n.get("google_maps_url") or (
            "https://www.google.com/maps/search/?api=1&query=" + quote_plus(d["maps_query"]) if d.get("maps_query") and street else "")
        oh = n.get("opening_hours", "")
        if oh and not OSM_HOURS.match(oh):
            warns.append(f"{nid}: opening_hours {oh!r} is not plain OSM syntax")
        row = dict.fromkeys(COLS, "")
        row.update(id=nid, parent_id=n.get("parent") or "", parent_name=par["name"] if par else "", level=n["level"],
                   depth=depth, hierarchy_path=(par["hierarchy_path"] + " > " if par else "") + n["name"], name=n["name"],
                   department_type=n.get("department_type", ""), brands=";".join(n.get("brands", [])), address=full_addr,
                   street=street, postal_code=pc, city=city, country=country, phone=n.get("phone", ""),
                   fax=n.get("fax", ""), email=n.get("email", ""), opening_hours=oh,
                   opening_hours_text_de=n.get("opening_hours_text", ""), google_maps_url=maps,
                   website_url=n.get("website_url", d.get("website_url", "")), source_url=n.get("source_url", ""),
                   notes=n.get("notes", ""))
        if not row["source_url"]:
            warns.append(f"{nid}: no source_url (every fact should be traceable)")
        row["_depth"] = depth
        out[nid] = row
    roots = [r for r in out.values() if not r["parent_id"]]
    if len(roots) != 1:
        errors.append(f"expected exactly 1 root, found {len(roots)}")
    for w in warns:
        print("WARN", w, file=sys.stderr)
    if errors:
        for e in errors:
            print("ERROR", e, file=sys.stderr)
        sys.exit(1)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out.values())
    print(f"wrote {len(out)} rows to {a.out} ({len(warns)} warnings)", file=sys.stderr)


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
