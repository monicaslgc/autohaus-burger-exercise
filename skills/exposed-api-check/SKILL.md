---
name: exposed-api-check
description: Passively check which APIs a website exposes publicly (WordPress REST, OpenAPI/Swagger, GraphQL, embedded JSON, JS-referenced endpoints), tell usable data endpoints from sensitive-looking ones, and report what the site owner should know. Use before writing a scraper ("is there an API?"), as a completeness cross-check, or when asked whether a site exposes an API or admin routes.
---

# Exposed API check (passive, read-only)

**Finding SKILL_DIR (works on any machine, in any folder).** `<SKILL_DIR>` below means the folder that contains this SKILL.md and its `tools/`. Use the first that applies: (1) the base directory shown when this skill was loaded; (2) the personal install `~/.claude/skills/<skill-name>/` (macOS/Linux `$HOME/.claude/skills/...`, Windows `%USERPROFILE%\.claude\skills\...`); (3) a project install `<project>/.claude/skills/<skill-name>/`; (4) in a Git checkout of the exercise repo, the `agent_toolkit/` folder. If unsure, search for the file: `find ~ -name SKILL.md -path "*exposed-api-check*"` or, in PowerShell, `Get-ChildItem $env:USERPROFILE -Recurse -Filter SKILL.md | Where-Object FullName -like "*exposed-api-check*"`.
**Run from YOUR working folder (where the outputs should land), not from SKILL_DIR:** call the scripts by full path, `python "<SKILL_DIR>/tools/api_probe.py" ...`. The scripts take every input and output path as an argument and never depend on where they are stored. Quote paths that contain spaces.

One script, stdlib only: `tools/api_probe.py`. It answers two questions for a site you are allowed to look at:
1. **Is there a public API I can use** (instead of scraping HTML) and what does it return?
2. **Is anything exposed that the owner should hear about** (admin/backup/DB/plugin routes advertised publicly, user enumeration)?

## Rules (non-negotiable)
- Only sites you are allowed to look at: your own, a client's, or a public site for an agreed task (e.g. a take-home exercise). Never use it against a site just to find weaknesses.
- **GET only. No logins, no tokens, no POST, no forms, no bypassing auth, no brute force, no wordlists.** The path list is short and fixed.
- **Sensitive-looking routes are listed, never requested** (admin, settings, backup, db, plugins, themes, keys, consent logs, export/import ...). Do not call them by hand either, even if the list tempts you.
- Throttled (default 1 s between requests, ~30-60 requests). Identifiable User-Agent. Respect robots.txt and the site's terms.
- Do not store or print personal data. The script records only that `/wp/v2/users` is public, not the names.
- A found API is a data source, not permission to hammer it: use it for one cross-check pass, not bulk extraction, unless the task and the terms allow it.

## Install (optional, for Claude)
Standalone: nothing to install, just Python 3.9+. As a Claude skill, copy this folder to `~/.claude/skills/exposed-api-check/` (Windows: `%USERPROFILE%\.claude\skills\exposed-api-check\`) or to `<project>/.claude/skills/exposed-api-check/`, then ask e.g. "does https://example.com expose an API?". Identify yourself to the site with the environment variable `SCRAPER_USER_AGENT`.

## Run
Run from any folder; reports are written where you run the command (`--json`).
```
python "<SKILL_DIR>/tools/api_probe.py" https://example.com                    # report to the terminal
python "<SKILL_DIR>/tools/api_probe.py" https://example.com --json report.json # also save the findings
python "<SKILL_DIR>/tools/api_probe.py" https://example.com --max-fetch 10 --delay 2
```

## How to read the report
- **Hints on the home page**: platform (WordPress ...), `link rel` feeds/`wp-json`, embedded JSON (`__NEXT_DATA__`, Nuxt, Apollo), JSON-LD types, API-looking URLs found inside the site's own JS (this is how `/wp-json/ecc/v1/cars` showed up), third-party script hosts (NOT the site's API).
- **Well-known paths**: `200 + json/xml` = real; `200 + HTML` is a catch-all page, not an API (the script labels it); 404 = absent.
- **WordPress REST**: route count and namespaces; then up to `--max-fetch` safe data routes with the shape (`list of N`, `object with vehicles[N]`) and field names only.
- **usable public data endpoints** = candidates for the scraper or for a completeness cross-check (compare total and ids with what you scraped).
- **Advertised but NOT probed** = sensitive-looking routes in the public index. Normally they need auth; the point is that they are listed. Tell the owner in one sentence, do not test them.
- **NOTE lines** = things worth reporting (user enumeration, many admin routes listed).

## After the report
1. Usable endpoint found -> open it by hand once, compare total/ids with the HTML listing; use it as `cross_check` in the `dealer-site-onboarding` config (`cross_check.url/list_key/id_key/total_key`).
2. Nothing usable -> scrape HTML/JSON-LD (see `dealer-site-onboarding`).
3. Exposure notes -> write them in the hand-over/write-up as an observation ("route list is public, not accessed"), never as a test result.

## Worked example (autohaus-burger.de, WordPress + Avada + vehicle plugin)
`api_probe.py https://autohaus-burger.de` -> 34 requests; found `/wp-json/ecc/v1/cars` in the site's JS, `/wp-json/ecc/v1/search` returning all the vehicles (matched the scraped cars), 9 usable data endpoints, 415 routes in the index, 106 sensitive-looking routes listed but not touched (cookie plugin, theme/plugin manager, backup/DB admin), `/wp/v2/users` public. `openapi`, `swagger`, `graphql` absent; `/api/v1/` is an HTML page.

## Limits
- It cannot see APIs that are only called after a login, in a mobile app, or from JS it did not fetch (only the first 8 same-origin scripts are read).
- "Safe data route" is a heuristic (no required parameters, data-looking name, not sensitive-looking). Review the list before extending `--max-fetch`.
- Non-WordPress sites get the home-page hints and well-known paths only; add site-specific knowledge by hand.
