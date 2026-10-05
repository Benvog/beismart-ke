import pytest
from fastapi.testclient import TestClient

from beismart import api
from beismart.api import create_app
from beismart.models import Listing, StoreResult, StoreStatus
from beismart.scrapers import Scraper


class FakeStore(Scraper):
    name = "Fake"
    calls = 0

    async def search(self, query):
        type(self).calls += 1
        items = [
            Listing(store=self.name, title="Samsung 32 Inch Smart TV", price=20000.0, url="https://f.test/1", old_price=24000.0),
            Listing(store=self.name, title="Samsung 55 Inch Smart TV", price=70000.0, url="https://f.test/2"),
        ]
        return StoreResult(store=self.name, status=StoreStatus.OK, listings=items, duration_ms=5)


@pytest.fixture
def client():
    FakeStore.calls = 0
    with TestClient(create_app(":memory:", stores=[FakeStore()])) as c:
        yield c


def test_search_before_any_refresh_is_empty_not_an_error(client):
    body = client.get("/api/search", params={"q": "samsung tv"}).json()
    assert body["count"] == 0 and body["results"] == []


def test_refresh_then_search_returns_saved_prices(client):
    refreshed = client.post("/api/refresh", params={"q": "samsung tv"})
    assert refreshed.status_code == 200
    assert refreshed.json()["listings"] == 2

    body = client.get("/api/search", params={"q": "samsung tv"}).json()
    assert [r["price"] for r in body["results"]] == [20000.0, 70000.0]
    assert body["results"][0]["old_price"] == 24000.0
    assert body["stores"][0]["store"] == "Fake" and body["stores"][0]["status"] == "ok"


def test_refreshing_the_same_query_twice_quickly_is_refused(client):
    assert client.post("/api/refresh", params={"q": "samsung tv"}).status_code == 200
    again = client.post("/api/refresh", params={"q": "Samsung TV "})
    assert again.status_code == 429
    assert "Retry-After" in again.headers
    assert FakeStore.calls == 1          # the stores were not hit a second time


def test_a_different_query_can_still_be_refreshed(client):
    assert client.post("/api/refresh", params={"q": "samsung tv"}).status_code == 200
    assert client.post("/api/refresh", params={"q": "iphone 13"}).status_code == 200


def test_stores_endpoint_shows_latest_outcome(client):
    client.post("/api/refresh", params={"q": "samsung tv"})
    rows = client.get("/api/stores").json()
    assert rows[0]["store"] == "Fake" and rows[0]["count"] == 2


def test_price_history_of_a_listing(client):
    client.post("/api/refresh", params={"q": "samsung tv"})
    listing_id = client.get("/api/search", params={"q": "samsung tv"}).json()["results"][0]["id"]
    history = client.get(f"/api/listings/{listing_id}/history").json()
    assert len(history) == 1 and history[0]["price"] == 20000.0


def test_unknown_listing_is_404(client):
    assert client.get("/api/listings/9999/history").status_code == 404


@pytest.mark.parametrize("q", ["", "a", "x" * 101])
def test_bad_queries_are_rejected(client, q):
    assert client.get("/api/search", params={"q": q}).status_code == 422
    assert client.post("/api/refresh", params={"q": q}).status_code == 422


def test_docs_page_is_served(client):
    assert client.get("/docs").status_code == 200
    assert "/api/search" in client.get("/openapi.json").json()["paths"]


def test_web_front_end_is_served_without_hiding_the_api(client):
    page = client.get("/")
    assert page.status_code == 200 and 'src="js/results.js"' in page.text
    assert client.get("/js/data.js").status_code == 200
    assert client.get("/api/stores").status_code == 200        # mounted last, so API routes still win
    assert client.get("/api/nope").status_code == 404


def test_hidden_junk_is_counted_and_listed_only_on_request(client):
    class Junky(Scraper):
        name = "Junky"

        async def search(self, query):
            items = [Listing(store=self.name, title=f"Ninja Air Fryer {i}L", price=10000.0 + i, url=f"https://j.test/{i}") for i in range(5)]
            items.append(Listing(store=self.name, title="Air Fryer Liner 40 pack", price=500.0, url="https://j.test/liner"))
            return StoreResult(store=self.name, status=StoreStatus.OK, listings=items)

    with TestClient(create_app(":memory:", stores=[Junky()])) as c:
        c.post("/api/refresh", params={"q": "air fryer"})
        plain = c.get("/api/search", params={"q": "air fryer"}).json()
        assert plain["count"] == 5 and plain["hidden_count"] == 1 and plain["hidden"] == []
        full = c.get("/api/search", params={"q": "air fryer", "show_hidden": "true"}).json()
        assert full["hidden"][0]["title"].startswith("Air Fryer Liner")
        assert "accessory" in full["hidden"][0]["hidden_reason"]


