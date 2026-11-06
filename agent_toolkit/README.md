# Dealer site toolkit

Command-line tools (and a Claude skill) to take a car-dealer website and produce two clean files:
an inventory JSON (every new and used car) and a dealership-structure CSV (group > location > departments).
It works for any dealer site: you adapt a small config file, you do not edit the code.

## What you need
- Python 3.9 or newer (`python --version`; on some systems the command is `python3` or `py`)
- Nothing else: no `pip install`, standard library only. Works on Windows, macOS and Linux.
- Internet access to the dealer site. The tools are polite by default (1 request per second).

## The tools (in `tools/`)
| Script | Use it to |
|---|---|
| `discover_site.py <url>` | map a new site before scraping: sitemaps, URL shapes, JSON-LD, platform |
| `dealer_scrape.py --config c.json --out inventory.json` | scrape every vehicle using the config; cross-checks the total against the site's own API if the config names one |
| `validate_inventory.py inventory.json --expect N` | quality gate: types, missing-rates, new cars present, CSV integrity |
| `build_structure.py --facts f.json --out structure.csv` | turn researched facts into an importable hierarchy CSV with integrity checks |

`configs/autohaus-burger*.json` is a worked example. Running the tools with it reproduces the shipped
`inventory.json` and `dealership_structure.csv` (that is the regression test).

## Run it yourself (no Claude needed)
Open a terminal in any folder you want the results in, then (replace `TOOLKIT` with the path of this folder):

macOS / Linux
```
python3 TOOLKIT/tools/discover_site.py https://dealer.example
cp TOOLKIT/configs/autohaus-burger.json dealer.json        # edit base_url, regexes, labels
python3 TOOLKIT/tools/dealer_scrape.py --config dealer.json --limit 5 --out try.json
python3 TOOLKIT/tools/dealer_scrape.py --config dealer.json --out inventory.json
python3 TOOLKIT/tools/validate_inventory.py inventory.json --expect 100
```
Windows (PowerShell)
```
python TOOLKIT\tools\discover_site.py https://dealer.example
Copy-Item TOOLKIT\configs\autohaus-burger.json dealer.json
python TOOLKIT\tools\dealer_scrape.py --config dealer.json --limit 5 --out try.json
python TOOLKIT\tools\dealer_scrape.py --config dealer.json --out inventory.json
python TOOLKIT\tools\validate_inventory.py inventory.json --expect 100
```
Quote paths that contain spaces. Output files are written to the folder you run the command in.
`SKILL.md` has the full workflow and the config reference.

## Use it as a Claude skill
Copy this whole folder to where Claude Code looks for skills, named `dealer-site-onboarding`:
- personal (all projects): `~/.claude/skills/dealer-site-onboarding/` (Windows: `%USERPROFILE%\.claude\skills\dealer-site-onboarding\`)
- one project only: `<project>/.claude/skills/dealer-site-onboarding/`

Then ask Claude, for example, "scrape the inventory of https://dealer.example and build the structure CSV".
The skill is a playbook: Claude reads `SKILL.md` and runs these scripts itself.

## Be a good citizen
- Set your own User-Agent so the site owner can reach you: `"user_agent"` in the config, or the environment variable
  `SCRAPER_USER_AGENT` (it overrides everything). Example: `Acme-Research/1.0 (+https://acme.example/contact)`.
- Keep the 1 s delay (or more), read the site's terms and robots.txt, collect only what the public pages show, and do not
  keep personal data (named staff, direct lines, personal e-mails).
- Exit codes of `dealer_scrape.py`: 0 ok; 1 pages failed or API cross-check mismatch; 2 no vehicle URLs found; 3 every page
  rejected. A non-zero exit is never "fine".

## Troubleshooting
- "Python 3.9 or newer is required": install a newer Python.
- `python` not found: try `python3` (macOS/Linux) or `py` (Windows).
- Accents look wrong in the terminal: the scripts force UTF-8 output themselves; open the JSON/CSV files with a UTF-8 editor.
