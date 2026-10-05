import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from beismart import alerts, store, watches
from beismart.db import connect
from beismart.mailer import MailError
from beismart.models import Listing, StoreResult, StoreStatus
from beismart.scheduler import run_job
from beismart.scrapers import Scraper

BASE = "http://app.test"
TV = 'Samsung 32H5000 32" Inch Smart TV'


class Mail:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, to, subject, text, html=None):
        if to in self.fail_for:
            raise MailError("down")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


@pytest.fixture
def conn():
    return connect(":memory:")


def put(conn, price, url="https://a.test/1", title=TV, shop="Jumia", query="samsung tv", **kw):
    item = Listing(store=shop, title=title, price=price, url=url, **kw)
    store.save_result(conn, StoreResult(store=shop, status=StoreStatus.OK, listings=[item]), query)


def watch(conn, target=20000.0, email="ben@example.com", confirmed=True, **kw):
    args = dict(query="samsung tv", target_price=target, email=email)
    args.update(kw)
    w, _ = watches.create_watch(conn, **args)
    if confirmed:
        watches.confirm(conn, w.token)
    return watches.get(conn, w.id)


def run(conn, mail):
    return alerts.run_alerts(conn, mail, BASE)


# ── when to alert ─────────────────────────────────────────────────────────────

def test_a_price_above_target_sends_nothing(conn):
    put(conn, 25000.0); watch(conn); mail = Mail()
    summary = run(conn, mail)
    assert mail.sent == [] and summary.checked == 1 and summary.sent == 0


def test_reaching_the_target_sends_one_alert_and_remembers_it(conn):
    put(conn, 19000.0); w = watch(conn); mail = Mail()
    assert run(conn, mail).sent == 1
    assert watches.get(conn, w.id).last_alerted_price == 19000.0
    assert run(conn, mail).sent == 0                     # tomorrow, same price: no repeat
    assert len(mail.sent) == 1 and mail.sent[0]["to"] == "ben@example.com"


def test_exactly_the_target_counts(conn):
    put(conn, 20000.0); watch(conn); mail = Mail()
    assert run(conn, mail).sent == 1


def test_a_small_further_drop_stays_quiet_but_a_real_one_alerts_again(conn):
    put(conn, 19000.0); watch(conn); mail = Mail()
    run(conn, mail)
    put(conn, 18600.0)                                   # 2% lower
    assert run(conn, mail).sent == 0
    put(conn, 17900.0)                                   # more than 5% below the 19,000 alerted at
    assert run(conn, mail).sent == 1
    assert len(mail.sent) == 2 and "dropped again" in mail.sent[1]["subject"]


def test_rising_above_the_target_rearms_the_alert(conn):
    put(conn, 19000.0); w = watch(conn); mail = Mail()
    run(conn, mail)
    put(conn, 24000.0)
    summary = run(conn, mail)
    assert summary.rearmed == 1 and watches.get(conn, w.id).last_alerted_price is None
    put(conn, 19500.0)
    assert run(conn, mail).sent == 1                     # a brand-new fall below target alerts again
    assert len(mail.sent) == 2


def test_an_unconfirmed_watch_is_never_alerted(conn):
    put(conn, 15000.0); watch(conn, confirmed=False); mail = Mail()
    summary = run(conn, mail)
    assert mail.sent == [] and summary.checked == 0


def test_a_query_nobody_sells_sends_nothing(conn):
    watch(conn); mail = Mail()
    assert run(conn, mail).sent == 0


# ── which prices count ────────────────────────────────────────────────────────

def test_a_sold_out_price_cannot_trigger_an_alert(conn):
    put(conn, 15000.0, in_stock=False); watch(conn); mail = Mail()
    assert run(conn, mail).sent == 0


def test_nothing_in_stock_does_not_rearm_a_watch(conn):
    put(conn, 19000.0); w = watch(conn); mail = Mail()
    run(conn, mail)
    put(conn, 19000.0, in_stock=False)                   # sold out everywhere for a day
    run(conn, mail)
    assert watches.get(conn, w.id).last_alerted_price == 19000.0


def test_an_international_price_cannot_trigger_an_alert(conn):
    put(conn, 15000.0, converted=True, shop="Amazon"); watch(conn); mail = Mail()
    assert run(conn, mail).sent == 0