def test_search_returns_listings_merged_by_product(client):
    class TwoStores(Scraper):
        name = "Shop"

        async def search(self, query):
            items = [
                Listing(store="Shop A", title="Samsung 32H5000 32\" Inch Smart TV", price=21386.0, url="https://a.test/tv"),
                Listing(store="Shop B", title="Samsung 32\" LED TV UA32H5000FUXKE", price=22990.0, url="https://b.test/tv"),
                Listing(store="Shop B", title="Samsung 55\" LED UHD TV UA55U8000FUXKE", price=57990.0, url="https://b.test/tv55"),
                Listing(store="Shop A", title="Samsung Smart TV Full HD Netflix", price=33000.0, url="https://a.test/plain"),
            ]
            return StoreResult(store=self.name, status=StoreStatus.OK, listings=items)

    with TestClient(create_app(":memory:", stores=[TwoStores()])) as c:
        c.post("/api/refresh", params={"q": "samsung tv"})
        body = c.get("/api/search", params={"q": "samsung tv"}).json()
        assert body["count"] == 4 and len(body["groups"]) == 3          # two shops' 32" TVs merged
        merged = next(g for g in body["groups"] if g["store_count"] == 2)
        assert merged["best_price"] == 21386.0 and merged["highest_price"] == 22990.0
        assert [m["price"] for m in merged["members"]] == [21386.0, 22990.0]
        assert merged["key"] == "samsung | H5000 | 32in | new"
        alone = next(g for g in body["groups"] if g["key"] is None)
        assert alone["store_count"] == 1
        assert merged["brand"] == "samsung" and merged["condition"] == "new"
        assert alone["brand"] == "samsung" and alone["condition"] == "new"   # brand known even without a model


# ── price history ─────────────────────────────────────────────────────────────

def seed_history(conn):
    """A TV that fell from 50,000 to 45,000 four days ago at Jumia; Hotpoint steady at 48,000."""
    from datetime import datetime, timedelta, timezone

    def days_ago(d):
        return (datetime.now(timezone.utc) - timedelta(days=d)).isoformat(timespec="seconds")

    def add(store, url, title, points):
        lid = conn.execute("INSERT INTO listings (store, url, title, first_seen, last_seen) VALUES (?,?,?,?,?)",
                           (store, url, title, days_ago(points[0][0]), days_ago(0))).lastrowid
        for d, price, stock in points:
            conn.execute("INSERT INTO price_points (listing_id, price, in_stock, seen_at) VALUES (?,?,?,?)",
                         (lid, price, int(stock), days_ago(d)))
        return lid

    a = add("Jumia", "https://j.test/tv", "Samsung 43U8000 43\" Crystal UHD 4K Smart TV", [(12, 50000.0, True), (4, 45000.0, True)])
    b = add("Hotpoint", "https://h.test/tv", "Samsung 43\" LED UHD TV UA43U8000FUXKE", [(10, 48000.0, True)])
    add("Avechi", "https://av.test/tv", "Samsung 43 Inch U8000F Smart TV", [(9, 40000.0, False)])      # sold out, so never the best
    conn.commit()
    return a, b


def test_history_endpoint_gives_the_best_price_over_time_and_a_summary(client):
    a, b = seed_history(client.app.state.conn)
    body = client.get("/api/history", params={"ids": f"{a},{b}"}).json()
    assert [c["price"] for c in body["best"]] == [50000.0, 48000.0, 45000.0]
    assert "Avechi" not in {s["store"] for s in body["stores"]}               # sold out the whole time: no line
    assert {s["store"]: [p["price"] for p in s["points"]] for s in body["stores"]} == {
        "Jumia": [50000.0, 45000.0], "Hotpoint": [48000.0]}
    s = body["summary"]
    assert s["current"] == 45000.0 and s["previous"] == 48000.0 and s["drop"] == 3000.0
    assert s["lowest_ever"] == 45000.0 and s["highest_ever"] == 50000.0 and s["is_lowest_ever"] is True


