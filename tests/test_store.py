from datetime import datetime, timedelta, timezone

import pytest

from beismart import store
from beismart.db import connect
from beismart.models import Listing, StoreResult, StoreStatus


@pytest.fixture
def conn():
    return connect(":memory:")


def listing(url="https://a.test/1", title="Samsung 43 Inch Smart TV", price=40000.0, **kw):
    return Listing(store=kw.pop("store", "A"), title=title, price=price, url=url, **kw)


def result(*listings, store_name="A", status=StoreStatus.OK):
    return StoreResult(store=store_name, status=status, listings=list(listings))


def age(conn, hours):
    """Pretend every saved row was written `hours` ago."""
    when = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    conn.execute("UPDATE price_points SET seen_at = ?", (when,))
    conn.execute("UPDATE listings SET last_seen = ?", (when,))
    conn.commit()


def test_saving_creates_a_listing_and_a_price_point(conn):
    added = store.save_result(conn, result(listing()), "samsung tv")
    assert added == 1
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM price_points").fetchone()[0] == 1


def test_the_same_product_seen_again_is_one_listing(conn):
    store.save_result(conn, result(listing()), "samsung tv")
    store.save_result(conn, result(listing()), "samsung tv")
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1


def test_an_unchanged_price_does_not_add_a_price_point(conn):
    store.save_result(conn, result(listing()), "samsung tv")
    assert store.save_result(conn, result(listing()), "samsung tv") == 0


def test_a_changed_price_adds_a_price_point_and_history_keeps_both(conn):
    store.save_result(conn, result(listing(price=40000.0)), "samsung tv")
    age(conn, 2)
    store.save_result(conn, result(listing(price=37500.0)), "samsung tv")
    history = store.price_history(conn, 1)
    assert [h["price"] for h in history] == [40000.0, 37500.0]


def test_going_out_of_stock_is_recorded(conn):
    store.save_result(conn, result(listing()), "samsung tv")
    age(conn, 2)
    assert store.save_result(conn, result(listing(in_stock=False)), "samsung tv") == 1


def test_an_old_unchanged_price_is_recorded_again_once_a_day(conn):
    store.save_result(conn, result(listing()), "samsung tv")
    age(conn, 25)
    assert store.save_result(conn, result(listing()), "samsung tv") == 1


def test_every_run_is_logged_including_failures(conn):
    store.save_result(conn, result(store_name="Jumia", status=StoreStatus.BLOCKED), "samsung tv")
    row = store.store_status(conn)[0]
    assert row["store"] == "Jumia" and row["status"] == "blocked"


def test_store_status_shows_only_the_latest_run_per_store(conn):
    store.save_result(conn, result(store_name="Jumia", status=StoreStatus.BLOCKED), "a")
    store.save_result(conn, result(listing(store="Jumia"), store_name="Jumia"), "a")
    rows = store.store_status(conn)
    assert len(rows) == 1 and rows[0]["status"] == "ok"


def test_search_finds_listings_cheapest_first(conn):
    store.save_result(conn, result(
        listing("https://a.test/1", "Samsung 55 Inch Smart TV", 70000.0),
        listing("https://a.test/2", "Samsung 32 Inch Smart TV", 20000.0),
    ), "samsung tv")
    found = store.search_saved(conn, "samsung tv")
    assert [f.price for f in found] == [20000.0, 70000.0]


def test_search_puts_sold_out_items_last(conn):
    store.save_result(conn, result(
        listing("https://a.test/1", "Samsung 55 Inch Smart TV", 10000.0, in_stock=False),
        listing("https://a.test/2", "Samsung 32 Inch Smart TV", 20000.0),
    ), "samsung tv")
    found = store.search_saved(conn, "samsung tv")
    assert [f.in_stock for f in found] == [True, False]


def test_search_needs_every_word_and_drops_accessories(conn):
    store.save_result(conn, result(
        listing("https://a.test/1", "Samsung 32 Inch Smart TV", 20000.0),
        listing("https://a.test/2", "Samsung TV Wall Mount Bracket", 900.0),
        listing("https://a.test/3", "Hisense 32 Inch Smart TV", 18000.0),
    ), "tv")
    found = store.search_saved(conn, "samsung tv")
    assert [f.url for f in found] == ["https://a.test/1"]


