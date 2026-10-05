# BeiSmart KE

**Compare prices for electronics and appliances across Kenyan online stores.**

**Live demo:** https://benvog.github.io/beismart-ke/ (a read-only daily snapshot; Amazon is not included in the demo)

One search checks Jumia, Kilimall, Avechi, Hotpoint, Carrefour, Phone Place and Amazon, groups the same product across stores, hides accessories and junk listings, and shows how each price has moved over time. Save products to a watchlist, or get an email when a price drops to your target.

## What it does

- **One search, every store.** Results are grouped by product, so you see every store's price for the same fridge side by side, with the cheapest first and the saving across stores.
- **Honest results.** Accessories, spare parts and far-too-cheap oddities are hidden with a visible reason (and can be shown). International prices are labelled as excluding delivery and import fees, and never count as a price drop.
- **Price history.** A daily check records every price change, so each product has a history chart, "lowest we've seen" and "price drop" badges, and a "Price drops this week" strip on the home page.
- **Filters.** Price range with a histogram of the results, stores, brands, new or refurbished, in stock only; a side panel on desktop and a bottom sheet on phones.
- **Watchlist and email alerts.** The heart keeps products in your browser (no accounts). An email alert confirms your address first, and every email has a safe one-click unsubscribe.
- **Light and dark themes**, keyboard friendly, checked with an automated accessibility audit.

## How it works

- **Scrapers** for each store (plain HTTP where possible, a real Chrome browser through Playwright where a store needs it), tested offline against saved real store pages.
- **A daily refresh job** (Windows Task Scheduler) keeps prices fresh, records price history in SQLite and sends any due price alerts.
- **A FastAPI API** for search, product grouping, price history, price drops and alerts.
- **A front end** in plain HTML, CSS and JavaScript modules, with no framework or build step. It reads the live API, or the same data exported as static JSON files for the read-only demo (`python -m beismart.export`).

## Run it

Windows, Python 3.13 and Google Chrome:

    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements-dev.txt
    .venv\Scripts\python -m playwright install chromium
    .venv\Scripts\python -m beismart.scheduler --once -q "fridge"
    .venv\Scripts\python -m uvicorn beismart.api:app --host 127.0.0.1 --port 8000

Then open http://127.0.0.1:8000. More detail, including the daily task, email settings and the API routes: [docs/RUNNING.md](docs/RUNNING.md).

Tests: `.venv\Scripts\python -m pytest` (262 tests, all offline). The scraper tests run against saved copies of the stores' own pages, which are kept out of this public repo.

## Status

Built as a final-year project, then reworked in 2026. The real app runs locally (the stores need a real browser and a home connection); the public demo is a static snapshot exported after the daily refresh and served by GitHub Pages.

Prices belong to the stores and every result links back to the store's own page.
