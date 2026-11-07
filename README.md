# Seez candidate exercise - Autohaus Burger (autohaus-burger.de)

The three deliverables of the exercise: (1) `inventory.json` + scraper, (2) `dealership_structure.csv`, (3) `writeup.md`. Quick start: `python scrape_inventory.py` then `python build_structure_csv.py` (Python 3.9+, nothing to install; details under "Run" below).

## Write-up

The site is WordPress with a custom vehicle post type outside the standard REST API, so I parsed the HTML. The /fahrzeuge/ listing (13 pages) holds all 126 cars, but 20 of them (9 new, 11 used) have letter-prefixed IDs such as hk2332. My first regex only matched numeric IDs, so it silently returned 106 cars and no new ones; comparing counts exposed the gap. The scraper now unions listing, sitemap and Neuwagen page: 126 vehicles (117 used, 9 new) with specs, equipment and all images, fetched at one request per second. Every run checks count, IDs, price, mileage and images against the vehicle plugin's own public API. 139 /autos/ pages are an old archive (title, price, one image, all 404), so I kept them in a separate archived_listings.json. Absent data stays null: new cars have no first registration, electric cars' 0 ccm becomes null, most used cars no CO₂. German labels become English enums, originals kept in *_de fields. Dealership data comes from the Kontakt, Impressum and footer pages: there is no Google Maps link (I built a search URL) and Saturday workshop hours conflict between pages. I used Claude Code (Claude Sonnet 5.5) to inspect the HTML and write the scrapers, and ChatGPT (GPT-6) as a second model to review the repository. Claude was fast at parsing, but the numeric-ID bug in its code went unnoticed until I compared counts; ChatGPT's review spotted that my API check only compared IDs, so I added field checks.

(The same text is in `writeup.md`.)