def test_search_returns_the_latest_price_and_old_price(conn):
    store.save_result(conn, result(listing(price=40000.0)), "samsung tv")
    age(conn, 2)
    store.save_result(conn, result(listing(price=37500.0, old_price=40000.0)), "samsung tv")
    found = store.search_saved(conn, "samsung tv")
    assert found[0].price == 37500.0 and found[0].old_price == 40000.0


def test_listings_not_seen_for_days_are_not_returned(conn):
    store.save_result(conn, result(listing()), "samsung tv")
    age(conn, 24 * 5)
    assert store.search_saved(conn, "samsung tv") == []


def test_plural_search_finds_singular_titles(conn):
    store.save_result(conn, result(listing(title="M48 Bluetooth Headphone Wireless")), "headphones")
    assert len(store.search_saved(conn, "headphones")) == 1


def test_empty_query_returns_nothing(conn):
    assert store.search_saved(conn, "  ") == []


# ── junk hiding ───────────────────────────────────────────────────────────────

def save_many(conn, *items):
    store.save_result(conn, result(*items), "air fryer")


def fryers(conn):
    save_many(
        conn,
        listing("https://a.test/1", "Ninja Air Fryer 5L", 12000.0),
        listing("https://a.test/2", "Philips Air Fryer XL", 15000.0),
        listing("https://a.test/3", "Tefal Air Fryer 4L", 11000.0),
        listing("https://a.test/4", "Chefman Air Fryer 6L", 9500.0),
        listing("https://a.test/5", "Disposable Air Fryer Liner Square 40", 595.0),
        listing("https://a.test/6", "Mystery Air Fryer", 400.0),
    )


def test_junk_is_hidden_by_default_and_counted(conn):
    fryers(conn)
    outcome = store.search(conn, "air fryer")
    assert [l.url for l in store.search_saved(conn, "air fryer")] == [l.url for l in outcome.shown]
    assert {l.url for l in outcome.hidden} == {"https://a.test/5", "https://a.test/6"}


def test_every_hidden_listing_says_why(conn):
    fryers(conn)
    reasons = {l.url: l.hidden_reason for l in store.search(conn, "air fryer").hidden}
    assert "accessory" in reasons["https://a.test/5"]
    assert "far below" in reasons["https://a.test/6"]


def test_shown_listings_have_no_reason(conn):
    fryers(conn)
    assert all(l.hidden_reason is None for l in store.search(conn, "air fryer").shown)


def test_an_accessory_cannot_drag_the_typical_price_down(conn):
    # five cheap liners plus real fryers: the liners must not make the real ones look expensive,
    # nor hide a real cheap fryer
    save_many(
        conn,
        *[listing(f"https://a.test/l{i}", f"Air Fryer Liner pack {i}", 500.0 + i) for i in range(5)],
        listing("https://a.test/r1", "Ninja Air Fryer 5L", 12000.0),
        listing("https://a.test/r2", "Tefal Air Fryer 4L", 9000.0),
        listing("https://a.test/r3", "Chefman Air Fryer 6L", 7000.0),
        listing("https://a.test/r4", "Philips Air Fryer XL", 15000.0),
        listing("https://a.test/r5", "Kenwood Air Fryer 3L", 6500.0),
    )
    shown = {l.url for l in store.search(conn, "air fryer").shown}
    assert {f"https://a.test/r{i}" for i in range(1, 6)} <= shown


def test_searching_for_the_accessory_shows_it(conn):
    fryers(conn)
    assert any("Liner" in l.title for l in store.search(conn, "air fryer liner").shown)


def test_too_few_results_means_no_price_judgement(conn):
    save_many(
        conn,
        listing("https://a.test/1", "Ninja Air Fryer 5L", 12000.0),
        listing("https://a.test/2", "Odd Air Fryer", 90.0),
    )
    assert len(store.search(conn, "air fryer").shown) == 2


def test_line_breaks_inside_titles_are_flattened(conn):
    store.save_result(conn, result(listing(title="Selim German 8 Litres Digital Air Fryer\nThis 8-litre  air fryer")), "air fryer")
    assert store.search_saved(conn, "air fryer")[0].title == "Selim German 8 Litres Digital Air Fryer This 8-litre air fryer"
