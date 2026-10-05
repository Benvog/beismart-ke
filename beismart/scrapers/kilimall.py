"""Kilimall Kenya. A JavaScript app, so it needs a real browser."""

import re
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

# Kilimall embeds its product data in the page: a listing id followed by its image address.
_PAYLOAD_IMAGE = re.compile(r'(\d{6,}),"(https://img\.kilimall\.com/gallery/[^"]+)"')
_LISTING_ID = re.compile(r"/listing/(\d+)-")


@register
class Kilimall(Scraper):
    name = "Kilimall"
    base_url = "https://www.kilimall.co.ke"

    async def search(self, query: str) -> StoreResult:
        started = time.monotonic()
        url = f"{self.base_url}/search?q={quote_plus(query)}"
        try:
            # Wait for the product cards or the "no data" message, so an empty search is quick.
            page = await get_rendered_page(url, wait_for="div.product-item, .pc__empty.no-data")
        except FetchProblem as problem:
            return self._result(started, problem.status, message=problem.message)
        status, listings, message = self.parse(page.html, query)
        return self._result(started, status, listings, message)

    def parse(self, html: str, query: str) -> tuple[StoreStatus, list[Listing], str]:
        """Turn a results page into (status, listings, message). Pure, so tests can use saved pages."""
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.product-item")
        if not cards:
            if soup.select_one(".pc__empty.no-data"):
                return StoreStatus.EMPTY, [], "The store has no products for this search"
            return StoreStatus.LAYOUT_CHANGED, [], "No product cards found: the page layout may have changed"

        payload_images = dict(_PAYLOAD_IMAGE.findall(html))
        listings = []
        for card in cards:
            listing = self._listing(card, payload_images)
            if listing and is_relevant(listing.title, query):
                listings.append(listing)
            if len(listings) >= MAX_RESULTS:
                break
        if not listings:
            return StoreStatus.EMPTY, [], f"{len(cards)} products on the page, none matched the search"
        return StoreStatus.OK, listings, ""

    def _listing(self, card, payload_images: dict[str, str]) -> Listing | None:
        link = card.select_one("a[href]")
        title = card.select_one(".product-title")
        price_el = card.select_one(".product-price")
        if not link or not title or not price_el:
            return None
        price = parse_price(price_el.get_text(" ", strip=True))
        if price is None:
            return None
        image = self._image(card, link["href"], payload_images)
        return Listing(
            store=self.name,
            title=title.get_text(" ", strip=True),
            price=price,
            url=urljoin(self.base_url, link["href"]).split("#")[0],
            image_url=image,
        )

    @staticmethod
    def _image(card, href: str, payload_images: dict[str, str]) -> str | None:
        # The page's own data is the reliable source: <img> tags only get their address once
        # scrolled into view, and src is a 1px placeholder until then.
        match = _LISTING_ID.search(href)
        if match and match.group(1) in payload_images:
            return payload_images[match.group(1)]
        img = card.select_one("img")
        for candidate in ((img.get("data-src"), img.get("src")) if img else ()):
            if candidate and not candidate.startswith("data:"):
                return candidate
        return None

    def _result(self, started, status, listings=None, message="") -> StoreResult:
        return StoreResult(
            store=self.name,
            status=status,
            listings=listings or [],
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
