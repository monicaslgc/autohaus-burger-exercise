#!/usr/bin/env python3
"""Generic, config-driven dealer inventory scraper (stdlib only, Python 3.9+).

    python dealer_scrape.py --config <SKILL_DIR>/configs/autohaus-burger.json --out inventory.json
    python dealer_scrape.py --config my-dealer.json --limit 5 --out /tmp/test.json   # try a new config on 5 cars
    python dealer_scrape.py --config my-dealer.json --sources-only                    # only reconcile URL sources

All site-specific knowledge lives in the JSON config (see ../SKILL.md, "Config reference"); this file has none.
Pipeline: discover URLs from EVERY source (listing pagination + sitemaps + extra pages), union them, fetch each
detail page once, accept it only if it carries a schema.org vehicle block, merge JSON-LD + spec table +
equipment + images, normalise, then cross-check the result against the site's own API if the config names one.
Throttled (default 1 s between requests), identifiable User-Agent, retries with back-off.
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
from urllib.parse import urljoin

CONDITION = {"UsedCondition": "used", "NewCondition": "new", "DamagedCondition": "damaged",
             "RefurbishedCondition": "refurbished"}


def log(*a):
    print(*a, file=sys.stderr)


class Fetcher:
    def __init__(self, cfg, delay):
        self.base = cfg["base_url"].rstrip("/")
        self.headers = {"User-Agent": os.environ.get("SCRAPER_USER_AGENT") or cfg.get("user_agent", "Mozilla/5.0 (compatible; DealerOnboarding/1.0; polite, throttled)"),
                        "Accept-Language": cfg.get("accept_language", "en,de;q=0.7")}
        self.delay = delay

    def abs(self, path):
        return path if path.startswith("http") else self.base + path

    def get(self, url, tries=3):
        url = self.abs(url)
        err = None
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=self.headers), timeout=30) as r:
                    body = r.read().decode("utf-8", "replace")
                time.sleep(self.delay)
                return body
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    time.sleep(self.delay)
                    return None
                err = e
            except Exception as e:  # network hiccup: back off and retry
                err = e
            time.sleep(self.delay * (attempt + 2) * 2)
        log(f"  ! giving up on {url}: {err}")
        return None


# ----------------------------------------------------------------------------- URL discovery
def discover(cfg, fx, limit=None):
    src = cfg["sources"]
    rx = re.compile(src["vehicle_url_regex"])
    found = {}  # source name -> ordered list of urls

    lst = src.get("listing")
    if lst:
        urls, page = [], 1
        while True:
            body = fx.get(lst["first"] if page == 1 else lst["next"].format(n=page))
            if body is None:
                break
            new = [u for u in dict.fromkeys(fx.abs(m.group(0)) for m in rx.finditer(body)) if u not in urls]
            if not new:
                break
            urls += new
            log(f"listing page {page}: {len(new)} vehicles")
            page += 1
            if limit and len(urls) >= limit:
                log(f"  (--limit {limit}: stopped paging early; counts below are partial)")
                break
        found["listing"] = urls
    for sm in src.get("sitemaps", []):
        body = fx.get(sm) or ""
        found[f"sitemap:{sm}"] = list(dict.fromkeys(u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body) if rx.fullmatch(u)))
    for page_path in src.get("extra_pages", []):
        body = fx.get(page_path) or ""
        found[f"page:{page_path}"] = list(dict.fromkeys(fx.abs(m.group(0)) for m in rx.finditer(body)))
    union = list(dict.fromkeys(u for lst_ in found.values() for u in lst_))
    return union, found


# ----------------------------------------------------------------------------- parsing helpers
def clean(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def to_int(s):
    m = re.search(r"[\d.]+", (s or "").replace("\xa0", " "))
    return int(m.group(0).replace(".", "")) if m else None


def find(rx, text, flags=re.S):
    return re.search(rx, text, flags) if rx else None


def jsonld_vehicle(page, types):
    car = {}
    for blob in re.findall(r"application/ld\+json[^>]*>(.*?)</script>", page, re.S):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        nodes = d.get("@graph", [d]) if isinstance(d, dict) else d
        for n in nodes if isinstance(nodes, list) else [nodes]:
            if isinstance(n, dict) and n.get("@type") in types:
                car = n
    return car


def parse_vehicle(url, page, cfg):
    p = cfg["parse"]
    en = cfg.get("enums", {})
    car = jsonld_vehicle(page, p.get("jsonld_types", ["Car"]))
    if not car:  # not a vehicle page (feed, index, archive...) -> reject
        return None
    v = {"listing_url": url, "source_id": url.rstrip("/").rsplit("/", 1)[1]}
    offer = car.get("offers", {}) or {}
    cond = str(offer.get("itemCondition", "")).rsplit("/", 1)[-1]

    m = find(p.get("title_regex"), page)
    title = clean(m.group(1)) if m else car.get("name", "")
    make = (car.get("brand") or {}).get("name") if isinstance(car.get("brand"), dict) else car.get("brand")
    mf = car.get("manufacturer")
    make = make or (mf.get("name") if isinstance(mf, dict) else mf)
    model = car.get("model")
    if not model and make and car.get("name"):  # "Seat Leon St" -> "Leon St"
        model = re.sub(re.escape(make), "", car["name"], count=1, flags=re.I).strip() or None
    variant = title
    if make:
        variant = re.sub(re.escape(make), "", variant, count=1, flags=re.I).strip()
    if model:  # remove model tokens in order, ignoring spaces ("RS 4" == "RS4") and an inserted generation
        for tok in model.split():
            pat = r"\s*".join(re.escape(ch) for ch in tok)
            variant = re.sub(pat, "", variant, count=1, flags=re.I).strip()
    gen = re.match(p["generation_regex"], variant) if p.get("generation_regex") else None
    v["generation"] = gen.group(1) if gen else None
    if gen:
        variant = variant[gen.end():]
    variant = re.sub(r"\s+", " ", variant).strip(" -/")
    v["title"] = title
    v["condition"] = CONDITION.get(cond, cond.replace("Condition", "").lower() or None)
    for frag, val in (p.get("condition_from_url") or {}).items():
        if not v["condition"] and frag in url:
            v["condition"] = val
    v["make"] = en.get("make_case", {}).get((make or "").lower(), make)
    v["model"] = model
    v["variant"] = variant or None

    m = find(p.get("price_regex"), page)
    price_txt = clean(m.group(1)) if m else ""
    amount = to_int(price_txt) if to_int(price_txt) else offer.get("price")  # visible price beats JSON-LD float noise
    m = find(p.get("vat_regex"), page)
    v["price"] = {"amount": amount, "currency": offer.get("priceCurrency", cfg.get("currency", "EUR")),
                  "vat_note": clean(m.group(1)) if m else None, "display": price_txt or None}
    v["availability"] = str(offer.get("availability", "")).rsplit("/", 1)[-1] or None

    rows = {}
    tbl = find(p.get("spec_table_regex"), page)
    if tbl:
        for k, val in re.findall(p["spec_row_regex"], tbl.group(0), re.S):
            rows[clean(k)] = clean(val)
    L = p.get("labels", {})
    g = lambda key: rows.get(L.get(key, "\0"), "")  # noqa: E731
    ez = re.match(r"(\d{2})/(\d{4})", g("first_registration").strip())
    year, month = (int(ez.group(2)), int(ez.group(1))) if ez else (None, None)
    if not year and p.get("production_date_is_first_registration"):
        pd_ = re.match(r"(\d{2})/(\d{4})", str(car.get("productionDate", "")))
        if pd_:
            year, month = int(pd_.group(2)), int(pd_.group(1))
    v["year"] = year or (int(car["vehicleModelDate"]) if car.get("vehicleModelDate") else None)
    v["first_registration"] = f"{year:04d}-{month:02d}" if year else None
    v["mileage_km"] = to_int(g("mileage")) if L.get("mileage") in rows else to_int(str((car.get("mileageFromOdometer") or {}).get("value", "")))
    pw = re.search(p["power_regex"], g("power")) if p.get("power_regex") else None
    v["power_kw"] = int(pw.group(1)) if pw else None
    v["power_ps"] = int(pw.group(2)) if pw else None
    eng = car.get("vehicleEngine")
    eng = (eng[0] if isinstance(eng, list) and eng else eng) if eng else {}
    eng = eng if isinstance(eng, dict) else {}
    if v["power_ps"] is None and (eng.get("enginePower") or {}).get("unitCode") in ("cv", "PS", "HP"):
        v["power_ps"] = to_int(str(eng["enginePower"].get("value", "")))
    v["engine_displacement_ccm"] = (to_int(g("displacement")) if g("displacement") else None) \
        or to_int(str((eng.get("engineDisplacement") or {}).get("value", ""))) or None  # 0 ccm = EV
    tr = g("transmission") or car.get("vehicleTransmission")
    dr = g("drive") or car.get("driveWheelConfiguration")
    fu = g("fuel") or car.get("fuelType") or eng.get("fuelType")
    v["transmission"] = en.get("transmission", {}).get(tr, tr)
    v["drive_type"] = en.get("drive", {}).get(dr, dr)
    v["fuel_type"] = en.get("fuel", {}).get(fu, fu)
    v["transmission_de"], v["drive_type_de"], v["fuel_type_de"] = tr, dr, fu  # original wording kept
    v["emission_class"] = g("emission_class") or None
    v["hsn_tsn"] = g("hsn_tsn") or None
    known = set(L.values())
    extra = {k: val for k, val in rows.items() if k not in known}
    for k in p.get("jsonld_extras", []):
        if car.get(k) not in (None, ""):
            extra[k] = car[k]
    if extra:
        v["other_specs"] = extra

    cons = find(p.get("consumption_block_regex"), page)
    t = clean(cons.group(0)) if cons else ""
    fc = re.search(r"([\d.,]+)\s*(l|kg|kWh)\s*/\s*100\s*km", t)
    v["consumption_combined"] = {"value": float(fc.group(1).replace(",", ".")), "unit": f"{fc.group(2)}/100km"} if fc else None
    co2 = re.search(p["co2_regex"], t) if p.get("co2_regex") else None
    co2_val = float(co2.group(1).replace(",", ".")) if co2 else car.get("emissionsCO2")
    v["co2_g_per_km"] = int(co2_val) if co2_val is not None and float(co2_val).is_integer() else co2_val  # one type: int

    equip, flat = {}, []
    blk = find(p.get("equipment_block_regex"), page)
    if blk:
        for h, inner in re.findall(r"<h[2-6][^>]*>(.*?)</h[2-6]>(.*?)(?=<h[2-6]|$)", blk.group(1), re.S):
            items = [i for i in (clean(x) for x in re.findall(p.get("equipment_item_regex", r"<li[^>]*>(.*?)</li>"), inner, re.S)) if i]
            if items:
                equip[clean(h)] = items
                flat += items
    v["equipment"] = list(dict.fromkeys(flat))
    v["equipment_by_category"] = equip

    imgs = list(car.get("image") or [])
    if isinstance(car.get("image"), str):
        imgs = [car["image"]]
    if p.get("image_regex"):
        scope = find(p.get("image_scope_regex"), page)  # pages with "similar cars" galleries: only this car's own block
        imgs += re.findall(p["image_regex"], scope.group(1) if scope else page)
    v["images"] = list(dict.fromkeys(urljoin(url, html.unescape(i)) for i in imgs))
    v["image_count"] = len(v["images"])

    m = find(p.get("vehicle_id_regex"), page)
    v["vehicle_id"] = m.group(1) if m else None
    m = find(p.get("modified_regex"), page)
    v["page_modified"] = m.group(1) if m else None
    m = find(p.get("published_regex"), page)
    v["page_published"] = m.group(1) if m else None
    m = find(p.get("pdf_link_regex"), page)
    v["pdf_url"] = html.unescape(m.group(1)) if m else None
    return v


# ----------------------------------------------------------------------------- completeness check
def _path(obj, dotted):
    for part in dotted.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def _norm(val, how):
    if how == "number":
        digits = re.sub(r"\D", "", str(val)) if val is not None else ""
        return int(digits) if digits else None
    if how == "set":
        return set(val or [])
    return val


def cross_check(cfg, cars, fx):
    """True = verified and equal; False = mismatch OR could not be verified (never reported as success);
    None = no cross-check configured (a warning, the result stays unverified)."""
    cc = cfg.get("cross_check")
    if not cc:
        log("cross-check: NONE CONFIGURED - completeness is UNVERIFIED (look for a site search/REST API and add one)")
        return None
    body = fx.get(cc["url"])
    if not body:
        log("cross-check: endpoint not reachable - NOT VERIFIED (exit code 1)")
        return False
    api = json.loads(body)
    items = api.get(cc["list_key"], []) if isinstance(api, dict) else api
    api_ids = {str(i[cc["id_key"]]) for i in items}
    ours = {str(c.get(cc["our_id_field"])) for c in cars}
    ok = api_ids == ours
    total = api.get(cc.get("total_key", "total")) if isinstance(api, dict) else len(items)
    log(f"cross-check (ids): site reports {total}, scraper has {len(cars)} -> "
        + ("MATCH" if ok else f"MISMATCH (only API: {sorted(api_ids - ours)[:5]}, only ours: {sorted(ours - api_ids)[:5]})"))

    ff = cc.get("fields")  # optional field-level check against a second API endpoint
    if ff:
        fbody = fx.get(ff["url"])
        if not fbody:
            log("cross-check (fields): endpoint not reachable - NOT VERIFIED (exit code 1)")
            return False
        by_url = {c["listing_url"]: c for c in cars}
        records = json.loads(fbody)
        diffs = []
        for r in records:
            c = by_url.get(r.get(ff.get("link_key", "link")))
            if c is None:
                diffs.append(f"{r.get(ff.get('link_key', 'link'))}: not in our result")
                continue
            for chk in ff["checks"]:
                if _norm(_path(c, chk["ours"]), chk.get("as")) != _norm(_path(r, chk["api"]), chk.get("as")):
                    diffs.append(f"{c['listing_url']}: {chk['ours']}")
        f_ok = not diffs and len(records) == len(cars)
        log(f"cross-check (fields {', '.join(k['ours'] for k in ff['checks'])}): {len(records)} records -> "
            + ("MATCH" if f_ok else f"MISMATCH ({len(diffs)}, e.g. {diffs[:3]})"))
        ok = ok and f_ok
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="inventory.json")
    ap.add_argument("--delay", type=float, default=None, help="seconds between requests (default: config or 1.0)")
    ap.add_argument("--limit", type=int, help="only fetch the first N vehicle pages (to test a new config)")
    ap.add_argument("--sources-only", action="store_true", help="only list URL counts per source and exit")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    fx = Fetcher(cfg, a.delay if a.delay is not None else cfg.get("delay", 1.0))

    urls, by_source = discover(cfg, fx, a.limit)
    log("URL sources: " + ", ".join(f"{k}={len(v)}" for k, v in by_source.items()) + f" -> union={len(urls)}")
    only = {k: [u for u in v if not any(u in w for k2, w in by_source.items() if k2 != k)] for k, v in by_source.items()}
    for k, v in only.items():
        if v:
            log(f"  {len(v)} URLs only in {k} (e.g. {v[0]}) - explain every difference in the write-up")
    if not urls:
        log("ERROR: no vehicle URLs found - check sources.vehicle_url_regex / listing / sitemaps in the config")
        sys.exit(2)
    if a.sources_only:
        return
    if a.limit:
        urls = urls[: a.limit]

    cars, rejected, failed = [], [], []
    for i, u in enumerate(urls, 1):
        page = fx.get(u)
        if not page:
            failed.append(u)
            continue
        rec = parse_vehicle(u, page, cfg)
        (cars if rec else rejected).append(rec or u)
        if i % 10 == 0:
            log(f"  {i}/{len(urls)}")
    if not cars:
        log("ERROR: every page was rejected - check parse.jsonld_types (the vehicle schema type) in the config")
        sys.exit(3)
    if len(rejected) > 0.2 * len(urls):
        log(f"WARNING: {len(rejected)}/{len(urls)} pages rejected as non-vehicle pages - is vehicle_url_regex too broad?")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(cars, f, ensure_ascii=False, indent=2)
    log(f"wrote {len(cars)} vehicles to {a.out}; rejected (no vehicle markup): {len(rejected)}; failed: {len(failed)}")
    ok = cross_check(cfg, cars, fx) if not a.limit else None
    sys.exit(1 if failed or ok is False else 0)  # ok is None = nothing configured: warned loudly, result stays unverified


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
