#!/usr/bin/env python3
"""Passive, read-only check: which APIs does a website expose publicly?

    python api_probe.py https://example.com [--delay 1.0] [--max-fetch 25] [--json report.json]

What it does (stdlib only, throttled, ~30-60 GET requests, never POST, never authenticated):
  1. Reads the home page: <link rel=alternate/api.w.org>, script URLs, embedded JSON (__NEXT_DATA__ ...), JSON-LD types,
     and greps same-origin JS files for API-looking URLs (/api/, /rest/, /graphql, /v1/ ...).
  2. GETs a short FIXED list of well-known paths (wp-json, openapi, swagger, graphql, feeds, sitemap ...). No wordlists, no fuzzing.
  3. If WordPress REST is present: reads the public route index, then sorts every route into
       - core content (wp/v2 posts, pages, media ... public by design)
       - data routes of plugins (safe to try: no required parameters, data-looking name)
       - SENSITIVE-looking routes (admin, settings, backup, db, install, users, keys, tokens, consent ...):
         these are only LISTED, NEVER requested.
     It then GETs at most --max-fetch safe routes and reports status, content type, item count and field names.
Output: a plain report of what is public and usable, what looks like an exposure to tell the site owner, and what to do next.
Use only on sites you are allowed to look at (your own, a client's, or a public site for an agreed task).
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
from urllib.parse import urljoin, urlparse

UA = os.environ.get("SCRAPER_USER_AGENT") or "Mozilla/5.0 (compatible; ApiExposureCheck/1.0; passive read-only, throttled)"
WELL_KNOWN = ["/wp-json/", "/openapi.json", "/swagger.json", "/api-docs", "/v2/api-docs", "/api/", "/api/v1/", "/rest/",
              "/graphql", "/feed/", "/sitemap.xml", "/sitemap_index.xml", "/.well-known/security.txt", "/humans.txt"]
SENSITIVE = re.compile(r"admin|setting|backup|restore|(^|/)db(/|$)|sql|install|uninstall|plugin|theme|user|account|login|auth|"
                       r"password|secret|token|key|license|connection|consent|log(s)?(/|$)|export|import|rollback|delete|"
                       r"activate|deactivate|update|run|exec|command|cron|health|status|debug|site-health|file|upload|fm/", re.I)
DATA_WORDS = re.compile(r"car|vehicle|search|product|item|listing|stock|event|location|store|dealer|offer|price|catalog|"
                        r"article|post|page|media|categor|tag|menu|option|filter|faq|job|news", re.I)
CORE_PUBLIC = ["/wp/v2/pages", "/wp/v2/posts", "/wp/v2/media", "/wp/v2/categories", "/wp/v2/tags", "/wp/v2/types",
               "/wp/v2/taxonomies"]
API_URL = re.compile(r"""["'`]((?:https?:)?//[^"'`\s]+|/[A-Za-z0-9_\-./]+)["'`]""")
API_HINT = re.compile(r"/(api|rest|graphql|wp-json|v\d+)(/|$|\?)|ajax[^/\s]*\.php|\.json(\?|$)", re.I)


class Fetcher:
    def __init__(self, delay):
        self.delay, self.n = delay, 0

    def get(self, url, limit=400_000):
        self.n += 1
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/html;q=0.8, */*;q=0.5"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read(limit).decode("utf-8", "replace")
                res = (r.status, r.headers.get("Content-Type", ""), body, dict(r.headers))
        except urllib.error.HTTPError as e:
            res = (e.code, e.headers.get("Content-Type", "") if e.headers else "", "", {})
        except Exception as e:  # network error
            res = (None, "", "", {"error": str(e)})
        time.sleep(self.delay)
        return res


def try_json(body):
    try:
        return json.loads(body)
    except Exception:
        return None


def describe(data):
    """items + field names of a JSON payload, without printing any values."""
    if isinstance(data, list):
        first = data[0] if data and isinstance(data[0], dict) else {}
        return f"list of {len(data)}", sorted(first)[:12]
    if isinstance(data, dict):
        for k in ("cars", "items", "data", "results", "products", "vehicles", "posts"):
            if isinstance(data.get(k), list):
                first = data[k][0] if data[k] and isinstance(data[k][0], dict) else {}
                return f"object with {k}[{len(data[k])}]", sorted(first)[:12]
        return f"object with {len(data)} keys", sorted(data)[:12]
    return type(data).__name__, []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--max-fetch", type=int, default=25, help="max plugin/core data routes to GET")
    ap.add_argument("--json", help="also write the findings to this JSON file")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    host = urlparse(base).netloc
    site_url = base                                   # the page the user gave (may be /pt/, /en/ ...)
    base = f"{urlparse(base).scheme}://{host}"        # probes go to the site root, not to the sub-path
    f = Fetcher(a.delay)
    rep = {"site": site_url, "home_hints": [], "well_known": [], "wordpress": None, "usable": [], "not_probed_sensitive": [],
           "exposure_notes": []}

    # 1. home page
    st, ct, robots, _ = f.get(base + "/robots.txt")
    blocked = []
    if st == 200:
        agent_all = False
        for line in robots.splitlines():
            line = line.split("#")[0].strip()
            if line.lower().startswith("user-agent:"):
                agent_all = line.split(":", 1)[1].strip() == "*"
            elif agent_all and line.lower().startswith("disallow:") and line.split(":", 1)[1].strip():
                blocked.append(line.split(":", 1)[1].strip())

    def allowed(path):
        return not any(path.startswith(b) for b in blocked)

    st, ct, home, hdrs = f.get(site_url if site_url.endswith("/") else site_url + "/")
    print(f"== {site_url}  (home: HTTP {st}; probing the site root {base})")
    if blocked:
        print("   robots.txt disallows for everyone: " + ", ".join(blocked) + "  (the probe never requests these)")
    if st != 200:
        print("Home page not reachable; stopping.")
        return
    hints = set()
    for m in re.finditer(r'<link[^>]+rel=["\']?(?:alternate|https://api\.w\.org/)[^>]*>', home, re.I):
        h = re.search(r'href=["\']([^"\']+)', m.group(0))
        if h and re.search(r"json|rss|atom|api\.w\.org|wp-json", m.group(0), re.I):
            hints.add("link: " + html.unescape(h.group(1)))
    if re.search(r"__NEXT_DATA__", home):
        hints.add("embedded JSON: __NEXT_DATA__ (Next.js page data)")
    if re.search(r"__NUXT__|window\.__INITIAL_STATE__|window\.__APOLLO_STATE__", home):
        hints.add("embedded JSON state (Nuxt / initial state / Apollo)")
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', home, re.S):
        j = try_json(m.group(1))
        g = (j.get("@graph", [j]) if isinstance(j, dict) else j) or []
        types = sorted({str(x.get("@type")) for x in g if isinstance(x, dict)})
        hints.add("JSON-LD types: " + ", ".join(types))
    if re.search(r"wp-content|wp-json", home):
        hints.add("platform: WordPress")
    gen = re.search(r'<meta name="generator" content="([^"]+)"', home)
    if gen:
        hints.add("generator: " + html.unescape(gen.group(1)))
    # same-origin JS files: look for API-looking URLs
    scripts = [urljoin(base + "/", s) for s in re.findall(r'<script[^>]+src=["\']([^"\']+)', home)]
    own = [s for s in scripts if urlparse(s).netloc == host and "wp-includes" not in s and "/themes/" not in s][:8]
    api_urls = set()
    for s in own:
        _, _, js, _ = f.get(s, limit=600_000)
        for m in API_URL.finditer(js):
            u = m.group(1)
            same = u.startswith("/") or urlparse(u if u.startswith("http") else "https:" + u).netloc == host
            if same and API_HINT.search(u) and not u.endswith((".js", ".css", ".png", ".jpg", ".svg", ".woff2")):
                api_urls.add(u[:120])
    for u in sorted(api_urls)[:15]:
        hints.add("API-looking URL in own JS: " + u)
    ext = sorted({urlparse(s).netloc for s in scripts if urlparse(s).netloc and urlparse(s).netloc != host})
    if ext:
        hints.add("third-party script hosts (not this site's API): " + ", ".join(ext[:10]))
    for m in re.finditer(r'(?:href|src|action)=["\']([^"\']+)', home, re.I):
        u = html.unescape(m.group(1))
        same = u.startswith("/") or urlparse(u).netloc == host
        if same and re.search(r"ajax|/api/|\.json(\?|$)|\.php(\?|$)", u, re.I) and not u.endswith((".js", ".css")):
            hints.add("endpoint-looking URL in the page: " + u[:120])
    rep["home_hints"] = sorted(hints)
    print("\n-- Hints on the home page")
    for h in sorted(hints):
        print("  *", h)
    if not hints:
        print("  (none)")

    # 2. well-known paths
    print("\n-- Well-known paths (fixed list, GET)")
    wp_index = None
    for p in WELL_KNOWN:
        if not allowed(p):
            print(f"  {p:28} skipped (robots.txt)")
            continue
        st, ct, body, _ = f.get(base + p, limit=4_000_000 if p == "/wp-json/" else 300_000)
        kind = "json" if "json" in ct else ("xml" if "xml" in ct else ct.split(";")[0] or "-")
        note = "  (HTML page, not an API)" if st == 200 and kind.startswith("text/html") else ""
        print(f"  {p:28} HTTP {st}  {kind}{note}")
        rep["well_known"].append({"path": p, "status": st, "type": kind})
        if p == "/wp-json/" and st == 200 and try_json(body) and "routes" in try_json(body):
            wp_index = try_json(body)

    # 3. WordPress REST
    if wp_index:
        routes = list(wp_index["routes"])
        ns = wp_index.get("namespaces", [])
        print(f"\n-- WordPress REST API: {len(routes)} routes, namespaces: {', '.join(ns)}")
        sens = [r for r in routes if SENSITIVE.search(r) and not r.startswith("/wp/v2/")]
        rep["not_probed_sensitive"] = sorted(sens)
        cand = []
        for r in routes:
            if r in sens or "(?P" in r or r == "/" or r.count("/") > 3:
                continue
            core = r in CORE_PUBLIC
            if core or (not r.startswith("/wp/v2/") and not r.startswith(("/oembed", "/batch")) and DATA_WORDS.search(r)):
                cand.append(r)
        cand = sorted(cand, key=lambda r: (r not in CORE_PUBLIC, r))[: a.max_fetch]
        print(f"   trying {len(cand)} safe data routes (GET, 1 item/page where possible)")
        for r in cand:
            sep = "&" if "?" in r else "?"
            st, ct, body, _ = f.get(f"{base}/wp-json{r}{sep}per_page=1" if r.startswith("/wp/v2/") else f"{base}/wp-json{r}",
                                    limit=6_000_000)
            data = try_json(body) if "json" in ct else None
            if st == 200 and data is not None:
                kind, fields = describe(data)
                total = ""
                rep["usable"].append({"route": "/wp-json" + r, "shape": kind, "fields": fields})
                print(f"  OK  /wp-json{r}  ->  {kind}; fields: {', '.join(fields) or '-'}")
            else:
                print(f"  --  /wp-json{r}  ->  HTTP {st}")
        if "/wp/v2/users" in routes:
            st, ct, body, _ = f.get(f"{base}/wp-json/wp/v2/users?per_page=1")
            d = try_json(body) if "json" in ct else None
            if st == 200 and isinstance(d, list) and d:
                rep["exposure_notes"].append("/wp-json/wp/v2/users is public and returns user records (author enumeration). "
                                             "Only the fact was recorded, no names stored.")
        if sens:
            rep["exposure_notes"].append(f"{len(sens)} sensitive-looking routes are advertised in the public index "
                                         "(admin/backup/DB/settings/plugin management). They were NOT requested. "
                                         "Auth is normally required, but tell the site owner they are listed.")
            print(f"\n-- Advertised but NOT probed (sensitive-looking): {len(sens)}")
            for r in sorted(sens)[:40]:
                print("   !", r)
            if len(sens) > 40:
                print(f"   ... and {len(sens) - 40} more")
    rep["wordpress"] = bool(wp_index)

    refused = [w["path"] for w in rep["well_known"] if w["status"] in (401, 403, 429)]
    if refused:
        print("\n  NOTE: the site answered 401/403/429 to our identifiable client for: " + ", ".join(refused))
        print("        That is the site refusing automated access. Do NOT work around it (no fake browser User-Agent,")
        print("        no proxies). Ask the site owner for access or an API key, or stay on the pages that answer 200.")
    print("\n== SUMMARY")
    print(f"  requests made: {f.n} (GET only, throttled {a.delay}s)")
    print(f"  usable public data endpoints: {len(rep['usable'])}")
    for u in rep["usable"]:
        print("   +", u["route"], "-", u["shape"])
    print(f"  sensitive-looking routes listed but not touched: {len(rep['not_probed_sensitive'])}")
    for n in rep["exposure_notes"]:
        print("  NOTE:", n)
    print("  NEXT: use a usable endpoint as the cross-check for completeness (ids/total), and read its terms/robots first.")
    if a.json:
        json.dump(rep, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("  report written to", a.json)


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
