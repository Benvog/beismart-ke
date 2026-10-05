"""Refreshing saved data: run every registered store for a query and save what comes back."""

import asyncio
import logging
import sqlite3
from dataclasses import dataclass

from .models import StoreResult
from .scrapers import Scraper, all_scrapers
from .store import save_result

log = logging.getLogger("beismart.refresh")


@dataclass
class RefreshSummary:
    query: str
    results: list[StoreResult]
    price_points_added: int

    @property
    def listings(self) -> int:
        return sum(len(r.listings) for r in self.results)


async def refresh_query(conn: sqlite3.Connection, query: str, stores: list[Scraper] | None = None) -> RefreshSummary:
    """Search every store for `query` at once and save the outcomes (successes and failures)."""
    stores = stores if stores is not None else [cls() for cls in all_scrapers().values()]
    results = await asyncio.gather(*[_safe_search(store, query) for store in stores])
    added = sum(save_result(conn, result, query) for result in results)
    for result in results:
        log.info("%s %r: %s (%d listings)", result.store, query, result.status.value, len(result.listings))
    return RefreshSummary(query=query, results=list(results), price_points_added=added)


async def _safe_search(store: Scraper, query: str) -> StoreResult:
    """One broken store must never take the others down."""
    from .models import StoreStatus

    try:
        return await store.search(query)
    except Exception as exc:  # scrapers should not raise, but a bug in one must not break a refresh
        log.exception("%s crashed on %r", store.name, query)
        return StoreResult(store=store.name, status=StoreStatus.ERROR, message=f"Unexpected error: {exc.__class__.__name__}")
