---
name: dealer-site-onboarding
description: Onboard a car dealership website. Scrape the full new + used inventory into a clean inventory.json (config-driven scraper, completeness cross-check), describe the dealership hierarchy (group > location > departments) in an importable CSV, validate both, and draft the write-up. Use when given a dealer URL and asked for stock data, a dealer structure file, or a Seez-style onboarding exercise.
---

# Dealer site onboarding (inventory JSON + structure CSV)

**Finding SKILL_DIR (works on any machine, in any folder).** `<SKILL_DIR>` below means the folder that contains this SKILL.md and its `tools/` and `configs/`. Use the first that applies: (1) the base directory shown when this skill was loaded; (2) the personal install `~/.claude/skills/<skill-name>/` (macOS/Linux `$HOME/.claude/skills/...`, Windows `%USERPROFILE%\.claude\skills\...`); (3) a project install `<project>/.claude/skills/<skill-name>/`; (4) in a Git checkout of the exercise repo, the `agent_toolkit/` folder. If unsure, search for the file: `find ~ -name SKILL.md -path "*dealer-site-onboarding*"` or, in PowerShell, `Get-ChildItem $env:USERPROFILE -Recurse -Filter SKILL.md | Where-Object FullName -like "*dealer-site-onboarding*"`.
**Run from YOUR working folder (where the outputs should land), not from SKILL_DIR:** call the scripts by full path, `python "<SKILL_DIR>/tools/<script>.py" ...`. The scripts take every input and output path as an argument and never depend on where they are stored. Quote paths that contain spaces.

Everything below is stdlib-only Python 3.9+. A worked example (autohaus-burger.de) ships in `configs/`;
running the generic tools with it reproduces the reference `inventory.json` (126 cars) and
`dealership_structure.csv` exactly - use that as your regression test before touching the tools.

```
tools/discover_site.py     map a new site BEFORE scraping (URL shapes, sitemaps, JSON-LD, APIs, platform)
tools/dealer_scrape.py     config-driven inventory scraper + completeness cross-check
tools/build_structure.py   facts JSON -> importable structure CSV (hierarchy, paths, address, maps, integrity checks)
tools/validate_inventory.py quality gate for inventory.json (+ structure CSV)
configs/<dealer>.json              scraper config            configs/<dealer>.structure.json   structure facts
inventory.schema.json      output contract (JSON Schema)
```

## Rules (non-negotiable)
- Scrape politely: identifiable User-Agent, >= 1 s between requests, retries with back-off. Respect robots.txt. Only public GET endpoints.
- Only collect what the public site shows. No logins, no forms. No personal data: no named staff, personal emails or direct lines in the CSV - use the dealership's general lines.
- Never invent data. Not published => `null` / empty cell, and say so in the write-up. Examples that are NOT errors: a new car has no first registration or year; an EV has no displacement; a department with no published hours has empty hours.
- English keys, consistent types: numbers as numbers, unit in the key (`mileage_km`, `power_kw`), currency separate, dates `YYYY-MM`.
- Stay in scope: the dealer's own website. Do not scrape marketplaces (AutoScout24, mobile.de) or brand portals unless the user explicitly asks.

## Quick start for a new dealer
Work in your own project folder; `<SKILL_DIR>` is explained at the top.
```
python "<SKILL_DIR>/tools/discover_site.py" https://dealer.example                       # 1. understand the site
cp "<SKILL_DIR>/configs/autohaus-burger.json" dealer.json                                # 2. adapt (see Config reference)
python "<SKILL_DIR>/tools/dealer_scrape.py" --config dealer.json --sources-only           # 3. reconcile URL sources
python "<SKILL_DIR>/tools/dealer_scrape.py" --config dealer.json --limit 5 --out try.json # 4. try 5 cars, read them
python "<SKILL_DIR>/tools/dealer_scrape.py" --config dealer.json --out inventory.json     # 5. full run (exit 0 = ok)
python "<SKILL_DIR>/tools/validate_inventory.py" inventory.json --expect <N> --structure dealership_structure.csv
python "<SKILL_DIR>/tools/build_structure.py" --facts dealer.structure.json --out dealership_structure.csv
```
(`cp` is `Copy-Item` in PowerShell. Start `dealer.structure.json` from `<SKILL_DIR>/configs/autohaus-burger.structure.json`.)
Exit codes of `dealer_scrape.py`: 0 ok; 1 pages failed to download or the API cross-check MISMATCHED; 2 no vehicle URLs
found (bad `vehicle_url_regex`/sources); 3 every page rejected (bad `jsonld_types`). A non-zero exit is never "fine".

