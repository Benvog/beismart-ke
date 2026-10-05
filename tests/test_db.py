import sqlite3

from beismart.db import connect, now


def test_schema_creates_all_tables():
    conn = connect(":memory:")
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"listings", "price_points", "store_runs", "watches"} <= names


def test_listing_url_is_unique():
    conn = connect(":memory:")
    row = ("Jumia", "https://x/1", "TV", now(), now())
    sql = "INSERT INTO listings (store, url, title, first_seen, last_seen) VALUES (?,?,?,?,?)"
    conn.execute(sql, row)
    try:
        conn.execute(sql, row)
        assert False, "duplicate url should be rejected"
    except sqlite3.IntegrityError:
        pass


def test_price_points_follow_their_listing():
    conn = connect(":memory:")
    conn.execute("INSERT INTO listings (store, url, title, first_seen, last_seen) VALUES ('A','u','t',?,?)", (now(), now()))
    conn.execute("INSERT INTO price_points (listing_id, price, seen_at) VALUES (1, 100, ?)", (now(),))
    conn.execute("DELETE FROM listings WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) FROM price_points").fetchone()[0] == 0
