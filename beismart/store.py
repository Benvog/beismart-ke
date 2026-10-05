"""Saving scrape results and searching the saved data."""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import now
from .matching import junk_reason, typical_price
from .models import Listing, StoreResult
from .parsing import is_relevant

# A price point is only added when something changed, or once a day so a chart has no holes.
HEARTBEAT = timedelta(hours=20)
# Listings not seen for this long are treated as gone from the store.
FRESH_FOR = timedelta(days=3)


@dataclass
class SavedListing:
    """A listing as search returns it: the product plus its latest price."""
    id: int
    store: str
    title: str
    url: str
    image_url: Optional[str]
    price: float
    old_price: Optional[float]
    in_stock: bool
    last_seen: str
    converted: bool = False               # priced in another currency (international, excludes shipping and import fees)
    hidden_reason: Optional[str] = None   # set when the listing looks like junk; None means show it


@dataclass
class SearchOutcome:
    shown: list[SavedListing]
    hidden: list[SavedListing]            # junk, each with the reason it was hidden


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def save_result(conn: sqlite3.Connection, result: StoreResult, query: str) -> int:
    """Record one scrape: the run itself, every listing, and a price point when it changed.
    Returns how many price points were added."""
    stamp = now()
    conn.execute(
        "INSERT INTO store_runs (store, query, status, count, message, duration_ms, ran_at) VALUES (?,?,?,?,?,?,?)",
        (result.store, query, result.status.value, len(result.listings), result.message, result.duration_ms, stamp),
    )
    added = 0
    for item in result.listings:
        added += _save_listing(conn, item, stamp)
    conn.commit()
    return added


def _save_listing(conn: sqlite3.Connection, item: Listing, stamp: str) -> int:
    item.title = " ".join(item.title.split())        # some stores put line breaks inside titles
    row = conn.execute("SELECT id FROM listings WHERE url = ?", (item.url,)).fetchone()
    if row:
        listing_id = row["id"]
        conn.execute(
            "UPDATE listings SET title = ?, image_url = COALESCE(?, image_url), last_seen = ? WHERE id = ?",
            (item.title, item.image_url, stamp, listing_id),
        )
    else:
        listing_id = conn.execute(
            "INSERT INTO listings (store, url, title, image_url, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
            (item.store, item.url, item.title, item.image_url, stamp, stamp),
        ).lastrowid

    last = conn.execute(
        "SELECT price, in_stock, seen_at FROM price_points WHERE listing_id = ? ORDER BY seen_at DESC, id DESC LIMIT 1",
        (listing_id,),
    ).fetchone()
    unchanged = (
        last
        and last["price"] == item.price
        and bool(last["in_stock"]) == item.in_stock
        and _parse_time(stamp) - _parse_time(last["seen_at"]) < HEARTBEAT
    )
    if unchanged:
        return 0
    conn.execute(
        "INSERT INTO price_points (listing_id, price, old_price, in_stock, converted, seen_at) VALUES (?,?,?,?,?,?)",
        (listing_id, item.price, item.old_price, int(item.in_stock), int(item.converted), stamp),
    )
    return 1


