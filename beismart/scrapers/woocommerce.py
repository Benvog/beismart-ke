"""Shared scraper for stores built on WooCommerce with the Merto theme (Avechi, Phone Place Kenya).

A store is a subclass that sets `name` and `base_url`. These sites can be fetched with plain HTTP."""

import time
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..models import Listing, StoreResult, StoreStatus
from ..parsing import is_relevant, parse_price
from .base import Scraper
from .http import FetchProblem, get_page

MAX_RESULTS = 20


class WooCommerceScraper(Scraper):

    async def search(self, query: str) -> StoreResult:
        started = time.monotonic()
        url = f"{self.base_url}/?s={quote_plus(query)}&post_type=product"
        try:
            page = await get_page(url)
        except FetchProblem as problem:
            return self._result(started, problem.status, message=problem.message)
        return self._result(started, *self.parse(page.html, query))

    def parse(self, html: str, query: str) -> tuple[StoreStatus, list[Listing], str]:
        """Turn a search results page into (status, listings, message). Pure, so tests can use saved pages."""
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".products .product")
        if not cards:
            if soup.select_one(".search-no-results-wrapper, .woocommerce-info, .woocommerce-no-products-found"):
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
        link = card.select_one(".product-name a")
        if not link or not link.get("href"):
            return None
        title = link.get_text(strip=True)
        price_box = card.select_one(".price")
        if not title or not price_box:
            return None                      # e.g. sold-out items that show no price
        # A discounted item has <del>old</del><ins>new</ins>; a variable item shows a range (lowest first).
        current = price_box.select_one("ins .amount") or price_box.select_one(".amount")
        price = parse_price(current.get_text(" ", strip=True) if current else "")
        if price is None:
            return None
        old = price_box.select_one("del .amount")
        old_price = parse_price(old.get_text(" ", strip=True)) if old else None
        img = card.select_one("img")
        image = None
        if img:
            # src is an inline placeholder until the image lazy-loads; data-src has the real address.
            for candidate in (img.get("data-src"), img.get("src")):
                if candidate and not candidate.startswith("data:"):
                    image = candidate
                    break
        return Listing(
            store=self.name,
            title=title,
            price=price,
            url=link["href"],
            image_url=image,
            old_price=old_price if old_price and old_price > price else None,
            in_stock="outofstock" not in card.get("class", []),
        )

    def _result(self, started, status, listings=None, message="") -> StoreResult:
        return StoreResult(
            store=self.name,
            status=status,
            listings=listings or [],
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
