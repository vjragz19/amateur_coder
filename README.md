# Demo 2

This repo contains a small scraper that compares the app catalogs on Pipedream and Composio and
outputs the apps that are listed on Pipedream but missing from Composio.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python scrape_apps.py --output apps_missing_from_composio.json --html-report missing_apps.html
```

Open `missing_apps.html` in your browser to visualize the list.

### Optional flags

* `--show` opens a visible browser window (useful for debugging selectors or login flows).
* `--max-scrolls` controls how many times the script scrolls to load more cards.
* `--pause-ms` controls the delay between scrolls.
* `--html-report` writes a simple HTML table for quick viewing.

## Notes

* The script uses Playwright to execute the sites' JavaScript and extract app names from the
  rendered DOM. It first tries CSS selectors and then falls back to pulling names from
  embedded Next/Nuxt data if present.
* If the site HTML changes, update the selector lists in `scrape_apps.py`.
