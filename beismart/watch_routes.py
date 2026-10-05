"""The price-alert routes: create a watch, confirm it, list a person's watches, remove one.

The confirm, manage and unsubscribe pages are opened from emails, so they answer with small HTML pages
rather than JSON. Everything shown on them is escaped: product names come from store listings."""

import time
from html import escape
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import watches
from .emails import confirmation_email
from .mailer import MailError

REQUESTS_PER_HOUR_PER_IP = 5


class WatchIn(BaseModel):
    query: str = Field(min_length=2, max_length=100, description="what to watch, e.g. 'samsung tv'")
    target_price: float = Field(gt=0, le=watches.MAX_TARGET_PRICE, description="alert me when the price is this much (KSh) or less")
    email: str = Field(max_length=254)
    product_key: Optional[str] = Field(None, max_length=200, description="watch one product (a group's key) instead of the whole search")
    label: Optional[str] = Field(None, max_length=150, description="a friendly name for the emails")


class WatchOut(BaseModel):
    status: str      # confirmation_sent, waiting_for_confirmation or updated
    message: str


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · BeiSmart KE</title>
<style>body{{font-family:system-ui,sans-serif;max-width:560px;margin:12vh auto;padding:0 20px;color:#1f2937}}
h1{{font-size:1.4rem}}a.btn,button{{display:inline-block;background:#f97316;color:#fff;border:0;padding:10px 18px;border-radius:8px;
font:600 1rem system-ui;text-decoration:none;cursor:pointer}}ul{{padding:0;list-style:none}}li{{border:1px solid #e5e7eb;border-radius:10px;
padding:12px 14px;margin:10px 0;display:flex;justify-content:space-between;gap:12px;align-items:center}}small{{color:#6b7280}}
form{{margin:0}}button.quiet{{background:#fff;color:#b91c1c;border:1px solid #fca5a5;padding:6px 12px}}</style></head>
<body><p><strong style="color:#f97316">BeiSmart KE</strong></p><h1>{escape(title)}</h1>{body}</body></html>"""
    return HTMLResponse(html, status_code=status_code)


def _invalid_link() -> HTMLResponse:
    return _page("This link is not valid", "<p>It may have been used already, or the alert was removed.</p>", 404)


def watch_router(base_url: str) -> APIRouter:
    router = APIRouter()
    hits: dict[str, list[float]] = {}          # client address -> recent request times

    def too_many_requests(ip: str) -> bool:
        recent = [t for t in hits.get(ip, []) if time.monotonic() - t < 3600]
        hits[ip] = recent + [time.monotonic()]
        return len(recent) >= REQUESTS_PER_HOUR_PER_IP

    @router.post("/api/watches", response_model=WatchOut, status_code=202, summary="Ask to be emailed when a price falls")
    async def create_watch(body: WatchIn, request: Request):
        ip = request.client.host if request.client else "unknown"
        if too_many_requests(ip):
            raise HTTPException(429, detail="Too many requests. Please try again in an hour.")
        conn = request.app.state.conn
        try:
            watch, send = watches.create_watch(conn, query=body.query, target_price=body.target_price, email=body.email,
                                               product_key=body.product_key, label=body.label)
        except watches.WatchError as error:
            raise HTTPException(422 if error.kind == "invalid" else 429, detail=error.message)
        if send:
            subject, text, html = confirmation_email(watch, base_url)
            try:
                request.app.state.mailer.send(watch.email, subject, text, html)
            except MailError:
                raise HTTPException(502, detail="We could not send the confirmation email. Please try again later.")
            watches.mark_mailed(conn, watch.id)
            return WatchOut(status="confirmation_sent", message="Check your inbox and click the link to switch the alert on.")
        if watch.confirmed:
            return WatchOut(status="updated", message=f"Your alert for {watch.name} is now KSh {watch.target_price:,.0f}.")
        return WatchOut(status="waiting_for_confirmation", message="We already sent a confirmation email. Please check your inbox.")

    @router.get("/api/watches/confirm", response_class=HTMLResponse, include_in_schema=False)
    async def confirm(request: Request, token: str = Query(..., max_length=100)):
        watch = watches.confirm(request.app.state.conn, token)
        if watch is None:
            return _invalid_link()
        manage = f"{base_url.rstrip('/')}/api/watches/manage?token={escape(token)}"
        return _page("Your price alert is on", (
            f"<p>We will email <strong>{escape(watch.email)}</strong> when <strong>{escape(watch.name)}</strong> "
            f"falls to <strong>KSh {watch.target_price:,.0f}</strong> or less.</p>"
            f'<p><a class="btn" href="{manage}">See my alerts</a></p>'))

    @router.get("/api/watches/manage", response_class=HTMLResponse, include_in_schema=False)
    async def manage(request: Request, token: str = Query(..., max_length=100)):
        mine = watches.for_token(request.app.state.conn, token)
        if not mine:
            return _invalid_link()
        rows = "".join(
            f"<li><span><strong>{escape(w.name)}</strong><br><small>KSh {w.target_price:,.0f} or less · "
            f"{'on' if w.confirmed else 'waiting for you to confirm by email'}</small></span>"
            f'<form method="post" action="{escape(base_url.rstrip("/"))}/api/watches/unsubscribe?token={escape(w.token)}">'
            f'<button class="quiet">Remove</button></form></li>'
            for w in mine)
        return _page("Your price alerts", f"<ul>{rows}</ul>")

    @router.get("/api/watches/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
    async def unsubscribe_page(request: Request, token: str = Query(..., max_length=100)):
        """Opening the link only asks; the removal is a POST, so email scanners that open links cannot delete alerts."""
        mine = watches.for_token(request.app.state.conn, token)
        watch = next((w for w in mine if w.token == token), None)
        if watch is None:
            return _invalid_link()
        return _page("Remove this alert?", (
            f"<p>Stop emailing <strong>{escape(watch.email)}</strong> about <strong>{escape(watch.name)}</strong>?</p>"
            f'<form method="post" action="{escape(base_url.rstrip("/"))}/api/watches/unsubscribe?token={escape(token)}">'
            f"<button>Yes, remove it</button></form>"))

    @router.post("/api/watches/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
    async def unsubscribe(request: Request, token: str = Query(..., max_length=100)):
        watch = watches.unsubscribe(request.app.state.conn, token)
        if watch is None:
            return _invalid_link()
        return _page("Alert removed", f"<p>You will no longer be emailed about <strong>{escape(watch.name)}</strong>.</p>")

    return router
