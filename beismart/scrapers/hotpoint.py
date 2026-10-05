"""Hotpoint Kenya. A Next.js app, so it needs a real browser.

Its class names carry a build hash (ProductCard-module__t53O_a__card) that changes on every
deploy, so everything here matches on the stable part of the name only."""

import re
import time
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Listing, StoreResult, StoreStatus
from ..parsing import is_relevant, parse_price
from .base import Scraper
from .browser import get_rendered_page
from .http import FetchProblem
from .registry import register

MAX_RESULTS = 20

_CARD = re.compile(r"^ProductCard-module__\w+__card$")
_NAME = re.compile(r"__name$")
_CURRENT_PRICE = re.compile(r"__currentPrice")
_ORIGINAL_PRICE = re.compile(r"__originalPrice$")
_RESULT_COUNT = re.compile(r"__resultCount$")
_OUT_OF_STOCK = re.compile(r"out of stock|sold out", re.I)


@register
class Hotpoint(Scraper):
    name = "Hotpoint"
    base_url = "https://www.hotpoint.co.ke"

    async def search(self, query: str) -> StoreResult:
        started = time.monotonic()
        url = f"{self.base_url}/products/?q={quote_plus(query)}"
        try:
            # Wait for real product cards only. The result counter reads "0 products" while the page is
            # still loading, so it cannot be trusted as a signal until the cards have had their chance.
            page = await get_rendered_page(url, wait_for='div[class^="ProductCard-module"][class$="__card"]')
        except FetchProblem as problem:
            return self._result(started, problem.status, message=problem.message)
        status, listings, message = self.parse(page.html, query)
        return self._result(started, status, listings, message)

    def parse(self, html: str, query: str) -> tuple[StoreStatus, list[Listing], str]:
        """Turn a results page into (status, listings, message). Pure, so tests can use saved pages."""
        soup = BeautifulSoup(html, "lxml")
        cards = soup.find_all("div", class_=_CARD)
        if not cards:
            count = soup.find("p", class_=_RESULT_COUNT)
            if count and count.get_text(" ", strip=True).startswith("0 "):
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
        name = card.find("a", class_=_NAME)
        current = card.find(class_=_CURRENT_PRICE)
        if not name or not name.get("href") or not current:
            return None
        price = parse_price(current.get_text(" ", strip=True))
        if price is None:
            return None
        original = card.find(class_=_ORIGINAL_PRICE)
        old_price = parse_price(original.get_text(" ", strip=True)) if original else None
        return Listing(
            store=self.name,
            title=name.get_text(" ", strip=True),
            price=price,
            url=urljoin(self.base_url, name["href"]).split("#")[0],
            image_url=self._image(card),
            old_price=old_price if old_price and old_price > price else None,
            in_stock=not _OUT_OF_STOCK.search(card.get_text(" ", strip=True)),
        )

    def _image(self, card) -> str | None:
        img = card.find("img")
        src = img.get("src") if img else None
        if not src or src.startswith("data:"):
            return None
        # Images go through Next.js's resizer; the real picture is in its `url` parameter.
        original = parse_qs(urlparse(src).query).get("url")
        if original:
            return unquote(original[0])
        return urljoin(self.base_url, src)

    def _result(self, started, status, listings=None, message="") -> StoreResult:
        return StoreResult(
            store=self.name,
            status=status,
            listings=listings or [],
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
