"""Price-alert watches: someone asks to be emailed when a price falls to a target.

A watch starts unconfirmed and does nothing until the person clicks the link in the confirmation email,
which proves the address is theirs and stops anyone signing a stranger up. There are no accounts: a
secret token in the emailed links is what lets a person confirm, list and remove their own watches."""

import math
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import now
from .store import normalize_query

MAX_WATCHES_PER_EMAIL = 10
MAX_NEW_WATCHES_PER_EMAIL_PER_DAY = 5
RESEND_CONFIRMATION_AFTER = timedelta(minutes=10)
PENDING_EXPIRES_AFTER = timedelta(days=3)
MAX_TARGET_PRICE = 100_000_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class WatchError(Exception):
    """The request cannot be accepted. `kind` is "invalid" (fix the input) or "limit" (try later)."""

    def __init__(self, message: str, kind: str = "invalid"):
        super().__init__(message)
        self.message, self.kind = message, kind


@dataclass
class Watch:
    id: int
    query: str
    product_key: Optional[str]
    label: Optional[str]
    target_price: float
    email: str
    token: str
    confirmed: bool
    last_alerted_price: Optional[float]
    created_at: str

    @property
    def name(self) -> str:
        """What to call the watch in emails."""
        return self.label or self.query


_COLUMNS = "id, query, product_key, label, target_price, email, token, confirmed, last_alerted_price, created_at"


def _watch(row: sqlite3.Row) -> Watch:
    return Watch(id=row["id"], query=row["query"], product_key=row["product_key"], label=row["label"],
                 target_price=row["target_price"], email=row["email"], token=row["token"],
                 confirmed=bool(row["confirmed"]), last_alerted_price=row["last_alerted_price"],
                 created_at=row["created_at"])


def create_watch(conn: sqlite3.Connection, *, query: str, target_price: float, email: str,
                 product_key: Optional[str] = None, label: Optional[str] = None) -> tuple[Watch, bool]:
    """Add a watch. Returns (watch, send_confirmation): whether a confirmation email should go out now.

    Asking again for the same thing updates the target price instead of adding a second watch."""
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise WatchError("That does not look like a valid email address.")
    query = normalize_query(query)
    if not 2 <= len(query) <= 100:
        raise WatchError("The product to watch must be between 2 and 100 characters.")
    if not isinstance(target_price, (int, float)) or not math.isfinite(target_price) or not 0 < target_price <= MAX_TARGET_PRICE:
        raise WatchError("The target price must be a positive amount in KSh.")
    label = " ".join(label.split())[:150] if label else None

    existing = conn.execute(
        f"SELECT {_COLUMNS}, confirmed_at, last_mailed_at FROM watches WHERE email = ? AND query = ? AND COALESCE(product_key, '') = ?",
        (email, query, product_key or ""),
    ).fetchone()
    if existing:
        conn.execute("UPDATE watches SET target_price = ?, label = COALESCE(?, label) WHERE id = ?",
                     (float(target_price), label, existing["id"]))
        watch = _watch(conn.execute(f"SELECT {_COLUMNS} FROM watches WHERE id = ?", (existing["id"],)).fetchone())
        send = False
        if not watch.confirmed:
            last = existing["last_mailed_at"]
            send = last is None or datetime.fromisoformat(now()) - datetime.fromisoformat(last) >= RESEND_CONFIRMATION_AFTER
        conn.commit()
        return watch, send

    total = conn.execute("SELECT COUNT(*) FROM watches WHERE email = ?", (email,)).fetchone()[0]
    if total >= MAX_WATCHES_PER_EMAIL:
        raise WatchError(f"There are already {MAX_WATCHES_PER_EMAIL} watches for this address. Remove one first.", "limit")
    since = (datetime.fromisoformat(now()) - timedelta(days=1)).isoformat(timespec="seconds")
    recent = conn.execute("SELECT COUNT(*) FROM watches WHERE email = ? AND created_at >= ?", (email, since)).fetchone()[0]
    if recent >= MAX_NEW_WATCHES_PER_EMAIL_PER_DAY:
        raise WatchError("Too many new watches for this address today. Try again tomorrow.", "limit")

    cursor = conn.execute(
        "INSERT INTO watches (query, product_key, label, target_price, email, token, confirmed, created_at) VALUES (?,?,?,?,?,?,0,?)",
        (query, product_key, label, float(target_price), email, secrets.token_urlsafe(24), now()),
    )
    conn.commit()
    return _watch(conn.execute(f"SELECT {_COLUMNS} FROM watches WHERE id = ?", (cursor.lastrowid,)).fetchone()), True


def mark_mailed(conn: sqlite3.Connection, watch_id: int) -> None:
    conn.execute("UPDATE watches SET last_mailed_at = ? WHERE id = ?", (now(), watch_id))
    conn.commit()


def confirm(conn: sqlite3.Connection, token: str) -> Optional[Watch]:
    """Switch the watch on. Safe to open twice. None if the link is not valid."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM watches WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    if not row["confirmed"]:
        conn.execute("UPDATE watches SET confirmed = 1, confirmed_at = ? WHERE id = ?", (now(), row["id"]))
        conn.commit()
        row = conn.execute(f"SELECT {_COLUMNS} FROM watches WHERE id = ?", (row["id"],)).fetchone()
    return _watch(row)


def unsubscribe(conn: sqlite3.Connection, token: str) -> Optional[Watch]:
    """Delete the watch. Returns what was removed, or None if the link is not valid (or already used)."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM watches WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM watches WHERE id = ?", (row["id"],))
    conn.commit()
    return _watch(row)


def for_token(conn: sqlite3.Connection, token: str) -> list[Watch]:
    """Every watch of the person who owns this token (empty if the token is not valid)."""
    row = conn.execute("SELECT email FROM watches WHERE token = ?", (token,)).fetchone()
    if row is None:
        return []
    return [_watch(r) for r in conn.execute(
        f"SELECT {_COLUMNS} FROM watches WHERE email = ? ORDER BY created_at, id", (row["email"],))]


def purge_pending(conn: sqlite3.Connection) -> int:
    """Delete watches never confirmed within a few days, so a mistyped address leaves nothing behind."""
    cutoff = (datetime.fromisoformat(now()) - PENDING_EXPIRES_AFTER).isoformat(timespec="seconds")
    cursor = conn.execute("DELETE FROM watches WHERE confirmed = 0 AND created_at < ?", (cutoff,))
    conn.commit()
    return cursor.rowcount


def get(conn: sqlite3.Connection, watch_id: int) -> Optional[Watch]:
    row = conn.execute(f"SELECT {_COLUMNS} FROM watches WHERE id = ?", (watch_id,)).fetchone()
    return _watch(row) if row else None
