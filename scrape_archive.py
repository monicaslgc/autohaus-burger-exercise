#!/usr/bin/env python3
"""Scraper for the OLD listing archive on https://autohaus-burger.de/autos/<id>/  (139 pages).

Run:  python scrape_archive.py [--inventory inventory.json] [--out archived_listings.json]

These pages are WordPress "portfolio" posts (type avada_portfolio), all published 2026-06-01, not linked from
the live site. Each one only exposes: title (with make/model/variant + body type), gross price, category
(Gebraucht = used / Neu = new) and ONE image (Yoast og:image). Mileage, year and equipment are NOT on these pages, and the image URL returns HTTP 404 (recorded in `image_http_status`).
The WordPress REST API returns all of them in 2 requests (X-WP-Total = 139), so no per-page crawling is needed.

Each record keeps the same key names as inventory.json where the data exists, plus:
  status = "archive_snapshot", snapshot_date, and `title_matches_current_listings` (URLs in inventory.json
  whose title is identical) so a consumer can tell re-listed cars from vanished ones.
"""
import argparse
import html
import json
import re
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://autohaus-burger.de"
UA = os.environ.get("SCRAPER_USER_AGENT") or "Mozilla/5.0 (compatible; SeezCandidateExercise/1.0; polite scraper, 1 req/s)"
MAKES = {"volkswagen": "Volkswagen", "audi": "Audi", "skoda": "Škoda", "škoda": "Škoda", "cupra": "CUPRA", "seat": "SEAT"}
CATEGORY = {"gebraucht": "used", "neu": "new"}



_DISALLOWED = None


def robots_allows(url):
    """Honour robots.txt: never request a path that is disallowed for User-agent: * (this site disallows nothing)."""
    global _DISALLOWED
    if _DISALLOWED is None:
        _DISALLOWED = []
        try:
            req = urllib.request.Request(BASE + "/robots.txt", headers={"User-Agent": UA})
            body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            for_all = False
            for line in body.splitlines():
                line = line.split("#")[0].strip()
                if line.lower().startswith("user-agent:"):
                    for_all = line.split(":", 1)[1].strip() == "*"
                elif for_all and line.lower().startswith("disallow:") and line.split(":", 1)[1].strip():
                    _DISALLOWED.append(line.split(":", 1)[1].strip())
        except Exception:
            pass
    path = url[len(BASE):] if url.startswith(BASE) else ""
    return not any(path.startswith(d) for d in _DISALLOWED)


def fetch(url, delay):
    if not robots_allows(url):
        raise SystemExit(f"robots.txt disallows {url}; not requesting it")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
        total = int(r.headers.get("X-WP-Total", 0))
    time.sleep(delay)
    return data, total


def image_status(url, delay):
    """HTTP status of the image URL (the archive's images are dead links: 404)."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        code = urllib.request.urlopen(req, timeout=20).status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = None
    time.sleep(delay)
    return code


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--inventory", default="inventory.json")
    ap.add_argument("--out", default="archived_listings.json")
    a = ap.parse_args()

    cats = {c["id"]: c["name"] for c in fetch(f"{BASE}/wp-json/wp/v2/portfolio_category?per_page=100", a.delay)[0]}
    items, page = [], 1
    while True:
        chunk, total = fetch(f"{BASE}/wp-json/wp/v2/avada_portfolio?per_page=100&page={page}", a.delay)
        items += chunk
        if len(items) >= total or not chunk:
            break
        page += 1
    print(f"{len(items)} archive items (site reports {total})", file=sys.stderr)

    inv = json.load(open(a.inventory, encoding="utf-8")) if a.inventory else []
    by_title = {}
    for c in inv:
        by_title.setdefault(norm(c["title"]), []).append(c["listing_url"])
    models = {}  # make -> set(model) learned from the live inventory, to split "Golf VIII GTE ..." sensibly
    for c in inv:
        models.setdefault(c["make"], set()).add(c["model"])

    out = []
    for x in items:
        c = x["content"]["rendered"]
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", c, re.S)
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", c, re.S)
        vat = re.search(r"inkl\.\s*([\d,]+)\s*%\s*MwSt", html.unescape(c))
        full = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else html.unescape(x["title"]["rendered"])
        pr = re.search(r"([\d.]+),(\d\d)\s*EUR", h2.group(1)) if h2 else None
        body = re.search(r"\s(\d)-Türer$", full)
        title = re.sub(r"\s+\d-Türer$", "", full)  # same form as titles in inventory.json (make + model + variant)
        tok = title.split(" ", 1)
        make = MAKES.get(tok[0].lower(), tok[0])
        rest = tok[1] if len(tok) > 1 else ""
        model = None
        for m in sorted(models.get(make, ()), key=len, reverse=True):  # longest known model name first
            if m and norm(rest).startswith(norm(m)):
                model = m
                break
        if model is None and rest:
            model = rest.split(" ")[0]
        variant = rest
        if model:
            for t in model.split():
                variant = re.sub(r"\s*".join(re.escape(ch) for ch in t), "", variant, count=1, flags=re.I).strip()
        gen = re.match(r"^([IVX]{2,5})(?=\s|$)\s*", variant)
        if gen:
            variant = variant[gen.end():]
        variant = re.sub(r"\s+", " ", variant).strip(" -/")
        pw = re.search(r"(\d+)\s*kW\s*\((\d+)\s*PS\)", title)
        y = x.get("yoast_head_json") or {}
        og = (y.get("og_image") or [{}])[0]
        cond = next((CATEGORY.get(cats.get(i, "").lower()) for i in x["portfolio_category"] if cats.get(i, "").lower() in CATEGORY), None)
        out.append({
            "listing_url": x["link"],
            "source_id": x["slug"],
            "status": "archive_snapshot",
            "snapshot_date": x["modified"][:10],
            "title": title,
            "condition": cond,
            "make": make,
            "model": model,
            "generation": gen.group(1) if gen else None,
            "variant": variant or None,
            "doors": int(body.group(1)) if body else None,
            "price": {"amount": int(pr.group(1).replace(".", "")) if pr else None, "currency": "EUR",
                      "vat_note": f"inkl. {vat.group(1)}% MwSt." if vat else None,
                      "display": html.unescape(re.sub(r"<[^>]+>", "", h2.group(1))).strip() if h2 else None},
            "power_kw": int(pw.group(1)) if pw else None,
            "power_ps": int(pw.group(2)) if pw else None,
            "images": [og["url"]] if og.get("url") else [],
            "image_count": 1 if og.get("url") else 0,
            "image_http_status": image_status(og["url"], a.delay) if og.get("url") else None,
            "year": None, "first_registration": None, "mileage_km": None, "equipment": [],
            "title_matches_current_listings": by_title.get(norm(title), []),
            "wp_post_id": x["id"],
        })
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(out)} records to {a.out}", file=sys.stderr)


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
