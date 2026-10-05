"""Jumia Kenya. Behind Cloudflare, so it is fetched with a real browser."""

import time
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from ..models import Listing, StoreResult, StoreStatus
from ..parsing import is_relevant, parse_price
from .base import Scraper
from .browser import get_rendered_page
from .http import FetchProblem
from .registry import register

MAX_RESULTS = 20


@register
class Jumia(Scraper):
    name = "Jumia"
    base_url = "https://www.jumia.co.ke"

    async def search(self, query: str) -> StoreResult:
        started = time.monotonic()
        url = f"{self.base_url}/catalog/?q={quote_plus(query)}"
        try:
            # Wait for either the product cards or Jumia's "no results" message, so an empty search is quick.
            page = await get_rendered_page(url, wait_for="article.prd, h2:has-text('no results')")
        except FetchProblem as problem:
            return self._result(started, problem.status, message=problem.message)
        status, listings, message = self.parse(page.html, query)
        return self._result(started, status, listings, message)

    def parse(self, html: str, query: str) -> tuple[StoreStatus, list[Listing], str]:
        """Turn a results page into (status, listings, message). Pure, so tests can use saved pages."""
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article.prd")
        if not cards:
            title = soup.title.get_text(strip=True).lower() if soup.title else ""
            if "just a moment" in title:
                return StoreStatus.BLOCKED, [], "The store showed a bot check instead of products"
            if title.startswith("no results") or "there are no results for" in soup.get_text().lower():
                return StoreStatus.EMPTY, [], "The store has no products for this search"
            return StoreStatus.LAYOUT_CHANGED, [], "No product cards found: the page layout may have changed"

        listings = []
        for card in cards:
            listing = self._listing(card)
            if listing and is_relevant(listing.title, query):
                listings.append(listing)
            if len(listings) >= MAX_RESULTS:
                break
        if not listings:
            return StoreStatus.EMPTY, [], f"{len(cards)} products on the page, none matched the search"
        return StoreStatus.OK, listings, ""

    def _listing(self, card) -> Listing | None:
        core = card.select_one("a.core")
        name = card.select_one("h3.name")
        price_el = card.select_one(".prc")
        if not core or not name or not price_el or not core.get("href"):
            return None
        price = parse_price(price_el.get_text(" ", strip=True))
        if price is None:
            return None
        old_el = card.select_one(".old")
        old_price = parse_price(old_el.get_text(" ", strip=True)) if old_el else None
        img = card.select_one("img")
        image = (img.get("data-src") or img.get("src")) if img else None
        if image and image.startswith("data:"):
            image = None
        return Listing(
            store=self.name,
            title=name.get_text(" ", strip=True),
            price=price,
            url=urljoin(self.base_url, core["href"]).split("#")[0],
            image_url=image,
            old_price=old_price if old_price and old_price > price else None,
        )

    def _result(self, started, status, listings=None, message="") -> StoreResult:
        return StoreResult(
            store=self.name,
            status=status,
            listings=listings or [],
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