def test_junk_hidden_from_search_cannot_trigger_an_alert(conn):
    put(conn, 500.0, title="Disposable Air Fryer Liner 40 pack", query="air fryer")
    watch(conn, query="air fryer", target=5000.0); mail = Mail()
    assert run(conn, mail).sent == 0


def test_the_cheapest_buyable_price_across_stores_is_used(conn):
    put(conn, 24000.0, url="https://a.test/1", shop="Jumia")
    put(conn, 19500.0, url="https://b.test/1", shop="Hotpoint", title='Samsung 32" LED TV UA32H5000FUXKE')
    watch(conn); mail = Mail()
    assert run(conn, mail).sent == 1
    assert "Hotpoint" in mail.sent[0]["text"] and "KSh 19,500" in mail.sent[0]["subject"]


# ── watching one product ──────────────────────────────────────────────────────

KEY = "samsung | H5000 | 32in | new"


def test_a_product_watch_ignores_cheaper_listings_of_other_products(conn):
    put(conn, 25000.0)                                                           # the 32in H5000, above target
    put(conn, 12000.0, url="https://a.test/other", title='Samsung 43F6000FU 43" Inch Smart TV')   # a different, cheaper TV
    watch(conn, product_key=KEY, label="Samsung 32 inch H5000"); mail = Mail()
    assert run(conn, mail).sent == 0


def test_a_product_watch_alerts_when_that_product_reaches_the_target(conn):
    put(conn, 19000.0)
    put(conn, 12000.0, url="https://a.test/other", title='Samsung 43F6000FU 43" Inch Smart TV')
    watch(conn, product_key=KEY, label="Samsung 32 inch H5000"); mail = Mail()
    assert run(conn, mail).sent == 1
    assert "Samsung 32 inch H5000" in mail.sent[0]["subject"] and "KSh 19,000" in mail.sent[0]["subject"]
    assert "43F6000" not in mail.sent[0]["text"]


# ── failures ──────────────────────────────────────────────────────────────────

def test_a_failed_email_is_retried_on_the_next_run(conn):
    put(conn, 19000.0); w = watch(conn)
    summary = run(conn, Mail(fail_for=["ben@example.com"]))
    assert summary.failed == 1 and summary.sent == 0 and watches.get(conn, w.id).last_alerted_price is None
    good = Mail()
    assert run(conn, good).sent == 1 and len(good.sent) == 1


def test_one_failing_address_does_not_stop_the_others(conn):
    put(conn, 19000.0)
    watch(conn, email="bad@example.com"); watch(conn, email="good@example.com")
    mail = Mail(fail_for=["bad@example.com"])
    summary = run(conn, mail)
    assert summary.failed == 1 and summary.sent == 1 and [m["to"] for m in mail.sent] == ["good@example.com"]


def test_stale_unconfirmed_watches_are_cleaned_up_on_every_run(conn):
    w = watch(conn, confirmed=False)
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(timespec="seconds")
    conn.execute("UPDATE watches SET created_at = ? WHERE id = ?", (old, w.id)); conn.commit()
    assert run(conn, Mail()).expired == 1
    assert watches.get(conn, w.id) is None


# ── the email ─────────────────────────────────────────────────────────────────

def test_the_alert_email_has_the_price_stores_links_and_a_way_out(conn):
    put(conn, 19000.0, old_price=24000.0, url="https://a.test/tv-1"); w = watch(conn); mail = Mail()
    run(conn, mail)
    m = mail.sent[0]
    assert "KSh 19,000" in m["subject"] and "target of KSh 20,000" in m["text"]
    assert "Jumia: KSh 19,000 (was KSh 24,000)" in m["text"] and "https://a.test/tv-1" in m["text"]
    assert f"{BASE}/api/watches/unsubscribe?token={w.token}" in m["text"]
    assert f"{BASE}/api/watches/manage?token={w.token}" in m["text"]
    assert "https://a.test/tv-1" in m["html"] and "Stop this alert" in m["html"]


def test_store_text_in_the_alert_email_cannot_inject_html(conn):
    put(conn, 19000.0, url='https://a.test/"><script>x</script>'); watch(conn, label="<b>Big</b> TV"); mail = Mail()
    run(conn, mail)
    assert "<script>" not in mail.sent[0]["html"] and "<b>Big</b>" not in mail.sent[0]["html"]


