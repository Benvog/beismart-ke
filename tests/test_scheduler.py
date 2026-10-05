import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from beismart import store
from beismart.db import connect, now
from beismart.models import Listing, StoreResult, StoreStatus
from beismart.scheduler import queries_to_refresh, run_job
from beismart.scrapers import Scraper


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture(autouse=True)
def no_real_starter_file(monkeypatch, tmp_path):
    """Tests must not depend on the project's own starter_queries.txt."""
    monkeypatch.setenv("BEISMART_STARTERS", str(tmp_path / "no-starters.txt"))


def watch(conn, query, confirmed=1):
    conn.execute(
        "INSERT INTO watches (query, target_price, email, token, confirmed, created_at) VALUES (?,?,?,?,?,?)",
        (query, 1000, "a@b.test", f"tok-{query}-{confirmed}", confirmed, now()),
    )
    conn.commit()


class Recording(Scraper):
    name = "Recording"

    def __init__(self, fail_on=None):
        self.seen = []
        self.fail_on = fail_on

    async def search(self, query):
        self.seen.append(query)
        if query == self.fail_on:
            raise RuntimeError("boom")
        item = Listing(store=self.name, title=f"{query} thing", price=100.0, url=f"https://r.test/{query}")
        return StoreResult(store=self.name, status=StoreStatus.OK, listings=[item])


def test_searches_are_counted_and_normalised(conn):
    store.record_search(conn, "Samsung  TV")
    store.record_search(conn, "samsung tv ")
    assert store.popular_queries(conn) == ["samsung tv"]
    assert conn.execute("SELECT times FROM searches").fetchone()[0] == 2


def test_popular_queries_are_ordered_by_count_and_limited(conn):
    for q, n in [("fridge", 1), ("iphone 13", 3), ("blender", 2)]:
        for _ in range(n):
            store.record_search(conn, q)
    assert store.popular_queries(conn) == ["iphone 13", "blender", "fridge"]
    assert store.popular_queries(conn, limit=2) == ["iphone 13", "blender"]


def test_old_searches_drop_out_of_popular(conn):
    store.record_search(conn, "old thing")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    conn.execute("UPDATE searches SET last_at = ?", (old,))
    assert store.popular_queries(conn) == []


def test_only_confirmed_watches_are_refreshed(conn):
    watch(conn, "ps5", confirmed=1)
    watch(conn, "spam query", confirmed=0)
    assert store.watched_queries(conn) == ["ps5"]


def test_watched_queries_come_first_and_duplicates_are_dropped(conn):
    store.record_search(conn, "iphone 13")
    store.record_search(conn, "ps5")
    watch(conn, "PS5")
    assert queries_to_refresh(conn) == ["ps5", "iphone 13"]


def test_the_job_refreshes_every_query(conn):
    fake = Recording()
    summary = asyncio.run(run_job(conn, ["fridge", "blender"], [fake], pause_s=0))
    assert fake.seen == ["fridge", "blender"]
    assert summary.listings == 2 and summary.price_points_added == 2
    assert len(store.search_saved(conn, "fridge thing")) == 1


def test_a_store_crash_is_reported_but_the_job_carries_on(conn):
    fake = Recording(fail_on="fridge")
    summary = asyncio.run(run_job(conn, ["fridge", "blender"], [fake], pause_s=0))
    assert fake.seen == ["fridge", "blender"]
    assert summary.failures == [("fridge", "Recording", "error")]
    assert summary.listings == 1


def test_with_nothing_to_refresh_the_job_does_nothing(conn):
    fake = Recording()
    summary = asyncio.run(run_job(conn, None, [fake], pause_s=0))
    assert summary.queries == [] and fake.seen == []


def test_starter_queries_are_read_from_a_file(tmp_path):
    from beismart.scheduler import starter_queries
    f = tmp_path / "starters.txt"
    f.write_text("# comment\n\nSamsung  TV\nfridge\n  # indented comment is still a comment? no: it is stripped first\n", encoding="utf-8")
    assert starter_queries(str(f)) == ["samsung tv", "fridge"]


def test_a_missing_starter_file_means_no_starters(tmp_path):
    from beismart.scheduler import starter_queries
    assert starter_queries(str(tmp_path / "nope.txt")) == []


def test_starters_come_last_and_duplicates_are_dropped(conn):
    store.record_search(conn, "iphone 13")
    watch(conn, "ps5")
    assert queries_to_refresh(conn, starters=["fridge", "iphone 13", "laptop"]) == ["ps5", "iphone 13", "fridge", "laptop"]


def test_the_job_publishes_the_demo_when_a_pages_folder_is_given(conn, monkeypatch):
    calls = []

    class Result:
        pushed = True
        summary = type("S", (), {"queries": ["q"], "products": 1, "drops": 0})()

    monkeypatch.setattr("beismart.publish.publish", lambda c, pages: calls.append(pages) or Result())
    asyncio.run(run_job(conn, ["fridge"], stores=[Recording()], pause_s=0, pages_dir="D:/pages"))
    assert calls == ["D:/pages"]
    asyncio.run(run_job(conn, ["fridge"], stores=[Recording()], pause_s=0))          # no folder: no publish
    assert calls == ["D:/pages"]


@pytest.mark.parametrize("error", [RuntimeError("git push failed"), SystemExit("empty export")])
def test_a_failed_publish_is_logged_and_the_refresh_still_counts(conn, monkeypatch, caplog, error):
    def boom(c, pages):
        raise error

    monkeypatch.setattr("beismart.publish.publish", boom)
    summary = asyncio.run(run_job(conn, ["fridge"], stores=[Recording()], pause_s=0, pages_dir="D:/pages"))
    assert summary.listings == 1
    assert "Publishing the demo failed" in caplog.text

