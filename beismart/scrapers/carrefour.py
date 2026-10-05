"""Carrefour Kenya. A JavaScript app, so it needs a real browser.

Its class names are utility classes (Tailwind) that change freely, so products are found through
their links instead: a card is the smallest element that holds exactly one product link."""

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

_PRODUCT_LINK = "a[href*='/p/']"
_PRODUCT_ID = re.compile(r"/p/(\d+)")
_AMOUNT = re.compile(r"\d[\d,]*\.\d{2}")
_KES_AMOUNT = re.compile(r"KES\s*(\d[\d,]*\.\d{2})")
# The page's data holds each product's picture as .../product/{id}/{version}/{id}_{n}.jpg; _1 is the main one.
_IMAGE = re.compile(r"https://cdn\.mafrservices\.com/pim-content/KEN/media/product/(\d+)/(\d+)/\1_(\d+)\.(?:jpg|png|webp)")
_OUT_OF_STOCK = re.compile(r"out of stock|sold out", re.I)


@register
class Carrefour(Scraper):
    name = "Carrefour"
    base_url = "https://www.carrefour.ke"

    async def search(self, query: str) -> StoreResult:
        started = time.monotonic()
        url = f"{self.base_url}/mafken/en/search?keyword={quote_plus(query)}"
        try:
            # Wait for product links or the "no results" message, so an empty search is quick.
            page = await get_rendered_page(url, wait_for=f"{_PRODUCT_LINK}, :text('No results found')")
        except FetchProblem as problem:
            return self._result(started, problem.status, message=problem.message)
        status, listings, message = self.parse(page.html, query)
        return self._result(started, status, listings, message)

    def parse(self, html: str, query: str) -> tuple[StoreStatus, list[Listing], str]:
        """Turn a results page into (status, listings, message). Pure, so tests can use saved pages."""
        soup = BeautifulSoup(html, "lxml")
        anchors = soup.select(_PRODUCT_LINK)
        if not anchors:
            if "no results found" in soup.get_text(" ", strip=True).lower():
                return StoreStatus.EMPTY, [], "The store has no products for this search"
            return StoreStatus.LAYOUT_CHANGED, [], "No product links found: the page layout may have changed"

        images = self._images(html)
        listings, seen = [], set()
        for anchor in anchors:
            listing = self._listing(anchor, images)
            if listing is None or listing.url in seen or not is_relevant(listing.title, query):
                continue
            seen.add(listing.url)
            listings.append(listing)
            if len(listings) >= MAX_RESULTS:
                break
        if not listings:
            return StoreStatus.EMPTY, [], f"{len(anchors)} products on the page, none matched the search"
        return StoreStatus.OK, listings, ""

    @staticmethod
    def _images(html: str) -> dict[str, str]:
        """product id -> main picture, for every product the page's data mentions."""
        best: dict[str, tuple[int, str]] = {}
        for match in _IMAGE.finditer(html):
            pid, n = match.group(1), int(match.group(3))
            if pid not in best or n < best[pid][0]:
                best[pid] = (n, match.group(0) + "?im=Resize=(300,300)")
        return {pid: url for pid, (_, url) in best.items()}

    def _listing(self, anchor, images: dict[str, str]) -> Listing | None:
        href = anchor.get("href", "")
        id_match = _PRODUCT_ID.search(href)
        title = anchor.get_text(" ", strip=True)
        if not id_match or not title:
            return None
        card = self._card(anchor)
        # Prices are read from the text after the title, starting at "KES": titles hold numbers such as
        # "Blender 1.25L" or "BLP15.150" that look like prices.
        text = card.get_text(" ", strip=True)
        text = text.split(title, 1)[1] if title in text else text
        first = _KES_AMOUNT.search(text)
        if not first:
            return None
        price = parse_price(first.group(1))
        if not price:
            return None
        # A discounted product shows the new price first, then the struck-through old one.
        later = [parse_price(a) for a in _AMOUNT.findall(text[first.end():])]
        old_price = next((a for a in later[:1] if a and a > price), None)
        return Listing(
            store=self.name,
            title=title,
            price=price,
            url=urljoin(self.base_url, href).split("?")[0],
            image_url=images.get(id_match.group(1)),
            old_price=old_price,
            in_stock=not _OUT_OF_STOCK.search(text),
        )

    @staticmethod
    def _card(anchor):
        """Climb until the parent would hold more than one product."""
        card = anchor
        while card.parent is not None:
            products = {a.get("href", "").split("?")[0] for a in card.parent.select(_PRODUCT_LINK)}
            if len(products) > 1:
                break
            card = card.parent
        return card

    def _result(self, started, status, listings=None, message="") -> StoreResult:
        return StoreResult(
            store=self.name,
            status=status,
            listings=listings or [],
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