## Workflow
1. **Discover.** Read which URL shape is the inventory, sitemap counts per shape, JSON-LD types, external sources, platform. Prefer schema.org JSON-LD (`Car`/`Vehicle`) on detail pages: brand, model, price, condition, engine, full image list.
2. **Find ALL inventory sources and union them** - one source is never enough: paginated listing; every vehicle-like sitemap (digits vs alphanumeric IDs); the "new cars" page (some sites keep new and used in different places). Look for the site's own search/REST API (`/wp-json/` namespaces, a vehicle plugin's `/search`): it usually gives the authoritative total and ids - put it in `cross_check`. Explain every difference between sources.
3. **Classify extra URL shapes.** Many URLs but no structured data, no specs, not linked from the live site (e.g. a WordPress `portfolio` archive of old ads) => sample ~10 and compare with current stock. Archive => scrape it too (WordPress REST `/wp-json/wp/v2/<post_type>` gives it in a few requests) but into a SEPARATE file with a snapshot date, and HEAD-check its image URLs (the reference archive's were all 404). Never silently drop it, never mix it into live stock. (`scrape_archive.py` in the repo root is the WordPress example.)
4. **Scrape** with `dealer_scrape.py`. Read the 5 sample cars by eye against the live pages before the full run.
5. **Normalise**: language enums to English, original kept in `*_de`; `0 ccm` on EVs => null; empty strings => null; generation split out of the model (`Golf VIII GTI` => model `Golf GTI`, generation `VIII`); brand casing (SEAT, CUPRA, Škoda); visible price over JSON-LD float noise.
6. **Validate** (`validate_inventory.py`): for every field with a high missing-rate open one page and decide "site does not publish" vs "parser missed". Check new cars exist if the dealer sells new.
7. **Structure**: research facts (contact page, imprint = legal entity + register number, footer, service/parts/fleet/trade-in/e-mobility/body-shop pages) into the facts JSON, one `source_url` per node, then `build_structure.py`. Department hours in OSM syntax (`Mo-Fr 08:00-18:00; Sa 09:00-12:00`). Record contradictions between pages in `notes`. No Maps link on the site => the tool builds a search URL from `maps_query`; say so.
8. **Write-up** (150-250 words, one paragraph): challenges and workarounds, what AI helped with and where it did not, what the site does not publish, at least one thing that went wrong first. Draft it for the candidate to review - it is their voice; do not present it as final.

## Config reference (`configs/<dealer>.json`)
- `base_url`, `user_agent`, `accept_language`, `delay` (s), `currency`.
- `sources.vehicle_url_regex` - matches ONE detail URL (use a negative lookahead for `/page/`, `/feed/`); used for listing pages, sitemap `<loc>`s (fullmatch) and extra pages.
- `sources.listing` - `{"first": "/cars/", "next": "/cars/page/{n}/"}` (set `null` if none); `sources.sitemaps` - list of sitemap paths; `sources.extra_pages` - pages that list more cars (e.g. `/new-cars/`).
- `cross_check` - `{url, list_key, id_key, total_key, our_id_field}`: the site's own API; ids must equal ours.
- `parse.jsonld_types` - vehicle schema types accepted (`["Car"]`, `["Vehicle","Car"]`); a page without one is rejected.
- `parse.*_regex` - capture group 1 = the text: `title`, `price`, `vat`, `spec_table` (whole table) + `spec_row` (2 groups: label, value), `power` (2 groups: kW, PS), `generation`, `consumption_block`, `co2`, `equipment_block` (group 1 = HTML with `<h2-6>` category headings and `<li>` items), `image` (extra gallery images; JSON-LD images are always included), `vehicle_id`, `modified`, `published`, `pdf_link`. Omit a key to skip that field.
- Optional `parse` keys added after testing a second site (matrizauto.pt, no spec table, JSON-LD without offers/images): `condition_from_url` (`{"/carro-usado/": "used"}`), `production_date_is_first_registration` (true = JSON-LD `productionDate` MM/YYYY is the registration date), `jsonld_extras` (JSON-LD fields kept under `other_specs`, e.g. `color`), `equipment_item_regex` (items that are not `<li>`), `image_scope_regex` (group 1 = the HTML block holding THIS car's gallery, so "similar cars" galleries are not mixed in). Relative links and image URLs are made absolute automatically. JSON-LD `manufacturer` + `name` are used when `brand` + `model` are missing.
- `parse.labels` - the site's own row labels (`{"first_registration": "Erstzulassung", ...}`); unknown extra rows land in `other_specs`.
- `enums` - maps from the site's wording to English enums (`transmission`, `drive`, `fuel`, `make_case`).
Debug loop: change one regex, rerun with `--limit 3`, diff the output.

## Pitfalls seen on the reference site (check on every new dealer)
- ID shapes: 20 cars (all 9 new ones) had letter-prefixed IDs (`hk2332`, `v08619`). A digits-only URL regex silently dropped them from listing, sitemap and new-car page alike and still produced a plausible 106-car file -> never trust one regex or one source: compare listing vs sitemap vs API counts and check that new cars exist.
- Generic path patterns also match `/feed/` and `/page/` - require vehicle JSON-LD to accept a page.
- A sitemap can be stale: matrizauto.pt lists ~62k vehicle URLs but the ones sampled returned 404 (sold cars) while the paginated listing (~80 pages) held the live stock. Sample a few sitemap URLs before trusting a sitemap as a source; the scraper skips 404s but would waste hours on 60k of them.
- Detail pages can embed "similar cars" galleries: image counts of 100+ per car are a sign (use `image_scope_regex`).
- 139 `/autos/...` pages were an old portfolio archive (title, price, one dead image; no specs, not linked).
- Contradicting opening hours between footer and contact page; the site truncates some long titles itself.
- A regex written through a shell heredoc can contain hidden control characters (`\b` became backspace): `grep -P '[\x00-\x08]'` generated code.
- A field that is empty for ALL records is a parser bug until proven otherwise (here `pdf_url`: the link text sat inside a nested `<span>`, so the first regex never matched). Also keep one JSON type per field (CO2 was int and float mixed -> int).
- Identical title + price can still be two different cars (different vehicle id/images): dedupe on URL or vehicle id, never title.
- Do not run shell/DB-admin REST namespaces that appear in `/wp-json/` (e.g. data-access or backup plugins): only the vehicle plugin's public read endpoints.

## Done means
`dealer_scrape.py` exits 0 with `cross-check ... MATCH`; `validate_inventory.py` exits 0; each empty field explained; counts per source reconciled in the write-up; the ZIP has `inventory.json`, the structure CSV, the code with run instructions, and the write-up.
