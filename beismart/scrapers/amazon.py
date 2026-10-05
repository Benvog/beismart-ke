"""Amazon (amazon.com), searched from Kenya.

Amazon shows prices in KES to visitors in Kenya. A visitor elsewhere (for example a hosted server) gets
dollars, so "$" prices are converted with BEISMART_USD_KES. Either way the price is the item price only:
shipping and import fees to Kenya are not included, and many items cannot be shipped there at all, so
every Amazon listing is flagged `converted` for the UI to say so."""

import asyncio
import os
import re
import time
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..models import Listing, StoreResult, StoreStatus
from ..parsing import is_relevant, parse_price
from .base import Scraper
from .browser import get_rendered_page
from .debug import save_unreadable_page
from .http import FetchProblem, get_page
from .registry import register

MAX_RESULTS = 20
USD_TO_KES = float(os.environ.get("BEISMART_USD_KES", "129.0"))

_RESULTS = "div[data-component-type='s-search-result'], form[action*='validateCaptcha']"
_SPONSORED = re.compile(r"^\s*Sponsored\s*$")
_ERROR_TITLES = ("sorry! something went wrong", "service unavailable")
_ROBOT_TITLES = ("robot check", "type the characters", "captcha")


@register
class Amazon(Scraper):
    name = "Amazon"
    base_url = "https://www.amazon.com"

    async def search(self, query: str) -> StoreResult:
        started = time.monotonic()
        url = f"{self.base_url}/s?k={quote_plus(query)}"
        status, listings, message = StoreStatus.ERROR, [], ""
        for attempt in range(3):
            try:
                page = await get_page(url)
            except FetchProblem as problem:
                return self._result(started, problem.status, message=problem.message)
            status, listings, message = self.parse(page.html, query)
            if status is StoreStatus.BLOCKED:
                # Plain HTTP cannot pass the bot check; the shared Chrome runs it and lands on the results.
                try:
                    page = await get_rendered_page(url, wait_for=_RESULTS, timeout=40)
                    status, listings, message = self.parse(page.html, query)
                except FetchProblem as problem:
                    status, listings, message = problem.status, [], problem.message
            # Amazon sometimes answers with a one-off error page or an unfamiliar variant of the page: ask again.
            if status not in (StoreStatus.ERROR, StoreStatus.LAYOUT_CHANGED, StoreStatus.BLOCKED):
                break
            save_unreadable_page(self.name, query, page.html)
            await asyncio.sleep(4 * (attempt + 1))
        return self._result(started, status, listings, message)

    def parse(self, html: str, query: str) -> tuple[StoreStatus, list[Listing], str]:
        """Turn a results page into (status, listings, message). Pure, so tests can use saved pages."""
        if "bm-verify" in html or "/_sec/verify" in html:
            # Akamai's bot check: a tiny page whose script proves the visitor is a browser, then reloads.
            return StoreStatus.BLOCKED, [], "Amazon showed a bot check (Akamai) instead of products"
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(strip=True).lower() if soup.title else ""
        if any(t in title for t in _ROBOT_TITLES) or soup.select_one("form[action*='validateCaptcha']"):
            return StoreStatus.BLOCKED, [], "Amazon showed a robot check instead of products"
        if any(t in title for t in _ERROR_TITLES):
            return StoreStatus.ERROR, [], "Amazon returned an error page"

        cards = soup.select("div[data-component-type='s-search-result']")
        if not cards:
            if "no results for your search query" in soup.get_text(" ", strip=True).lower():
                return StoreStatus.EMPTY, [], "The store has no products for this search"
            return StoreStatus.LAYOUT_CHANGED, [], "No product cards found: the page layout may have changed"

        organic = [c for c in cards if not c.find(string=_SPONSORED)]
        if not organic:
            return StoreStatus.EMPTY, [], "The store has no products for this search (only ads)"

        listings = []
        for card in organic:
            listing = self._listing(card)
            if listing and is_relevant(listing.title, query):
                listings.append(listing)
            if len(listings) >= MAX_RESULTS:
                break
        if not listings:
            return StoreStatus.EMPTY, [], f"{len(organic)} products on the page, none matched the search"
        return StoreStatus.OK, listings, ""

    def _listing(self, card) -> Listing | None:
        asin = card.get("data-asin")
        img = card.select_one("img.s-image")
        title = (img.get("alt") if img else "") or ""
        price_el = card.select_one(".a-price:not(.a-text-price) .a-offscreen")
        if not asin or not title or not price_el:
            return None                      # no price shown, e.g. "see options"
        price_text = price_el.get_text(strip=True)
        price = parse_price(price_text)
        if price is None:
            return None
        old_el = card.select_one(".a-price.a-text-price .a-offscreen")
        old_price = parse_price(old_el.get_text(strip=True)) if old_el else None
        if "$" in price_text:                # dollars: convert (see the module note)
            price = round(price * USD_TO_KES, 2)
            old_price = round(old_price * USD_TO_KES, 2) if old_price else None
        return Listing(
            store=self.name,
            title=title.strip(),
            price=price,
            url=f"{self.base_url}/dp/{asin}",
            image_url=img.get("src") if img else None,
            old_price=old_price if old_price and old_price > price else None,
            converted=True,
        )

    def _result(self, started, status, listings=None, message="") -> StoreResult:
        return StoreResult(
            store=self.name,
            status=status,
            listings=listings or [],
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
