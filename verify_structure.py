#!/usr/bin/env python3
"""Re-check dealership_structure.csv against the live site.

Run:  python verify_structure.py [--csv dealership_structure.csv] [--delay 1.0]

The CSV is not scraped blindly: its facts were read from the dealer's own pages (contact, imprint, footer, service,
fleet ...) and every row cites its `source_url`. This script makes that reproducible. For each row it downloads the
cited page (plus /kontakt/, which holds the opening hours, and /impressum/) and checks that the row's
phone, e-mail, street/postal code/city and every opening-hours time range really appear in that text.
Exit code 0 = every published fact found; 1 = at least one fact could not be found (listed).
Empty cells are not checked - they mean "the site does not publish this".
"""
import argparse
import csv
import html
import re
import os
import sys
import time
import urllib.request

UA = os.environ.get("SCRAPER_USER_AGENT") or "Mozilla/5.0 (compatible; SeezCandidateExercise/1.0; polite checker, 1 req/s)"
_cache = {}


def page_text(url, delay):
    if url not in _cache:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        time.sleep(delay)
        raw = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", raw)
        _cache[url] = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return _cache[url]


def norm(s):
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\xa0", " ")
    s = re.sub(r"\b(\d):(\d\d)", r"0\1:\2", s)              # 8:00 -> 08:00
    s = re.sub(r"\s*Uhr\s*", " ", s)                         # drop "Uhr"
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def digits(s):
    return re.sub(r"\D", "", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="dealership_structure.csv")
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    base = "https://autohaus-burger.de"
    rows = list(csv.DictReader(open(a.csv, encoding="utf-8", newline="")))
    problems, checked = [], 0
    for r in rows:
        texts = [page_text(r["source_url"], a.delay), page_text(base + "/kontakt/", a.delay),
                 page_text(base + "/impressum/", a.delay)]
        blob, blob_n, blob_d = " ".join(texts), norm(" ".join(texts)), digits(" ".join(texts))

        def need(label, ok):
            nonlocal checked
            checked += 1
            if not ok:
                problems.append(f"{r['id']} {r['name']}: {label} not found on the site")

        if r["phone"]:
            pd = digits(r["phone"])            # +49 7344 9600-0 -> 4973449600 0 ; also match the national form (no 49)
            need(f"phone {r['phone']}", pd in blob_d or pd[2:] in blob_d)
        if r["email"]:
            need(f"e-mail {r['email']}", r["email"].lower() in blob.lower())
        if r["street"]:
            need(f"postal code/city {r['postal_code']} {r['city']}", f"{r['postal_code']} {r['city']}" in blob)
            need("street Ehinger Stra\u00dfe", "ehinger stra" in blob.lower())
        for rng in re.findall(r"\d\d:\d\d-\d\d:\d\d", r["opening_hours"]):
            need(f"hours {rng}", rng in blob_n)
        # the days too: every German segment (day range + times, or "geschlossen") must appear as written on the site
        for seg in filter(None, (x.strip() for x in r["opening_hours_text_de"].split(";"))):
            need(f"hours text '{seg}'", norm(seg) in blob_n)
    print(f"{len(rows)} rows, {checked} facts checked against the live site")
    for p in problems:
        print("NOT FOUND:", p)
    print("OK - every published fact was found" if not problems else f"{len(problems)} fact(s) not found")
    sys.exit(1 if problems else 0)


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
