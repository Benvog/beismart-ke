"""The emails BeiSmart sends: a plain-text version for every message, and an HTML version built for email
clients (table layout, inline styles, a 600px card). Product names, stores and links come from store
listings, so everything is escaped, and links and images are only used if they are real http(s) addresses."""

from html import escape
from typing import Optional

from .watches import Watch

BRAND = "#f97316"
INK = "#1f2937"
MUTED = "#6b7280"
LINE = "#e5e7eb"
PAGE = "#f3f4f6"
FONT = "-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"


def _link(base_url: str, action: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/api/watches/{action}?token={token}"


def _safe_url(url: Optional[str]) -> Optional[str]:
    """Scraped addresses are only used when they are plain web links (never javascript: or data:)."""
    return url if url and url.lower().startswith(("http://", "https://")) else None


def _button(label: str, url: str) -> str:
    """A button that holds up in email clients: a coloured table cell around a link."""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td bgcolor="{BRAND}" style="border-radius:8px"><a href="{escape(url)}" '
            f'style="display:inline-block;padding:12px 22px;font:600 15px {FONT};color:#ffffff;text-decoration:none">'
            f'{escape(label)}</a></td></tr></table>')


def _layout(preheader: str, label: str, inner: str, footer: str) -> str:
    """The shared frame: orange header, white card, muted footer. `preheader` is the grey preview text
    some inboxes show next to the subject."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(label)}</title></head>
<body style="margin:0;padding:0;background:{PAGE}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAGE}"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid {LINE};border-radius:14px;overflow:hidden">
<tr><td bgcolor="{BRAND}" style="padding:16px 28px;font:700 18px {FONT};color:#ffffff">BeiSmart KE
<span style="font-weight:400;font-size:13px;opacity:.9">&nbsp;&middot;&nbsp;Kenyan price comparison</span></td></tr>
<tr><td style="padding:28px 28px 8px;font-family:{FONT};color:{INK}">
<div style="font:700 12px {FONT};letter-spacing:.08em;text-transform:uppercase;color:{BRAND}">{escape(label)}</div>
{inner}
</td></tr>
<tr><td style="padding:8px 28px 26px;font:13px/1.5 {FONT};color:{MUTED};border-top:1px solid {LINE}">
<div style="padding-top:16px">{footer}</div></td></tr>
</table></td></tr></table></body></html>"""


def confirmation_email(watch: Watch, base_url: str) -> tuple[str, str, str]:
    """(subject, plain text, html) asking the person to confirm a new price alert."""
    confirm = _link(base_url, "confirm", watch.token)
    remove = _link(base_url, "unsubscribe", watch.token)
    price = f"KSh {watch.target_price:,.0f}"
    subject = f"Confirm your BeiSmart price alert for {watch.name[:60]}"
    text = (
        f"You asked to be emailed when {watch.name} falls to {price} or less.\n\n"
        f"Confirm the alert: {confirm}\n\n"
        f"Until you confirm, nothing will be sent. If you did not ask for this, ignore this email and the "
        f"request is deleted in a few days. Or remove it now: {remove}\n\n"
        f"BeiSmart KE"
    )
    inner = (
        f'<h1 style="margin:8px 0 12px;font:700 22px/1.3 {FONT};color:{INK}">Switch on your price alert</h1>'
        f'<p style="margin:0 0 18px;font:16px/1.55 {FONT};color:{INK}">You asked to be emailed when '
        f'<strong>{escape(watch.name)}</strong> falls to <strong>{escape(price)}</strong> or less.</p>'
        f'<div style="margin:0 0 22px">{_button("Confirm the alert", confirm)}</div>'
        f'<p style="margin:0 0 20px;font:14px/1.55 {FONT};color:{MUTED}">Until you confirm, nothing will be sent.</p>'
    )
    footer = (f'If you did not ask for this, ignore this email and the request is deleted in a few days, or '
              f'<a href="{escape(remove)}" style="color:{MUTED}">remove it now</a>.')
    html = _layout(f"Confirm to get an email when {watch.name} reaches {price}.", "Confirm your alert", inner, footer)
    return subject, text, html


