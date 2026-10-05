from datetime import datetime, timedelta, timezone

from beismart.history import Point, Tracked, build_history

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


def listing(store, *points, last_seen_days_ago=0.0):
    return Tracked(store=store, last_seen=at(last_seen_days_ago), points=[
        Point(at=at(d), price=p, in_stock=s) for d, p, s in points
    ])


def prices(series):
    return [c.price for c in series]


def test_no_listings_means_empty_history():
    h = build_history([], NOW)
    assert h.best == [] and h.summary.current is None and not h.summary.is_lowest_ever


def test_one_listing_one_price_has_no_changes_to_show():
    h = build_history([listing("Jumia", (5, 50000.0, True))], NOW)
    assert prices(h.best) == [50000.0]
    assert h.summary.current == 50000.0 and h.summary.drop is None and not h.summary.is_lowest_ever


def test_a_price_drop_is_recorded_and_flagged_when_recent():
    h = build_history([listing("Jumia", (6, 50000.0, True), (2, 45000.0, True))], NOW)
    assert prices(h.best) == [50000.0, 45000.0]
    s = h.summary
    assert s.current == 45000.0 and s.previous == 50000.0 and s.drop == 5000.0
    assert s.is_lowest_ever and s.lowest_ever == 45000.0 and s.highest_ever == 50000.0


def test_an_old_drop_is_not_called_recent():
    h = build_history([listing("Jumia", (30, 50000.0, True), (20, 45000.0, True), last_seen_days_ago=0)], NOW)
    assert h.summary.drop is None and h.summary.previous == 50000.0


def test_a_price_rise_is_not_a_drop():
    h = build_history([listing("Jumia", (6, 45000.0, True), (2, 50000.0, True))], NOW)
    s = h.summary
    assert s.current == 50000.0 and s.drop is None and not s.is_lowest_ever and s.lowest_ever == 45000.0


def test_repeated_identical_prices_collapse_into_one_point():
    h = build_history([listing("Jumia", (4, 50000.0, True), (3, 50000.0, True), (2, 50000.0, True), (1, 50000.0, True))], NOW)
    assert prices(h.best) == [50000.0]


def test_best_is_the_cheapest_across_stores_over_time():
    h = build_history([
        listing("Jumia", (8, 50000.0, True), (3, 46000.0, True)),
        listing("Hotpoint", (6, 48000.0, True)),
    ], NOW)
    # day 8: only Jumia (50000); day 6: Hotpoint joins at 48000; day 3: Jumia falls to 46000
    assert prices(h.best) == [50000.0, 48000.0, 46000.0]
    assert prices(h.by_store["Jumia"]) == [50000.0, 46000.0]
    assert prices(h.by_store["Hotpoint"]) == [48000.0]


def test_a_sold_out_listing_does_not_set_the_best_price():
    h = build_history([
        listing("Jumia", (5, 40000.0, False)),                       # cheaper but sold out
        listing("Hotpoint", (5, 47000.0, True)),
    ], NOW)
    assert prices(h.best) == [47000.0]
    assert h.summary.current == 47000.0


def test_going_out_of_stock_then_back_changes_the_best_price():
    h = build_history([listing("Jumia", (6, 40000.0, True), (4, 40000.0, False), (2, 41000.0, True))], NOW)
    assert prices(h.best) == [40000.0, None, 41000.0]
    assert h.summary.current == 41000.0 and h.summary.drop is None


def test_nothing_in_stock_now_means_no_current_price():
    h = build_history([listing("Jumia", (6, 40000.0, True), (1, 40000.0, False))], NOW)
    assert h.summary.current is None and h.summary.lowest_ever == 40000.0


def test_a_listing_the_store_stopped_showing_stops_counting():
    # Hotpoint was cheapest but was last seen 10 days ago: it should not hold the best price down forever
    h = build_history([
        listing("Hotpoint", (20, 40000.0, True), last_seen_days_ago=10),
        listing("Jumia", (20, 48000.0, True)),
    ], NOW)
    assert prices(h.best) == [40000.0, 48000.0]
    assert h.summary.current == 48000.0


def test_a_listing_not_yet_seen_does_not_count_before_its_first_point():
    h = build_history([listing("Jumia", (10, 50000.0, True)), listing("Hotpoint", (3, 45000.0, True))], NOW)
    assert prices(h.best) == [50000.0, 45000.0]


def test_is_lowest_ever_needs_the_price_to_have_moved():
    h = build_history([listing("Jumia", (4, 50000.0, True), (2, 50000.0, True))], NOW)
    assert not h.summary.is_lowest_ever
