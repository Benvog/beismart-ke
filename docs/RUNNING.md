# Running the rework

All commands run from the project folder. The environment lives in `.venv` (git-ignored).

## First time
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements-dev.txt

## Tests
    .venv\Scripts\python -m pytest

## The app (website and API)
    .venv\Scripts\python -m uvicorn beismart.api:app --host 127.0.0.1 --port 8000
Open http://127.0.0.1:8000 for the website and http://127.0.0.1:8000/docs for the interactive API page.

- Do not add `--reload`: on Windows it stops the browser stores (Carrefour, Hotpoint, Jumia, Kilimall) from refreshing.
  Restart the server after changing Python code. The website is plain files in `web/`, so its changes show on a refresh (F5).
- **On your phone:** start the server with `--host 0.0.0.0` instead, connect the phone to the same Wi-Fi and open
  `http://<this PC's address>:8000` (the address is shown by `ipconfig`, for example 192.168.1.20). If it will not load,
  Windows Firewall is blocking it: set the Wi-Fi network's profile to Private (Settings > Network & internet > Wi-Fi), or
  allow Python when Windows asks. While the server runs like this anyone on the Wi-Fi can open the site, so switch back to
  `--host 127.0.0.1` afterwards.
- The website reads the live API when opened from this PC or the home network, and exported JSON files in `web/data/`
  anywhere else (the public demo). Add `?source=static` or `?source=api` to force one (remembered until the tab closes).

## The public demo (static export)
    .venv\Scripts\python -m beismart.export            writes dist/demo (git-ignored)
Writes the website plus today's saved prices as JSON files in the same shapes the API returns, ready for GitHub Pages:
the most searched queries and `starter_queries.txt` (never watched ones), each product's price history, this week's drops
and the store list. Amazon is left out entirely. A search with no results is skipped. It only ever replaces a folder it made
itself. Preview it as plain files: `.venv\Scripts\python -m http.server 8001 --bind 127.0.0.1 -d dist/demo`, then open
http://127.0.0.1:8001/?source=static (on GitHub Pages the website picks the files by itself).

## The website (web/)
- `index.html`: home (no search) and results (`?q=fridge`, with sort and filters in the address).
- `product.html?q=fridge&id=<product id>`: one product across stores, price history and the email alert form.
- `watchlist.html`: products saved with the heart, kept in the browser.
- `js/data.js` is the only place that knows where data comes from; `css/app.css` holds every style and both themes.

## The refresh job (keeps saved prices fresh)
    .venv\Scripts\python -m beismart.scheduler --once            refresh popular and watched queries now, then exit
    .venv\Scripts\python -m beismart.scheduler                   refresh now, then every 24 hours
    .venv\Scripts\python -m beismart.scheduler --once -q "fridge"   refresh just this query

To run it daily with Windows Task Scheduler (survives reboots), create a task that runs
`.venv\Scripts\python.exe -m beismart.scheduler --once` with this folder as the start-in directory.

## Settings (environment variables)
- `BEISMART_DB`: database file (default `beismart_v2.db`)
- `BEISMART_REFRESH_HOURS`: hours between refreshes in loop mode (default 24)

Scraping uses your installed Google Chrome (falls back to Playwright's Chromium).

## API routes (details and a try-it-out page at /docs)
- `GET /api/search?q=samsung tv` saved prices: `results` (one row per listing), `groups` (one row per product, with every store's price, `price_drop`, `previous_best` and `lowest_ever` badges), `hidden_count` (junk; add `show_hidden=true` to list it with reasons) and each store's latest status.
- `GET /api/history?ids=1,2,3` price history of one product: pass the ids of a group's members. Returns the cheapest in-stock price over time (`best`), one line per store (`stores`) and a `summary` (current, lowest and highest ever, last change, drop). Points are the moments a price changed, so draw a step line that runs on to now.
- `POST /api/refresh?q=...` re-scrape all stores for a query (refused for 5 minutes after the last refresh of the same query).
- `GET /api/stores` each store's latest outcome. `GET /api/listings/{id}/history` the raw price points of one listing.
- `GET /api/drops` products whose best Kenyan price fell in the last 7 days, across every search the daily job keeps fresh, biggest fall first; each comes with the `query` that finds it (for links to its product page).
- `GET /api/popular` searches to suggest: most searched first, then the daily list.
- Each product in `groups` also has `brand` (read from the title, even when the product could not be matched across stores) and `condition` ("new" or "refurbished"); the filter panel uses both.

## The daily refresh task (Windows Task Scheduler)
A task called "BeiSmart daily refresh" runs `.venv\Scripts\pythonw.exe -m beismart.scheduler --once` every day at 2:00 PM,
as the owner, with this folder as its start-in directory (no window; catches up if the PC was off). It refreshes confirmed
watchlist queries, then the most-searched queries, then the list in `starter_queries.txt` (edit that file to change it).
Progress and store problems are written to `logs/refresh.log`.
- Run it now: `Start-ScheduledTask -TaskName 'BeiSmart daily refresh'` (PowerShell)
- Pause it: `Disable-ScheduledTask -TaskName 'BeiSmart daily refresh'`; resume with `Enable-ScheduledTask`
- Remove it: `Unregister-ScheduledTask -TaskName 'BeiSmart daily refresh' -Confirm:$false`
- Change the time: Task Scheduler (taskschd.msc) > the task > Triggers.

## Price alerts (watches) and email
- `POST /api/watches` with `{"query": "samsung tv", "target_price": 20000, "email": "you@example.com"}` (optionally `product_key` and `label` to watch one product). It creates an unconfirmed watch and emails a confirmation link. Nothing is sent until the link is opened. Limits: 10 watches per address, 5 new per day, 5 requests an hour per client.
- The links in the emails open small pages: `/api/watches/confirm`, `/api/watches/manage` (a person's alerts) and `/api/watches/unsubscribe` (asks first; a button removes it). Unconfirmed watches are deleted after 3 days.
- **Email delivery.** By default (`BEISMART_MAIL=outbox`) nothing is sent: each message is written to `logs/outbox/` so you can read it. For real delivery set `BEISMART_MAIL=smtp` and `BEISMART_SMTP_HOST`, `BEISMART_SMTP_PORT` (587), `BEISMART_SMTP_USER`, `BEISMART_SMTP_PASSWORD` and optionally `BEISMART_MAIL_FROM`. Any SMTP server works: a Gmail app password, or a transactional email service.
- `BEISMART_BASE_URL` (default `http://127.0.0.1:8000`) is the address put in email links.

## When alerts are sent
The daily refresh job checks every confirmed watch right after refreshing prices (`python -m beismart.scheduler`; add `--no-alerts` to skip this). The cheapest price you could actually buy is compared with the target:
- first time it reaches the target: one email;
- already below target and it falls a further 5% or more: another email; smaller wobbles stay silent;
- back above the target: the alert re-arms, so the next fall emails again.
Sold-out listings, listings hidden as junk and international listings (Amazon: shipping and import fees to Kenya are not included) never trigger an alert. If an email cannot be sent, the watch is retried at the next run. Unconfirmed watches older than 3 days are deleted at the same time. The log (`logs/refresh.log`) ends each run with a line such as "Alerts: 4 watches checked, 1 sent, 0 failed".
