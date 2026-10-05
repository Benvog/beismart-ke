"""Deciding who to tell, and telling them.

Run after every refresh. For each confirmed watch the cheapest price you could actually buy is compared with
the target:

* it reaches the target for the first time           -> send an alert
* it is already below target and falls a further 5%   -> send another
* it stays about the same, or wobbles a little        -> stay quiet (no daily repeats)
* it rises back above the target                      -> re-arm, so the next fall alerts again

Only prices that can really be had count: sold-out listings, listings hidden as junk and international
listings (Amazon: shipping and import fees to Kenya are not included) never trigger an alert."""

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from . import store, watches
from .emails import alert_email
from .mailer import MailError, Mailer
from .products import group_listings
from .watches import Watch

log = logging.getLogger("beismart.alerts")

# While already below target, the price has to fall this much further to earn another alert.
FURTHER_DROP = 0.05
TOP_OFFERS = 5


@dataclass
class Hit:
    price: float                  # the cheapest buyable price now
    offers: list                  # the cheapest buyable listings, cheapest first


@dataclass
class AlertSummary:
    checked: int = 0
    sent: int = 0
    failed: int = 0
    rearmed: int = 0
    expired: int = 0
    sent_to: list[str] = field(default_factory=list)


def current_hit(conn: sqlite3.Connection, watch: Watch) -> Optional[Hit]:
    """The cheapest buyable price for what the watch follows, or None if nothing can be bought right now."""
    shown = store.search(conn, watch.query, limit=500).shown
    buyable = [l for l in shown if l.in_stock and not l.converted]
    if watch.product_key:
        matches = [g for g in group_listings(buyable) if g.key is not None and str(g.key) == watch.product_key]
        offers = [m for g in matches for m in g.members]
    else:
        offers = buyable
    if not offers:
        return None
    offers = sorted(offers, key=lambda l: l.price)
    return Hit(price=offers[0].price, offers=offers[:TOP_OFFERS])


def should_alert(watch: Watch, price: float) -> bool:
    if price > watch.target_price:
        return False
    if watch.last_alerted_price is None:
        return True
    return price <= watch.last_alerted_price * (1 - FURTHER_DROP)


def run_alerts(conn: sqlite3.Connection, mailer: Mailer, base_url: str) -> AlertSummary:
    summary = AlertSummary(expired=watches.purge_pending(conn))
    rows = conn.execute("SELECT id FROM watches WHERE confirmed = 1 ORDER BY id").fetchall()
    for row in rows:
        watch = watches.get(conn, row["id"])
        if watch is None:
            continue
        summary.checked += 1
        hit = current_hit(conn, watch)
        if hit is None:
            continue                                       # nothing buyable: say nothing, change nothing
        if hit.price > watch.target_price:
            if watch.last_alerted_price is not None:       # back above target: arm it again
                conn.execute("UPDATE watches SET last_alerted_price = NULL WHERE id = ?", (watch.id,))
                conn.commit()
                summary.rearmed += 1
            continue
        if not should_alert(watch, hit.price):
            continue
        subject, text, html = alert_email(watch, hit, base_url)
        try:
            mailer.send(watch.email, subject, text, html)
        except MailError as error:
            log.warning("Alert for watch %s not sent: %s", watch.id, error)
            summary.failed += 1                            # last_alerted_price unchanged, so it retries next run
            continue
        conn.execute("UPDATE watches SET last_alerted_price = ? WHERE id = ?", (hit.price, watch.id))
        conn.commit()
        summary.sent += 1
        summary.sent_to.append(watch.email)
        log.info("Alert sent for watch %s (%s): KSh %s", watch.id, watch.name, f"{hit.price:,.0f}")
    return summary
