"""SQLite storage: listings, their price history, scrape outcomes and watches."""

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id         INTEGER PRIMARY KEY,
    store      TEXT NOT NULL,
    url        TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    image_url  TEXT,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_store ON listings(store);

CREATE TABLE IF NOT EXISTS price_points (
    id         INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price      REAL NOT NULL,
    old_price  REAL,                          -- struck-through price shown by the store, if any
    in_stock   INTEGER NOT NULL DEFAULT 1,
    converted  INTEGER NOT NULL DEFAULT 0,
    seen_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_points_listing ON price_points(listing_id, seen_at);

CREATE TABLE IF NOT EXISTS store_runs (
    id          INTEGER PRIMARY KEY,
    store       TEXT NOT NULL,
    query       TEXT NOT NULL,
    status      TEXT NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    message     TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    ran_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_store_runs_store ON store_runs(store, ran_at);

CREATE TABLE IF NOT EXISTS searches (
    query    TEXT PRIMARY KEY,               -- normalised: lower case, single spaces
    times    INTEGER NOT NULL DEFAULT 1,
    first_at TEXT NOT NULL,
    last_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watches (
    id                 INTEGER PRIMARY KEY,
    query              TEXT NOT NULL,
    target_price       REAL NOT NULL,
    email              TEXT NOT NULL,
    token              TEXT NOT NULL UNIQUE,   -- secret in the confirm, unsubscribe and manage links
    confirmed          INTEGER NOT NULL DEFAULT 0,
    last_alerted_price REAL,
    created_at         TEXT NOT NULL,
    product_key        TEXT,                   -- watch one product (see products.ProductKey); NULL: the cheapest match for the query
    label              TEXT,                   -- what to call it in emails, e.g. the product title
    confirmed_at       TEXT,
    last_mailed_at     TEXT                    -- when the last confirmation email went out
);
"""

# Columns added after the first release of the schema: databases created earlier get them on connect.
_WATCH_COLUMNS = {"product_key": "TEXT", "label": "TEXT", "confirmed_at": "TEXT", "last_mailed_at": "TEXT"}


def _upgrade(conn: sqlite3.Connection) -> None:
    have = {row["name"] for row in conn.execute("PRAGMA table_info(watches)")}
    for name, kind in _WATCH_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE watches ADD COLUMN {name} {kind}")
    conn.commit()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str = "beismart_v2.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)  # the API serialises access itself
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")   # wait for the other process instead of failing
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # the web server and the refresh job share this file
    conn.executescript(SCHEMA)
    _upgrade(conn)
    return conn