## Files
- `archived_listings.json` + `scrape_archive.py` - the 139 old `/autos/` pages (June 2026 snapshot): title, price, category, 1 image (dead link, HTTP 404). Mileage/year/equipment are not published there, so they are `null`. Kept apart from live stock on purpose
- `inventory.json` - 126 vehicles (117 used, 9 new), English keys, numeric types, all image URLs
- `dealership_structure.csv` - group > location > departments (13 rows, UTF-8, comma separated, `;` inside multi-value cells). Hierarchy via `id` / `parent_id` (import key) plus `parent_name`, `level` and `hierarchy_path` (readability)
- `writeup.md` - short write-up
- `scrape_inventory.py`, `build_structure_csv.py` - source code. The structure CSV is not scraped blindly: its facts were read by hand from the dealer's own pages and each row cites its `source_url`; `build_structure_csv.py` writes them out consistently
- `verify_structure.py` - re-checks every phone, e-mail, address and opening-hours fact in the CSV against the live site (70 checks including the opening-hours days, exit 0 = all found). It does not check fax, brands or the Maps link, and it searches the row's `source_url` plus /kontakt/ and /impressum/, not only the cited page
- `skills/exposed-api-check/` - extra, a second skill: a passive, GET-only check of which APIs a site exposes publicly (lists sensitive-looking routes, never requests them); this is how the site's own vehicle API was found for the completeness cross-check. See its `SKILL.md`
- `agent_toolkit/` - extra, a reusable skill for onboarding any dealer (see `agent_toolkit/README.md` for install and use): `SKILL.md` (playbook + config reference), `tools/discover_site.py`, `tools/dealer_scrape.py` (config-driven scraper, completeness cross-check), `tools/build_structure.py` (facts JSON to CSV), `tools/validate_inventory.py`, `configs/` (this dealer's config and facts), `inventory.schema.json`. Running the generic tools with `configs/autohaus-burger*.json` reproduces `inventory.json` and `dealership_structure.csv` (the only difference is `page_modified`, a timestamp the site refreshes on each page load)

Validation of the published files: `python agent_toolkit/tools/validate_inventory.py inventory.json --expect 126 --structure dealership_structure.csv` gives 126 vehicles, 0 errors, 0 warnings. The site's robots.txt allows everything (empty `Disallow`). `agent_toolkit/` and `skills/` are extras beyond the three requested deliverables.

Requirements: Python 3.9 or newer (`python --version`; on macOS/Linux the command may be `python3`, on Windows `py`), no packages to install, Windows / macOS / Linux. Run the commands from the folder that contains these files. The scripts force UTF-8 output themselves, so accents print correctly on any terminal. To identify yourself to the site, set the environment variable `SCRAPER_USER_AGENT` (for example `Your-Name-Exercise/1.0 (+you@example.com)`); the default User-Agent says it is a polite 1 request/second scraper.

Run (Python 3.9+, standard library only, no install needed)
```
python scrape_inventory.py          # ~3 min, 1 request/second, writes inventory.json
python scrape_archive.py            # 139 archive pages via the WordPress API, writes archived_listings.json
python build_structure_csv.py       # writes dealership_structure.csv
python verify_structure.py           # re-checks the CSV facts against the live pages (~15 s)
```
Use `--delay 2` to scrape more slowly.

Extra (agent toolkit)
```
python agent_toolkit/tools/dealer_scrape.py --config agent_toolkit/configs/autohaus-burger.json --out inventory.json
python agent_toolkit/tools/build_structure.py --facts agent_toolkit/configs/autohaus-burger.structure.json --out dealership_structure.csv
python agent_toolkit/tools/validate_inventory.py inventory.json --expect 126 --structure dealership_structure.csv
python agent_toolkit/tools/discover_site.py https://some-other-dealer.example
```
The 139 `/autos/` URLs are an old archive, scraped separately into `archived_listings.json` (see write-up).

Notes
- Completeness check: at the end the scraper compares its result with the site's own public API: `/wp-json/ecc/v1/search` (126 cars, same IDs, 9 new + 117 used) and `/wp-json/ecc/v1/cars` (listing URL, price, mileage and image list of every car must match). Any mismatch or failed page makes the script exit with code 1.
- Prices are gross (incl. VAT), EUR. `mileage_km` is km; `power_kw`/`power_ps`, `engine_displacement_ccm` are numbers.
- Missing on the site = `null` (e.g. first registration of new cars, CO2 of most used cars). New cars: the site shows an empty "Erstzulassung" row and publishes no model year, so `year` / `first_registration` are `null` for the 9 new cars.
- `page_published` / `page_modified` = the site's own page timestamps (schema.org `datePublished`, `article:modified_time`): when the ad page went online / was last regenerated.
- Checked on the whole site (all pages and posts in the sitemaps, raw HTML + stored page content, the public REST API): the site publishes no Google Maps link or embedded map (the contact page only has a bwegt.de public-transport route widget), no structured opening hours (only the contact page and the footer list them, for sales, service, workshop and parts), and no per-department brand list. Those CSV cells are therefore empty (the `notes` column says "not published for this department" on each such row), and the Maps URL is a search link built from the site's own address. Brands that ARE published are used: used cars = Audi, Volkswagen, CUPRA, SEAT, Škoda (/gebrauchtwagen/); new-car enquiry form = VW, Audi, Škoda, SEAT, CUPRA; service booking = the same plus VW commercial vehicles; fleet = Audi and VW (/grosskunden/).
- All 3,737 image URLs were HEAD-checked: HTTP 200, `image/jpeg`.
- `brands` in the CSV = the brands a department deals in according to the site's own wording (forms, service and fleet pages), not the current stock: the 9 new cars published today are all Volkswagen, but the new-car enquiry form lists VW, Audi, Škoda, SEAT and CUPRA.
- `fuel_type`, `transmission`, `drive_type` are English enums; the site's German wording is in `*_de`.
- `opening_hours` uses OpenStreetMap syntax; the German text is in `opening_hours_text_de`.
