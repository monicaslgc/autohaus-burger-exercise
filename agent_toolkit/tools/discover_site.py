#!/usr/bin/env python3
"""Step 1 of the dealer-onboarding playbook: map a dealer website before writing a scraper.

Usage:  python discover_site.py https://dealer.example [--delay 1.0] [--sample 3]

Prints (stdlib only, throttled, ~10-20 requests):
  - robots.txt rules that matter + sitemap URLs
  - sitemap URLs grouped by path "shape" (e.g. /fahrzeuge/<digits>, /fahrzeuge/<alnum>) with counts
  - candidate inventory listing pages (links containing vehicle-ish words) and pagination hints
  - on a sample of detail pages: which structured data exists (JSON-LD @type, price, image count)
  - external inventory sources (mobile.de, autoscout24, ...) and tell-tale platform hints (WordPress, REST API)
The goal is to know BEFORE scraping: where cars live, how many there are, and which data source is cleanest.
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
from collections import Counter, defaultdict
from urllib.parse import urljoin, urlparse

UA = os.environ.get("SCRAPER_USER_AGENT") or "Mozilla/5.0 (compatible; DealerDiscovery/1.0; polite, throttled)"
VEHICLE_WORDS = re.compile(r"fahrzeug|gebraucht|neuwagen|vehicle|inventory|used|new-cars|stock|angebot|occasion|voiture|coches|carro|viatura|usado|veiculo|automovel|coche|ocasion|segunda-mano", re.I)
EXTERNAL = re.compile(r"mobile\.de|autoscout24|autouncle|porscheinformatik|dasweltauto|cargurus|autotrader", re.I)


def get(url, delay):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
        time.sleep(delay)
        return body
    except urllib.error.HTTPError as e:
        return None if e.code in (404, 410) else None
    except Exception as e:
        print(f"  ! {url}: {e}", file=sys.stderr)
        return None


def shape(path):
    """/fahrzeuge/09384/ -> /fahrzeuge/<digits>/ ; /fahrzeuge/hk2332/ -> /fahrzeuge/<alnum>/"""
    parts = []
    for seg in path.strip("/").split("/"):
        if re.fullmatch(r"\d+(-\d+)?", seg):
            parts.append("<digits>")
        elif re.fullmatch(r"[a-z]{1,3}\d{2,}", seg, re.I):
            parts.append("<alnum-id>")
        elif re.fullmatch(r"[0-9a-f-]{20,}", seg):
            parts.append("<uuid>")
        else:
            parts.append(seg)
    if len(parts) >= 4 and parts[-1] in ("<digits>", "<alnum-id>", "<uuid>"):
        # /pt/carro-usado/audi/a3/a3-40-tfsi/118087/ -> keep the 2-segment prefix, the text slugs in between are data
        parts = parts[:2] + ["<slug>"] * (len(parts) - 3) + parts[-1:]
    return "/" + "/".join(parts) + "/"


def sitemap_locs(url, delay, seen=None, depth=0):
    seen = seen if seen is not None else set()
    if url in seen or depth > 2:
        return []
    seen.add(url)
    body = get(url, delay) or ""
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
    out = []
    for loc in locs:
        if loc.endswith(".xml"):
            out += sitemap_locs(loc, delay, seen, depth + 1)
        else:
            out.append(loc)
    return out


def jsonld_types(page):
    types = []
    for blob in re.findall(r"application/ld\+json[^>]*>(.*?)</script>", page, re.S):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                t = x.get("@type")
                types += t if isinstance(t, list) else ([t] if t else [])
                stack += [v for v in x.values() if isinstance(v, (dict, list))]
            elif isinstance(x, list):
                stack += x
    return types


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--sample", type=int, default=3, help="detail pages to inspect per URL shape")
    a = ap.parse_args()
    site_url = a.url.rstrip("/")                      # the page the user gave (may be /pt/, /en/ ...)
    host = urlparse(site_url).netloc
    base = f"{urlparse(site_url).scheme}://{host}"    # robots.txt and sitemaps live at the site root

    print(f"== {site_url}  (site root {base})")
    robots = get(base + "/robots.txt", a.delay) or ""
    dis = [l for l in robots.splitlines() if l.lower().startswith(("disallow", "crawl-delay", "user-agent"))]
    print("robots.txt:", "; ".join(dis[:8]) or "(none)")
    sm_urls = re.findall(r"(?im)^sitemap:\s*(\S+)", robots) or [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    locs = []
    for s in sm_urls:
        locs += sitemap_locs(s, a.delay)
    locs = list(dict.fromkeys(locs))
    print(f"sitemap URLs: {len(locs)}")

    groups = defaultdict(list)
    for u in locs:
        p = urlparse(u)
        if p.netloc == host:
            groups[shape(p.path)].append(u)
    print("\nURL shapes in sitemaps (look for the one that is the inventory):")
    for sh, us in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:15]:
        flag = "  <-- vehicle-like" if VEHICLE_WORDS.search(sh) and len(us) > 5 else ""
        print(f"  {len(us):4d}  {sh}{flag}")

    home = get(site_url + "/", a.delay) or ""
    print("\nplatform hints:", ", ".join(h for h, pat in [("WordPress", "wp-content"), ("Avada", "Avada"),
          ("Next.js", "__NEXT_DATA__"), ("Nuxt", "__NUXT__"), ("Shopify", "cdn.shopify")] if re.search(pat, home)) or "-")
    print("WP REST API:", "yes" if re.search(r"wp-json", home) else "no/unknown")
    links = sorted({urljoin(site_url + "/", html.unescape(h)).split("#")[0] for h in re.findall(r'href="([^"]+)"', home)})
    inv = [l.rstrip("/") + "/" for l in links
           if urlparse(l).netloc == host and VEHICLE_WORDS.search(urlparse(l).path)
           and "<" not in shape(urlparse(l).path) and "feed" not in l]  # index pages only, not single cars
    inv = list(dict.fromkeys(inv))
    print("\ncandidate inventory pages from homepage:")
    for l in inv[:15]:
        print("  ", l)
    ext = sorted({l for l in links if EXTERNAL.search(l)})
    print("external inventory sources:", ext[:8] or "-")

    print("\nlisting pages: check pagination and total counts on each candidate; cross-check against sitemap counts above")
    for l in inv[:4]:
        body = get(l, a.delay) or ""
        pages = re.findall(r'(?:/page/|[?&]page=|[?&]paged=)(\d+)', body)
        counts = re.findall(r'data-(?:pages|total|count)="(\d+)"', body)
        print(f"  {l}: max page link={max(map(int, pages)) if pages else '-'}, data-counters={counts[:4] or '-'}")

    print("\nsample detail pages (structured data is the cleanest source - prefer it):")
    for sh, us in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if not (VEHICLE_WORDS.search(sh) and len(us) > 5):
            continue
        for u in us[: a.sample]:
            page = get(u, a.delay) or ""
            t = Counter(jsonld_types(page))
            imgs = len(set(re.findall(r'https?://[^"\' ]+\.(?:jpg|jpeg|webp)', page)))
            print(f"  {u}\n     json-ld types={dict(t) or '-'} price-in-ld={'price' in page and 'priceCurrency' in page} images~{imgs}")
        break
    print("\nNEXT: write the scraper from the cleanest source; union ALL url sources (listing + every sitemap shape +"
          " new-car page) and compare counts; see SKILL.md")


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