def search(conn: sqlite3.Connection, query: str, limit: int = 100) -> SearchOutcome:
    """Search saved listings: cheapest first, in-stock items before sold-out ones.

    Candidates come from SQL (every query word must appear in the title), then the same
    relevance rules the scrapers use are applied, so accessories stay out."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 2]
    if not words:
        return SearchOutcome([], [])
    cutoff = (datetime.now(timezone.utc) - FRESH_FOR).isoformat(timespec="seconds")
    where = " AND ".join("lower(l.title) LIKE ?" for _ in words)
    rows = conn.execute(
        f"""
        SELECT l.id, l.store, l.title, l.url, l.image_url, l.last_seen,
               p.price, p.old_price, p.in_stock, p.converted
        FROM listings l
        JOIN price_points p ON p.id = (
            SELECT id FROM price_points WHERE listing_id = l.id ORDER BY seen_at DESC, id DESC LIMIT 1
        )
        WHERE l.last_seen >= ? AND {where}
        ORDER BY p.in_stock DESC, p.price ASC
        """,
        (cutoff, *[f"%{_loose(w)}%" for w in words]),
    ).fetchall()
    found = [
        SavedListing(r["id"], r["store"], r["title"], r["url"], r["image_url"], r["price"],
                     r["old_price"], bool(r["in_stock"]), r["last_seen"], bool(r["converted"]))
        for r in rows
        if is_relevant(r["title"], query)
    ]
    return _split_junk(found, query, limit)


def _split_junk(found: list[SavedListing], query: str, limit: int) -> SearchOutcome:
    """Separate listings that look like junk (with a reason) from real results."""
    # Words first, so an obvious accessory cannot drag the "typical price" down.
    by_words = {l.id: junk_reason(l.title, l.price, query, None) for l in found}
    clean = [l.price for l in found if not by_words[l.id] and l.in_stock] or             [l.price for l in found if not by_words[l.id]]
    median = typical_price(clean)
    shown, hidden = [], []
    for l in found:
        l.hidden_reason = by_words[l.id] or junk_reason(l.title, l.price, query, median)
        (hidden if l.hidden_reason else shown).append(l)
    return SearchOutcome(shown=shown[:limit], hidden=hidden)


def search_saved(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[SavedListing]:
    """Search saved listings, junk left out: cheapest first, in-stock items before sold-out ones."""
    return search(conn, query, limit).shown


def _loose(word: str) -> str:
    """'headphones' also finds 'headphone': drop a plural 's' for the SQL match."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def store_status(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The most recent scrape outcome for each store."""
    return conn.execute(
        """
        SELECT store, status, count, message, duration_ms, ran_at, query
        FROM store_runs
        WHERE id IN (SELECT MAX(id) FROM store_runs GROUP BY store)
        ORDER BY store
        """
    ).fetchall()


def price_history(conn: sqlite3.Connection, listing_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT price, old_price, in_stock, seen_at FROM price_points WHERE listing_id = ? ORDER BY seen_at, id",
        (listing_id,),
    ).fetchall()


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def record_search(conn: sqlite3.Connection, query: str) -> None:
    """Count a search so popular ones can be kept fresh by the refresh job."""
    q, stamp = normalize_query(query), now()
    conn.execute(
        """
        INSERT INTO searches (query, times, first_at, last_at) VALUES (?, 1, ?, ?)
        ON CONFLICT(query) DO UPDATE SET times = times + 1, last_at = excluded.last_at
        """,
        (q, stamp, stamp),
    )
    conn.commit()


def popular_queries(conn: sqlite3.Connection, days: int = 14, limit: int = 20) -> list[str]:
    """Most-searched queries from the last `days` days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT query FROM searches WHERE last_at >= ? ORDER BY times DESC, last_at DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    return [r["query"] for r in rows]


def watched_queries(conn: sqlite3.Connection) -> list[str]:
    """Queries with at least one confirmed watch."""
    rows = conn.execute("SELECT DISTINCT query FROM watches WHERE confirmed = 1").fetchall()
    return sorted({normalize_query(r["query"]) for r in rows})


def tracked(conn: sqlite3.Connection, listing_ids: list[int]) -> dict[int, "Tracked"]:
    """The full price history of each listing, fetched in two queries however many listings there are."""
    from .history import Point, Tracked

    if not listing_ids:
        return {}
    marks = ",".join("?" for _ in listing_ids)
    listings = conn.execute(f"SELECT id, store, last_seen FROM listings WHERE id IN ({marks})", listing_ids).fetchall()
    out = {r["id"]: Tracked(store=r["store"], last_seen=r["last_seen"], points=[]) for r in listings}
    for r in conn.execute(
        f"SELECT listing_id, price, old_price, in_stock, seen_at FROM price_points WHERE listing_id IN ({marks}) ORDER BY seen_at, id",
        listing_ids,
    ):
        out[r["listing_id"]].points.append(Point(at=r["seen_at"], price=r["price"], in_stock=bool(r["in_stock"]), old_price=r["old_price"]))
    return out