# ── as part of the daily job ──────────────────────────────────────────────────

class FakeStore(Scraper):
    name = "Fake"

    async def search(self, query):
        item = Listing(store=self.name, title=TV, price=18500.0, url="https://f.test/tv")
        return StoreResult(store=self.name, status=StoreStatus.OK, listings=[item])


def test_the_daily_job_sends_alerts_after_refreshing(conn):
    watch(conn); mail = Mail()
    summary = asyncio.run(run_job(conn, ["samsung tv"], [FakeStore()], pause_s=0, mailer=mail, base_url=BASE))
    assert summary.alerts.sent == 1 and len(mail.sent) == 1 and "KSh 18,500" in mail.sent[0]["subject"]


def test_without_a_mailer_the_job_only_refreshes(conn):
    watch(conn)
    summary = asyncio.run(run_job(conn, ["samsung tv"], [FakeStore()], pause_s=0))
    assert summary.alerts is None and summary.listings == 1


def test_a_broken_alert_check_does_not_undo_the_refresh(conn, monkeypatch):
    from beismart import scheduler
    monkeypatch.setattr(scheduler, "run_alerts", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    summary = asyncio.run(run_job(conn, ["samsung tv"], [FakeStore()], pause_s=0, mailer=Mail(), base_url=BASE))
    assert summary.listings == 1 and summary.alerts is None
    assert len(store.search_saved(conn, "samsung tv")) == 1


# ── the email's design and safety ─────────────────────────────────────────────

def alert_html(conn, **listing_kw):
    put(conn, 19000.0, **listing_kw); watch(conn); mail = Mail()
    run(conn, mail)
    return mail.sent[0]["html"]


def test_the_alert_html_is_a_complete_branded_email(conn):
    html = alert_html(conn)
    assert html.startswith("<!doctype html>") and 'lang="en"' in html
    assert "BeiSmart KE" in html and "#f97316" in html
    assert "KSh 19,000" in html and "Price alert" in html


def test_the_alert_has_a_hidden_preview_line_for_the_inbox_list(conn):
    html = alert_html(conn)
    assert "display:none" in html and "KSh 19,000 at Jumia" in html


def test_a_listings_picture_is_shown_when_it_is_a_real_web_address(conn):
    html = alert_html(conn, image_url="https://img.test/tv.jpg")
    assert '<img src="https://img.test/tv.jpg"' in html


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,<script>x</script>", "//evil.test/x.jpg", "file:///c:/x"])
def test_a_scraped_address_that_is_not_http_is_never_used_as_a_picture(conn, bad):
    assert "<img" not in alert_html(conn, image_url=bad)


def test_a_scraped_link_that_is_not_http_never_becomes_a_button(conn):
    html = alert_html(conn, url="javascript:alert(1)")
    assert "javascript:" not in html and "View at Jumia" not in html


def test_the_store_count_counts_stores_not_listings(conn):
    put(conn, 19000.0, url="https://a.test/1", shop="Jumia")
    put(conn, 19500.0, url="https://a.test/2", shop="Jumia")
    put(conn, 20000.0, url="https://b.test/1", shop="Hotpoint", title='Samsung 32" LED TV UA32H5000FUXKE')
    watch(conn); mail = Mail()
    run(conn, mail)
    assert "2 stores have it" in mail.sent[0]["html"]


def test_a_second_alert_says_where_the_price_was_before(conn):
    put(conn, 19000.0); watch(conn); mail = Mail()
    run(conn, mail)
    put(conn, 17000.0)
    run(conn, mail)
    assert "down from KSh 19,000 at your last alert" in mail.sent[1]["html"] and "Price dropped again" in mail.sent[1]["html"]


def test_the_confirmation_html_has_a_button_and_a_way_out(conn):
    from beismart.emails import confirmation_email
    w, _ = watches.create_watch(conn, query="samsung tv", target_price=20000, email="ben@example.com")
    _, _, html = confirmation_email(w, BASE)
    assert "Confirm the alert" in html and f"{BASE}/api/watches/confirm?token={w.token}" in html
    assert f"{BASE}/api/watches/unsubscribe?token={w.token}" in html and "KSh 20,000" in html
