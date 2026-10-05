import asyncio

from beismart import store
from beismart.db import connect
from beismart.models import Listing, StoreResult, StoreStatus
from beismart.refresh import refresh_query
from beismart.scrapers import Scraper


class Working(Scraper):
    name = "Working"

    async def search(self, query):
        item = Listing(store=self.name, title="Samsung 43 Inch Smart TV", price=40000.0, url="https://w.test/1")
        return StoreResult(store=self.name, status=StoreStatus.OK, listings=[item])


class Crashing(Scraper):
    name = "Crashing"

    async def search(self, query):
        raise RuntimeError("selector exploded")


def test_refresh_saves_results_from_every_store():
    conn = connect(":memory:")
    summary = asyncio.run(refresh_query(conn, "samsung tv", [Working()]))
    assert summary.listings == 1 and summary.price_points_added == 1
    assert len(store.search_saved(conn, "samsung tv")) == 1


def test_one_crashing_store_does_not_break_the_others():
    conn = connect(":memory:")
    summary = asyncio.run(refresh_query(conn, "samsung tv", [Crashing(), Working()]))
    statuses = {r.store: r.status for r in summary.results}
    assert statuses == {"Crashing": StoreStatus.ERROR, "Working": StoreStatus.OK}
    assert len(store.search_saved(conn, "samsung tv")) == 1
    assert {r["store"] for r in store.store_status(conn)} == {"Crashing", "Working"}