def _offer_row(offer) -> str:
    link = _safe_url(offer.url)
    old = (f' <span style="color:#9ca3af;text-decoration:line-through;font-weight:400">KSh {offer.old_price:,.0f}</span>'
           if offer.old_price else "")
    view = (f'<a href="{escape(link)}" style="color:{BRAND};font-weight:600;text-decoration:none">View &rarr;</a>'
            if link else "")
    return (f'<tr><td style="padding:11px 0;border-top:1px solid {LINE};font:15px {FONT};color:{INK}">{escape(offer.store)}</td>'
            f'<td style="padding:11px 8px;border-top:1px solid {LINE};font:700 15px {FONT};color:{INK}" align="right">'
            f'KSh {offer.price:,.0f}{old}</td>'
            f'<td style="padding:11px 0;border-top:1px solid {LINE};font:14px {FONT}" align="right" width="64">{view}</td></tr>')


def alert_email(watch: Watch, hit, base_url: str) -> tuple[str, str, str]:
    """(subject, plain text, html) telling someone the price they were waiting for has arrived.

    `hit` has .price and .offers (the cheapest buyable listings, cheapest first)."""
    remove = _link(base_url, "unsubscribe", watch.token)
    manage = _link(base_url, "manage", watch.token)
    target = f"KSh {watch.target_price:,.0f}"
    now_price = f"KSh {hit.price:,.0f}"
    again = watch.last_alerted_price is not None
    subject = f"Price {'dropped again' if again else 'alert'}: {watch.name[:60]} is now {now_price}"
    headline = (f"{watch.name} has fallen further, to {now_price}." if again
                else f"{watch.name} is now {now_price}, at or below your target of {target}.")
    lines = [f"  {o.store}: KSh {o.price:,.0f}" + (f" (was KSh {o.old_price:,.0f})" if o.old_price else "") + f"\n    {o.url}"
             for o in hit.offers]
    text = (f"{headline}\n\nCheapest right now:\n" + "\n".join(lines) +
            f"\n\nPrices were checked today and can change quickly; check the store before you buy.\n\n"
            f"Your alerts: {manage}\nStop this alert: {remove}\n\nBeiSmart KE")

    best = hit.offers[0]
    best_link = _safe_url(best.url)
    image = _safe_url(getattr(best, "image_url", None))
    picture = (f'<td width="96" valign="top" style="padding-right:16px"><img src="{escape(image)}" width="96" height="96" '
               f'alt="{escape(best.title[:80])}" style="display:block;width:96px;height:96px;object-fit:contain;border-radius:8px;'
               f'border:1px solid {LINE}"></td>' if image else "")
    stores = {o.store for o in hit.offers}
    context = f"{len(stores)} stores have it" if len(stores) > 1 else f"at {best.store}"
    sub = (f"down from KSh {watch.last_alerted_price:,.0f} at your last alert" if again
           else f"at or below your target of {escape(target)}")
    inner = (
        f'<h1 style="margin:8px 0 4px;font:700 20px/1.3 {FONT};color:{INK}">{escape(watch.name)}</h1>'
        f'<div style="font:800 38px/1.15 {FONT};color:{INK};margin:6px 0 2px">{escape(now_price)}</div>'
        f'<div style="font:15px {FONT};color:{MUTED};margin:0 0 22px">{sub} &middot; {escape(context)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#fff7ed;border:1px solid #fed7aa;border-radius:12px"><tr><td style="padding:16px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{picture}'
        f'<td valign="middle" style="font:{FONT}"><div style="font:600 13px {FONT};color:{MUTED}">Cheapest right now</div>'
        f'<div style="font:700 17px {FONT};color:{INK};margin:2px 0 10px">{escape(best.store)} &middot; KSh {best.price:,.0f}</div>'
        + (_button(f"View at {best.store}", best_link) if best_link else "")
        + '</td></tr></table></td></tr></table>'
        + (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:22px 0 4px">'
           f'<tr><td colspan="3" style="padding-bottom:8px;font:700 13px {FONT};color:{MUTED};text-transform:uppercase;letter-spacing:.06em">'
           f'All the cheapest offers</td></tr>{"".join(_offer_row(o) for o in hit.offers)}</table>' if len(hit.offers) > 1 else "")
        + f'<p style="margin:18px 0 20px;font:13px/1.5 {FONT};color:{MUTED}">Prices were checked today and can change quickly; '
          f'check the store before you buy.</p>'
    )
    footer = (f'<a href="{escape(manage)}" style="color:{MUTED}">Your alerts</a> &nbsp;&middot;&nbsp; '
              f'<a href="{escape(remove)}" style="color:{MUTED}">Stop this alert</a>')
    html = _layout(f"{now_price} at {best.store}" + (f" and {len(stores) - 1} more store" + ("s" if len(stores) > 2 else "") if len(stores) > 1 else ""),
                   "Price dropped again" if again else "Price alert", inner, footer)
    return subject, text, html
