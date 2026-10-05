"""The scheduled refresh: keeps popular and watched queries fresh.

Run it as its own process, not inside the web server:

    python -m beismart.scheduler --once              refresh everything now, then exit
    python -m beismart.scheduler                     refresh now, then again every BEISMART_REFRESH_HOURS (24)
    python -m beismart.scheduler --once -q "iphone 13" -q "fridge"     refresh just these

What gets refreshed: confirmed watchlist queries, then the most-searched ones, then starter_queries.txt.
Progress is logged to logs/refresh.log.

`--once` suits Windows Task Scheduler (daily), which also survives reboots."""

import argparse
import asyncio
import logging
import logging.handlers
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field

from . import store
from .db import connect
from .models import StoreStatus
from .alerts import AlertSummary, run_alerts
from .mailer import Mailer, get_mailer
from .refresh import RefreshSummary, refresh_query
from .scrapers import Scraper
from .scrapers.browser import close_browser

log = logging.getLogger("beismart.scheduler")

MAX_POPULAR = 20      # how many popular queries to keep fresh
PAUSE_BETWEEN_S = 5   # a short rest between queries, to be polite to the stores


@dataclass
class JobSummary:
    queries: list[str]
    refreshed: list[RefreshSummary] = field(default_factory=list)
    seconds: float = 0.0
    alerts: AlertSummary | None = None

    @property
    def listings(self) -> int:
        return sum(s.listings for s in self.refreshed)

    @property
    def price_points_added(self) -> int:
        return sum(s.price_points_added for s in self.refreshed)

    @property
    def failures(self) -> list[tuple[str, str, str]]:
        """(query, store, status) for every store that did not return ok or empty."""
        bad = []
        for summary in self.refreshed:
            for r in summary.results:
                if r.status not in (StoreStatus.OK, StoreStatus.EMPTY):
                    bad.append((summary.query, r.store, r.status.value))
        return bad


def starter_queries(path: str | None = None) -> list[str]:
    """The always-refreshed list from starter_queries.txt (one query per line; # starts a comment)."""
    path = path or os.environ.get("BEISMART_STARTERS", "starter_queries.txt")
    try:
        with open(path, encoding="utf-8") as f:
            lines = [line.strip() for line in f]
    except OSError:
        return []
    return [store.normalize_query(line) for line in lines if line and not line.startswith("#")]


def queries_to_refresh(conn: sqlite3.Connection, limit: int = MAX_POPULAR, starters: list[str] | None = None) -> list[str]:
    """Watched queries first (people asked to be told), then the most-searched ones, then the starter list."""
    starters = starter_queries() if starters is None else starters
    seen, ordered = set(), []
    for q in store.watched_queries(conn) + store.popular_queries(conn, limit=limit) + starters:
        if q not in seen:
            seen.add(q)
            ordered.append(q)
    return ordered


async def run_job(conn: sqlite3.Connection, queries: list[str] | None = None,
                  stores: list[Scraper] | None = None, pause_s: float = PAUSE_BETWEEN_S,
                  mailer: Mailer | None = None, base_url: str = "http://127.0.0.1:8000") -> JobSummary:
    """Refresh each query in turn, then send any price alerts that are due (when a mailer is given).
    One query failing never stops the rest."""
    queries = queries if queries is not None else queries_to_refresh(conn)
    summary = JobSummary(queries=queries)
    started = time.monotonic()
    log.info("Refresh job started: %d queries", len(queries))
    for i, query in enumerate(queries):
        if i and pause_s:
            await asyncio.sleep(pause_s)
        try:
            summary.refreshed.append(await refresh_query(conn, query, stores))
        except Exception:
            log.exception("Refresh of %r failed", query)
    summary.seconds = time.monotonic() - started
    log.info("Refresh job done in %.0fs: %d listings seen, %d new price points, %d store problems",
             summary.seconds, summary.listings, summary.price_points_added, len(summary.failures))
    for query, store_name, status in summary.failures:
        log.warning("  %s on %r: %s", store_name, query, status)
    if mailer is not None:
        try:
            summary.alerts = run_alerts(conn, mailer, base_url)
            a = summary.alerts
            log.info("Alerts: %d watches checked, %d sent, %d failed, %d re-armed, %d unconfirmed expired",
                     a.checked, a.sent, a.failed, a.rearmed, a.expired)
        except Exception:
            log.exception("Checking price alerts failed")    # the refresh itself already succeeded and is saved
    return summary


async def main_async(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    interval = args.hours * 3600
    mailer = None if args.no_alerts else get_mailer()
    base_url = os.environ.get("BEISMART_BASE_URL", "http://127.0.0.1:8000")
    try:
        while True:
            await run_job(conn, args.query or None, mailer=mailer, base_url=base_url)
            if args.once:
                return
            log.info("Next refresh in %.0f hours", args.hours)
            await asyncio.sleep(interval)
    finally:
        await close_browser()
        conn.close()


def setup_logging(log_path: str) -> None:
    """Log to the console (when there is one) and to a file, since the daily task runs without a window."""
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(log_path, maxBytes=500_000, backupCount=3, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", handlers=handlers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep BeiSmart's saved prices fresh.")
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    parser.add_argument("--no-alerts", action="store_true", help="refresh prices but do not send price alerts")
    parser.add_argument("-q", "--query", action="append", help="refresh this query instead of the usual list (repeatable)")
    parser.add_argument("--db", default=os.environ.get("BEISMART_DB", "beismart_v2.db"))
    parser.add_argument("--log", default=os.environ.get("BEISMART_LOG", os.path.join("logs", "refresh.log")),
                        help="log file (default logs/refresh.log); empty to log to the console only")
    parser.add_argument("--hours", type=float, default=float(os.environ.get("BEISMART_REFRESH_HOURS", "24")))
    args = parser.parse_args()
    setup_logging(args.log)
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
