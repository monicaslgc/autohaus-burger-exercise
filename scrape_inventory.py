#!/usr/bin/env python3
"""Inventory scraper for https://autohaus-burger.de/  (Seez candidate exercise).

Run:   python scrape_inventory.py            -> writes inventory.json
       python scrape_inventory.py --delay 2  -> slower (default 1.0 s between requests)

Only the Python 3.9+ standard library is used (no pip install needed).

How it works
  1. Walks the paginated listing /fahrzeuge/page/N/ until a 404 and collects every
     /fahrzeuge/<id>/ detail URL. These are cross-checked against vehicle-sitemap.xml.
  2. Fetches each detail page once and merges three sources on the page:
       - schema.org "Car" JSON-LD  (brand, model, price, condition, all gallery images, engine)
       - the "vehicle-summary-table" (power, gearbox, first registration, HSN/TSN ...)
       - the "Ausstattung" equipment block (grouped by category)
  3. Normalises everything to English keys and numeric types.
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

CONDITION = {
    "UsedCondition": "used",
    "NewCondition": "new",
    "DamagedCondition": "damaged",
    "RefurbishedCondition": "refurbished",
}
TRANSMISSION = {"Automatik": "automatic", "Schaltgetriebe": "manual"}
DRIVE = {"Frontantrieb": "front_wheel_drive", "Heckantrieb": "rear_wheel_drive", "Allradantrieb": "all_wheel_drive"}
FUEL = {"Super": "petrol", "Diesel": "diesel", "Elektro": "electric", "Hybrid-Benzin": "hybrid_petrol",
        "Hybrid-Diesel": "hybrid_diesel", "Erdgas": "cng", "Autogas": "lpg", "Super Plus": "petrol"}
# German label on the page -> (english key, converter)
def _int(s):
    m = re.search(r"[\d.]+", s.replace("\xa0", " "))
    return int(m.group(0).replace(".", "")) if m else None


def _ez(s):
    m = re.match(r"(\d{2})/(\d{4})", s.strip())
    return (int(m.group(2)), int(m.group(1))) if m else (None, None)


def get(url, delay, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de,en;q=0.7"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            time.sleep(delay)
            return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # network hiccup -> back off and retry
            err = e
        time.sleep(delay * (attempt + 2) * 2)
    print(f"  ! giving up on {url}: {err}", file=sys.stderr)
    return None


def listing_urls(delay):
    urls, page = [], 1
    while True:
        u = f"{BASE}/fahrzeuge/" if page == 1 else f"{BASE}/fahrzeuge/page/{page}/"
        body = get(u, delay)
        if body is None:
            break
        found = re.findall(r'https://autohaus-burger\.de/fahrzeuge/(?!page/|feed/)[A-Za-z0-9]+/', body)
        new = [x for x in dict.fromkeys(found) if x not in urls]
        if not new:
            break
        urls += new
        print(f"listing page {page}: {len(new)} vehicles", file=sys.stderr)
        page += 1
    return urls


def new_car_urls(delay):
    body = get(f"{BASE}/neuwagen/", delay) or ""
    return list(dict.fromkeys(re.findall(r'https://autohaus-burger\.de/fahrzeuge/(?!page/|feed/)[A-Za-z0-9]+/', body)))


def sitemap_urls(delay):
    body = get(f"{BASE}/vehicle-sitemap.xml", delay) or ""
    return list(dict.fromkeys(re.findall(r'<loc>(https://autohaus-burger\.de/fahrzeuge/(?!page/|feed/)[A-Za-z0-9]+/)</loc>', body)))


def api_check(cars, delay):
    """Cross-check against the site's own public search API (/wp-json/ecc/v1/search): it reports how many cars
    the dealer currently offers. Our result must match that total and its ids."""
    body = get(f"{BASE}/wp-json/ecc/v1/search", delay)
    if not body:
        print("API cross-check skipped (endpoint not reachable)", file=sys.stderr)
        return
    api = json.loads(body)
    api_ids = {str(v["id"]) for v in api.get("vehicles", [])}
    ours = {str(c["vehicle_id"]) for c in cars}
    verdict = "MATCH" if api_ids == ours else f"MISMATCH (only API: {len(api_ids - ours)}, only ours: {len(ours - api_ids)})"
    print(f"API cross-check: site reports {api.get('total')} cars, scraper has {len(cars)} -> {verdict}", file=sys.stderr)


def clean(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def parse_vehicle(url, page):
    v = {"listing_url": url, "source_id": url.rstrip("/").rsplit("/", 1)[1]}

    # --- JSON-LD Car ---------------------------------------------------------
    car = {}
    for blob in re.findall(r'application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Car":
            car = d
    if not car:  # not a vehicle page (e.g. feed, index) -> skip
        return None
    offer = car.get("offers", {})
    cond = str(offer.get("itemCondition", "")).rsplit("/", 1)[-1]
    h1 = re.search(r'<h1 class="ecc-detail-title">(.*?)</h1>', page, re.S)
    title = clean(h1.group(1)) if h1 else car.get("name", "")
    make = (car.get("brand") or {}).get("name")
    model = car.get("model")
    variant = title
    if make:
        variant = re.sub(re.escape(make), "", variant, count=1, flags=re.I).strip()
    if model:
        # match model tokens in order, ignoring spaces ("RS 4" == "RS4") and an inserted generation ("Golf VIII GTI")
        for tok in model.split():
            pat = r"\s*".join(re.escape(ch) for ch in tok)
            variant = re.sub(pat, "", variant, count=1, flags=re.I).strip()
    gen = re.match(r"^([IVX]{2,5})\s*", variant)
    v["generation"] = gen.group(1) if gen else None
    if gen:
        variant = variant[gen.end():]
    variant = re.sub(r"\s+", " ", variant).strip(" -/")
    v["title"] = title
    v["condition"] = CONDITION.get(cond, cond.replace("Condition", "").lower() or None)
    v["make"] = {"seat": "SEAT", "cupra": "CUPRA", "skoda": "Škoda"}.get((make or "").lower(), make)
    v["model"] = model
    v["variant"] = variant or None

    # --- price ---------------------------------------------------------------
    pr = re.search(r'ecc-detail-price">(.*?)</h2>', page, re.S)
    price_txt = clean(pr.group(1)) if pr else ""
    # the visible price is whole euros; JSON-LD sometimes carries float noise (74495.01)
    amount = _int(price_txt) if _int(price_txt) else offer.get("price")
    vat = re.search(r'ecc-detail-vat">(.*?)</p>', page, re.S)
    v["price"] = {
        "amount": amount,
        "currency": offer.get("priceCurrency", "EUR"),
        "vat_note": clean(vat.group(1)) if vat else None,
        "display": price_txt or None,
    }
    v["availability"] = str(offer.get("availability", "")).rsplit("/", 1)[-1] or None

    # --- summary table -------------------------------------------------------
    rows = {}
    tbl = re.search(r'vehicle-summary-table.*?</table>', page, re.S)
    if tbl:
        for k, val in re.findall(r'<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>', tbl.group(0), re.S):
            rows[clean(k)] = clean(val)
    year, month = _ez(rows.get("Erstzulassung", ""))
    v["year"] = year or (int(car["vehicleModelDate"]) if car.get("vehicleModelDate") else None)
    v["first_registration"] = f"{year:04d}-{month:02d}" if year else None
    km = _int(rows.get("Laufleistung", "")) if "Laufleistung" in rows else (car.get("mileageFromOdometer") or {}).get("value")
    v["mileage_km"] = km
    pw = re.search(r"(\d+)\s*kW\s*\((\d+)\s*PS\)", rows.get("Leistung", ""))
    v["power_kw"] = int(pw.group(1)) if pw else None
    v["power_ps"] = int(pw.group(2)) if pw else None
    disp = _int(rows["Hubraum"]) if rows.get("Hubraum") else None
    v["engine_displacement_ccm"] = disp or None  # 0 ccm = electric motor -> null
    tr = rows.get("Getriebe") or car.get("vehicleTransmission")
    dr = rows.get("Antrieb") or car.get("driveWheelConfiguration")
    fu = rows.get("Kraftstoff") or car.get("fuelType")
    v["transmission"] = TRANSMISSION.get(tr, tr)
    v["drive_type"] = DRIVE.get(dr, dr)
    v["fuel_type"] = FUEL.get(fu, fu)
    v["transmission_de"], v["drive_type_de"], v["fuel_type_de"] = tr, dr, fu  # original site wording
    v["emission_class"] = rows.get("Schadstoffklasse") or None
    v["hsn_tsn"] = rows.get("HSN/TSN") or None
    known = {"Erstzulassung", "Laufleistung", "Leistung", "Hubraum", "Getriebe", "Antrieb", "Kraftstoff",
             "Schadstoffklasse", "HSN/TSN"}
    extra = {k: val for k, val in rows.items() if k not in known}
    if extra:  # any additional labelled row the site exposes, kept verbatim (German labels)
        v["other_specs"] = extra

    # --- consumption / emissions --------------------------------------------
    cons = re.search(r'Verbrauchs- und Emissionswerte.*?(?=Finanzierung berechnen|Interesse\?)', page, re.S)
    t = clean(cons.group(0)) if cons else ""
    fc = re.search(r"([\d.,]+)\s*(l|kg|kWh)\s*/\s*100\s*km", t)
    v["consumption_combined"] = (
        {"value": float(fc.group(1).replace(",", ".")), "unit": f"{fc.group(2)}/100km"} if fc else None)
    co2 = re.search(r"CO.{1,3}-Emission\s*/\s*km\s*([\d.,]+)\s*g", t)
    co2_val = float(co2.group(1).replace(",", ".")) if co2 else car.get("emissionsCO2")
    v["co2_g_per_km"] = int(co2_val) if co2_val is not None and float(co2_val).is_integer() else co2_val  # one type: int

    # --- equipment -----------------------------------------------------------
    equip, flat = {}, []
    blk = re.search(r'>Ausstattung<(.*?)Verbrauchs- und Emissionswerte', page, re.S)
    if blk:
        body = blk.group(1)
        for h, inner in re.findall(r'<h[2-6][^>]*>(.*?)</h[2-6]>(.*?)(?=<h[2-6]|$)', body, re.S):
            items = [clean(i) for i in re.findall(r'<li[^>]*>(.*?)</li>', inner, re.S)]
            items = [i for i in items if i]
            if items:
                equip[clean(h)] = items
                flat += items
    v["equipment"] = list(dict.fromkeys(flat))
    v["equipment_by_category"] = equip

    # --- images --------------------------------------------------------------
    imgs = list(car.get("image") or [])
    imgs += re.findall(r'<div class="ecc-slide"><img src="([^"]+)"', page)
    v["images"] = list(dict.fromkeys(imgs))
    v["image_count"] = len(v["images"])

    # --- misc ----------------------------------------------------------------
    vid = re.search(r'data-vehicle-id="(\d+)"', page)
    v["vehicle_id"] = vid.group(1) if vid else None
    mod = re.search(r'article:modified_time" content="([^"]+)"', page)
    v["page_modified"] = mod.group(1) if mod else None
    pub = re.search(r'"datePublished":"([^"]+)"', page)  # schema.org WebPage: day the ad page was first published
    v["page_published"] = pub.group(1) if pub else None
    pdf = re.search(r'href="([^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*Fahrzeug als PDF', page)
    v["pdf_url"] = html.unescape(pdf.group(1)) if pdf else None
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1.0)")
    ap.add_argument("--out", default="inventory.json")
    a = ap.parse_args()

    urls = listing_urls(a.delay)
    sm = sitemap_urls(a.delay) + new_car_urls(a.delay)
    missing = [u for u in dict.fromkeys(sm) if u not in urls]
    if missing:
        print(f"{len(missing)} URLs only in sitemap, adding", file=sys.stderr)
        urls += missing
    print(f"{len(urls)} vehicles to fetch", file=sys.stderr)

    cars, failed = [], []
    for i, u in enumerate(urls, 1):
        page = get(u, a.delay)
        if not page:
            failed.append(u)
            continue
        rec = parse_vehicle(u, page)
        if rec:
            cars.append(rec)
        if i % 10 == 0:
            print(f"  {i}/{len(urls)}", file=sys.stderr)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(cars, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(cars)} vehicles to {a.out}; failed: {failed}", file=sys.stderr)
    api_check(cars, a.delay)


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