def test_search_marks_a_recent_price_drop_and_a_lowest_ever(client):
    seed_history(client.app.state.conn)
    group = client.get("/api/search", params={"q": "samsung tv"}).json()["groups"][0]
    assert group["store_count"] == 3                    # the sold-out Avechi listing is the same product
    assert group["price_drop"] == 3000.0 and group["previous_best"] == 48000.0 and group["lowest_ever"] is True


def test_drops_lists_products_whose_best_price_fell_with_their_search(client):
    seed_history(client.app.state.conn)
    client.get("/api/search", params={"q": "samsung tv"})           # makes it a popular search, so it is looked at
    drops = client.get("/api/drops").json()
    assert len(drops) == 1
    d = drops[0]
    assert d["query"] == "samsung tv" and d["price_drop"] == 3000.0 and d["previous_best"] == 48000.0
    assert d["best_price"] == 45000.0 and d["id"]                     # enough to link to the product page


def test_drops_leave_out_international_prices(client):
    conn = client.app.state.conn
    from datetime import datetime, timedelta, timezone
    ago = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).isoformat(timespec="seconds")
    lid = conn.execute("INSERT INTO listings (store, url, title, first_seen, last_seen) VALUES (?,?,?,?,?)",
                       ("Amazon", "https://a.test/tv", "Samsung 43U8000 43\" Crystal UHD 4K Smart TV", ago(9), ago(0))).lastrowid
    for d, price in [(9, 50000.0), (2, 40000.0)]:
        conn.execute("INSERT INTO price_points (listing_id, price, in_stock, converted, seen_at) VALUES (?,?,1,1,?)", (lid, price, ago(d)))
    conn.commit()
    client.get("/api/search", params={"q": "samsung tv"})
    assert client.get("/api/drops").json() == []


def test_an_international_listing_appearing_cheaper_is_not_a_drop(client):
    conn = client.app.state.conn
    from datetime import datetime, timedelta, timezone
    ago = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).isoformat(timespec="seconds")

    def add(store, url, d, price, converted):
        lid = conn.execute("INSERT INTO listings (store, url, title, first_seen, last_seen) VALUES (?,?,?,?,?)",
                           (store, url, "Samsung 43U8000 43\" Crystal UHD 4K Smart TV", ago(d), ago(0))).lastrowid
        conn.execute("INSERT INTO price_points (listing_id, price, in_stock, converted, seen_at) VALUES (?,?,1,?,?)",
                     (lid, price, int(converted), ago(d)))

    add("Jumia", "https://j.test/tv", 9, 50000.0, False)        # steady in Kenya
    add("Amazon", "https://a.test/tv", 2, 38000.0, True)        # turns up two days ago, cheaper
    conn.commit()
    client.get("/api/search", params={"q": "samsung tv"})
    assert client.get("/api/drops").json() == []


def test_popular_puts_searches_people_make_first(client):
    for _ in range(3):
        client.get("/api/search", params={"q": "Air Fryer"})
    popular = client.get("/api/popular").json()
    assert popular[0] == "air fryer" and len(popular) <= 8


def test_a_product_with_no_movement_has_no_badges(client):
    conn = client.app.state.conn
    client.post("/api/refresh", params={"q": "samsung tv"})
    group = client.get("/api/search", params={"q": "samsung tv"}).json()["groups"][0]
    assert group["price_drop"] is None and group["lowest_ever"] is False


@pytest.mark.parametrize("ids", ["abc", "1,,x", ""])
def test_history_rejects_bad_ids(client, ids):
    assert client.get("/api/history", params={"ids": ids}).status_code == 422


def test_history_for_unknown_listings_is_404(client):
    assert client.get("/api/history", params={"ids": "9999"}).status_code == 404


def test_international_listings_are_flagged_in_search_results():
    class Mixed(Scraper):
        name = "Mixed"

        async def search(self, query):
            items = [Listing(store="Local", title="Samsung 32 Inch Smart TV H5000", price=21000.0, url="https://l.test/tv"),
                     Listing(store="Amazon", title="Samsung 32-Inch Class HD H5000F Smart TV", price=19089.0, url="https://a.test/tv", converted=True)]
            return StoreResult(store=self.name, status=StoreStatus.OK, listings=items)

    with TestClient(create_app(":memory:", stores=[Mixed()])) as c:
        c.post("/api/refresh", params={"q": "samsung tv"})
        flags = {r["store"]: r["converted"] for r in c.get("/api/search", params={"q": "samsung tv"}).json()["results"]}
        assert flags == {"Local": False, "Amazon": True}
