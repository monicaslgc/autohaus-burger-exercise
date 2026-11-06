#!/usr/bin/env python3
"""Builds dealership_structure.csv from the facts published on autohaus-burger.de
(/kontakt/, /impressum/, /service/, /grosskunden/, /ankauf/, /jobcar-by-autohaus-burger/, footer).
Run: python build_structure_csv.py
"""
import csv
from urllib.parse import quote_plus

SITE = "https://autohaus-burger.de"
ADDR = dict(street="Ehinger Straße 17 + 21-25", postal_code="89143", city="Blaubeuren", country="DE")
MAPS = "https://www.google.com/maps/search/?api=1&query=" + quote_plus("Autohaus Burger, Ehinger Straße 21, 89143 Blaubeuren")
PHONE, FAX, MAIL = "+49 7344 9600-0", "+49 7344 9600-20", "info@autohaus-burger.de"
ALL = "Volkswagen;Audi;Škoda;SEAT;CUPRA"

COLS = ["id", "parent_id", "parent_name", "level", "depth", "hierarchy_path", "name", "department_type", "brands", "address",
        "street", "postal_code", "city", "country", "phone", "fax", "email", "opening_hours",
        "opening_hours_text_de", "google_maps_url", "website_url", "source_url", "notes"]

def row(id, parent, level, name, dtype="", brands="", loc=True, phone="", fax="", email="", oh="", oht="",
        url="", src="", notes=""):
    r = dict.fromkeys(COLS, "")
    r.update(id=id, parent_id=parent, level=level, name=name, department_type=dtype, brands=brands,
             phone=phone, fax=fax, email=email, opening_hours=oh, opening_hours_text_de=oht,
             website_url=url or SITE, source_url=src, notes=notes)
    if loc:
        r.update(ADDR)
        r["google_maps_url"] = MAPS
    return r

