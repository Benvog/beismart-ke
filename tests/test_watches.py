from datetime import datetime, timedelta, timezone

import pytest

from beismart import watches
from beismart.db import connect, now
from beismart.watches import WatchError


@pytest.fixture
def conn():
    return connect(":memory:")


def make(conn, **kw):
    args = dict(query="samsung tv", target_price=30000, email="Ben@Example.com")
    args.update(kw)
    return watches.create_watch(conn, **args)


def age(conn, watch_id, **delta):
    when = (datetime.now(timezone.utc) - timedelta(**delta)).isoformat(timespec="seconds")
    conn.execute("UPDATE watches SET created_at = ? WHERE id = ?", (when, watch_id))
    conn.commit()


def test_a_new_watch_starts_unconfirmed_and_asks_for_a_confirmation_email(conn):
    watch, send = make(conn)
    assert send is True and watch.confirmed is False
    assert watch.email == "ben@example.com" and watch.query == "samsung tv" and len(watch.token) >= 24


def test_tokens_are_unique_and_unguessable_looking(conn):
    a, _ = make(conn)
    b, _ = make(conn, query="fridge")
    assert a.token != b.token


@pytest.mark.parametrize("email", ["", "nope", "a@b", "a b@c.com", "@x.com", "a@" + "x" * 260 + ".com"])
def test_bad_emails_are_rejected(conn, email):
    with pytest.raises(WatchError) as e:
        make(conn, email=email)
    assert e.value.kind == "invalid"


@pytest.mark.parametrize("price", [0, -5, float("nan"), float("inf"), 10**12])
def test_bad_prices_are_rejected(conn, price):
    with pytest.raises(WatchError) as e:
        make(conn, target_price=price)
    assert e.value.kind == "invalid"


def test_a_too_short_query_is_rejected(conn):
    with pytest.raises(WatchError):
        make(conn, query=" a ")


def test_confirming_switches_the_watch_on_and_can_be_repeated(conn):
    watch, _ = make(conn)
    first = watches.confirm(conn, watch.token)
    again = watches.confirm(conn, watch.token)
    assert first.confirmed and again.confirmed
    assert conn.execute("SELECT confirmed_at FROM watches").fetchone()[0] is not None


def test_a_wrong_token_confirms_nothing(conn):
    make(conn)
    assert watches.confirm(conn, "not-a-token") is None
    assert conn.execute("SELECT confirmed FROM watches").fetchone()[0] == 0


def test_asking_again_updates_the_target_instead_of_adding_a_second_watch(conn):
    first, _ = make(conn, target_price=30000)
    watches.mark_mailed(conn, first.id)               # the confirmation email went out
    second, send = make(conn, target_price=28000)
    assert second.id == first.id and second.target_price == 28000.0
    assert conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0] == 1
    assert send is False                              # no second confirmation email so soon


def test_a_watch_that_was_never_mailed_gets_its_confirmation(conn):
    first, _ = make(conn)                             # e.g. the send failed the first time
    _, send = make(conn)
    assert send is True


def test_the_confirmation_is_resent_only_after_a_while(conn):
    watch, _ = make(conn)
    watches.mark_mailed(conn, watch.id)
    _, send_now = make(conn)
    assert send_now is False
    conn.execute("UPDATE watches SET last_mailed_at = ? WHERE id = ?",
                 ((datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(timespec="seconds"), watch.id))
    _, send_later = make(conn)
    assert send_later is True


def test_changing_the_target_of_a_confirmed_watch_needs_no_new_confirmation(conn):
    watch, _ = make(conn)
    watches.confirm(conn, watch.token)
    updated, send = make(conn, target_price=25000)
    assert send is False and updated.confirmed and updated.target_price == 25000.0


def test_watching_one_product_is_separate_from_watching_the_search(conn):
    make(conn)
    make(conn, product_key="samsung | H5000 | 32in | new", label="Samsung 32 inch H5000")
    assert conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0] == 2


def test_an_address_is_limited_to_ten_watches(conn):
    for i in range(watches.MAX_WATCHES_PER_EMAIL):
        w, _ = make(conn, query=f"thing {i}")
        age(conn, w.id, days=2)                       # spread out, so only the total limit applies
    with pytest.raises(WatchError) as e:
        make(conn, query="one more")
    assert e.value.kind == "limit"


def test_an_address_cannot_create_many_new_watches_in_a_day(conn):
    for i in range(watches.MAX_NEW_WATCHES_PER_EMAIL_PER_DAY):
        make(conn, query=f"thing {i}")
    with pytest.raises(WatchError) as e:
        make(conn, query="sixth")
    assert e.value.kind == "limit"


def test_unsubscribing_deletes_the_watch_and_the_link_then_stops_working(conn):
    watch, _ = make(conn)
    assert watches.unsubscribe(conn, watch.token).id == watch.id
    assert watches.unsubscribe(conn, watch.token) is None
    assert conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0] == 0


def test_a_token_lists_only_its_owners_watches(conn):
    mine, _ = make(conn)
    make(conn, query="fridge")
    other, _ = make(conn, email="someone@else.com")
    assert {w.query for w in watches.for_token(conn, mine.token)} == {"samsung tv", "fridge"}
    assert [w.email for w in watches.for_token(conn, other.token)] == ["someone@else.com"]
    assert watches.for_token(conn, "nope") == []


def test_unconfirmed_watches_expire_but_confirmed_ones_stay(conn):
    stale, _ = make(conn, query="never confirmed")
    kept, _ = make(conn, query="confirmed")
    watches.confirm(conn, kept.token)
    fresh, _ = make(conn, query="just now")
    age(conn, stale.id, days=4)
    age(conn, kept.id, days=4)
    assert watches.purge_pending(conn) == 1
    assert {w.query for w in watches.for_token(conn, kept.token)} == {"confirmed", "just now"}


def test_an_old_database_gets_the_new_columns_when_opened(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript("""CREATE TABLE watches (id INTEGER PRIMARY KEY, query TEXT NOT NULL, target_price REAL NOT NULL,
        email TEXT NOT NULL, token TEXT NOT NULL UNIQUE, confirmed INTEGER NOT NULL DEFAULT 0,
        last_alerted_price REAL, created_at TEXT NOT NULL);
        INSERT INTO watches (query, target_price, email, token, created_at) VALUES ('x', 1, 'a@b.co', 't', '2026-01-01');""")
    old.commit(); old.close()
    conn = connect(path)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(watches)")}
    assert {"product_key", "label", "confirmed_at", "last_mailed_at"} <= columns
    assert conn.execute("SELECT query FROM watches").fetchone()[0] == "x"        # the old row is untouched