K = f"{SITE}/kontakt/"
rows = [
    row("G1", "", "group", "Autohaus Burger GmbH & Co. KG", brands=ALL + ";Volkswagen Nutzfahrzeuge", phone=PHONE,
        fax=FAX, email=MAIL, src=f"{SITE}/impressum/",
        notes="Legal entity per Impressum: Registergericht Ulm HRA 1657; general partner Burger GmbH (HRB 4357); managing: Joachim Burger. Single site."),
    row("L1", "G1", "location", "Autohaus Burger Blaubeuren", brands=ALL + ";Volkswagen Nutzfahrzeuge", phone=PHONE,
        fax=FAX, email=MAIL, src=K,
        notes="Only showroom/site listed. Billing address Ehinger Str. 21-25; Impressum lists 17 + 21-25. Maps URL is a search link built from the address (site publishes no Maps link)."),
    row("D1", "L1", "department", "New car sales (Neuwagenverkauf)", "new_car_sales", ALL, phone=PHONE, email=MAIL,
        oh="Mo-Fr 08:00-18:00; Sa 09:00-12:00", oht="Montag - Freitag: 08:00 - 18:00 Uhr; Samstag: 09:00 - 12:00 Uhr",
        src=f"{SITE}/neuwagen/", notes="New cars currently online are Volkswagen only."),
    row("D2", "L1", "department", "Used car sales (Gebrauchtwagenverkauf)", "used_car_sales", ALL, phone=PHONE, email=MAIL,
        oh="Mo-Fr 09:00-18:00; Sa 09:00-12:00", oht="Montag - Freitag: 09:00 - 18:00 Uhr; Samstag: 09:00 - 12:00 Uhr",
        src=f"{SITE}/gebrauchtwagen/"),
    row("D3", "L1", "department", "Service counter (Service)", "service", ALL + ";Volkswagen Nutzfahrzeuge",
        phone=PHONE, email=MAIL, oh="Mo-Fr 07:00-18:00; Sa 08:00-12:00",
        oht="Montag - Freitag: 07:00 - 18:00 Uhr; Samstag: 08:00 - 12:00 Uhr", src=f"{SITE}/service/",
        notes="Online booking via myAudi, Volkswagen We, SEAT, CUPRA, SKODA and commercial-vehicle guest booking. Saturday: only the counter is staffed (footer note)."),
    row("D4", "L1", "department", "Workshop (Werkstatt)", "workshop", ALL + ";Volkswagen Nutzfahrzeuge",
        phone=PHONE, email=MAIL, oh="Mo-Fr 08:00-16:30; Sa off", oht="Montag - Freitag: 08:00 - 16:30 Uhr; Samstag: geschlossen",
        src=K, notes="Footer shows Service und Werkstatt 07:00-18:00 / Sa 08:00-12:00, but the footer's asterisk says the workshop is closed on Saturday; /kontakt/ values used."),
    row("D5", "L1", "department", "Parts & accessories (Teile- und Zubehörverkauf)", "parts", ALL + ";Volkswagen Nutzfahrzeuge",
        phone=PHONE, email=MAIL, oh="Mo-Fr 07:00-17:00", oht="Mo. - Fr. 07:00 Uhr - 17:00 Uhr", src=f"{SITE}/service/",
        notes="Express parts service, 98% of parts within 24h."),
    row("D6", "L1", "department", "Vehicle purchase (Ankauf)", "vehicle_purchase", "", phone="+49 7344 9600-40",
        email=MAIL, src=f"{SITE}/ankauf/", notes="Advice line +49 7344 96 00 40."),
    row("D7", "L1", "department", "Fleet & corporate customers (Großkunden)", "fleet_sales", "Volkswagen;Audi",
        phone="+49 7344 9600-99", email=MAIL, src=f"{SITE}/grosskunden/",
        notes="Large-account service centre for Audi and VW; sales contact line -99. Named staff omitted on purpose."),
    row("D8", "L1", "department", "JobCar (employee car leasing)", "leasing", "", phone=PHONE, email=MAIL,
        src=f"{SITE}/jobcar-by-autohaus-burger/"),
    row("D9", "L1", "department", "Body & paint shop (Karosserie- und Lackfachbetrieb)", "body_shop", "", phone=PHONE,
        email=MAIL, src=f"{SITE}/service/",
        notes="Accident repair, paintwork, dent removal, windscreen repair. No brand restriction or separate hours stated on the site."),
    row("D10", "L1", "department", "E-mobility (E-Mobilität by Burger)", "e_mobility", "", phone=PHONE, email=MAIL,
        src=f"{SITE}/e-mobilitaet/",
        notes="EV advice, charging solutions, installation service, tariffs, subsidies; advice line +49 7344 96 00 0. No brand restriction or hours stated."),
    row("D11", "L1", "department", "24h emergency & towing (Notdienst)", "roadside_assistance", "", phone="+49 176 62935356",
        email=MAIL, oh="24/7", oht="365 Tage, 24h erreichbar", src=K, notes="Accident, breakdown and towing hotline."),
]
# facts the site does NOT publish stay empty; say so in the notes so the gap is explicit, not silent
EXTRA_NOTES = {
    "G1": "Opening hours: the site publishes hours per department only (see department rows).",
    "L1": "Opening hours: the site publishes hours per department only (see department rows).",
    "D3": "24-hour key safe (24 STUNDEN SCHLÜSSELTRESOR) on /service/ for dropping off or collecting keys outside opening hours.",
    "D6": "Opening hours and brands: not published for this department.",
    "D7": "Opening hours: not published for this department.",
    "D8": "Opening hours and brands: not published for this department.",
    "D9": "Opening hours and brands: not published for this department.",
    "D10": "Opening hours and brands: not published for this department.",
    "D11": "Brands: not published for this department."
}
for r in rows:
    if r["id"] in EXTRA_NOTES:
        r["notes"] = (r["notes"] + " " if r["notes"] else "") + EXTRA_NOTES[r["id"]]
by_id = {r["id"]: r for r in rows}
for r in rows:  # readable hierarchy: parent name, full path, one-line address
    par = by_id.get(r["parent_id"])
    r["parent_name"] = par["name"] if par else ""
    r["depth"] = {"group": 1, "location": 2, "department": 3}[r["level"]]
    r["hierarchy_path"] = (par["hierarchy_path"] + " > " if par else "") + r["name"]
    if r["street"]:
        r["address"] = f'{r["street"]}, {r["postal_code"]} {r["city"]}, Germany'

with open("dealership_structure.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=COLS, quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    w.writerows(rows)
print(f"wrote {len(rows)} rows")
