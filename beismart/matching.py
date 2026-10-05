"""Deciding which saved listings are really the product that was searched for.

Nothing is thrown away: a listing judged to be junk gets a plain-language reason and is hidden by
default, so the page can offer "show hidden" and a wrong call can be seen and fixed."""

import re
import statistics
from typing import Optional

# Words that mark something as a part, consumable or add-on rather than the product itself.
# Only words seen in real listings are here; each one we add risks hiding a real product, so be sparing.
# (Tried and removed: "bag" and "accessories", which hid real laptops and TVs sold with a free bag or accessories.)
# (The scrapers already drop the most common accessories: cases, chargers, cables, mounts, remotes.)
JUNK_TERMS = (
    "liner", "container", "machine cleaner", "dishwasher cleaner", "drain cleaner", "descaler", "refill",
    "cartridge", "replacement", "spare part", "conversion kit", "transform", "sticker", "decal", "gasket",
    "seal ring", "disposable", "rack", "accessory set", "accessories set", "powder", "detergent",
)
_JUNK_RE = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in JUNK_TERMS) + r")s?\b", re.I)

# Phrases that contain a junk word but describe a real product or a real selling point.
_EXEMPT_RE = re.compile(
    r"\b(?:(?:vacuum|steam|robot|robotic|air|carpet|pressure|window|floor|handheld|cordless) cleaner"
    r"|(?:free|year|years|yr|month|months)\s+replacement|replacement\s+(?:warranty|guarantee)|warranty\s+replacement)s?\b",
    re.I,
)

# A result priced under this fraction of the middle price is almost certainly not the product.
# Deliberately low: prices in one search legitimately span a wide range (headphones run from
# KSh 350 to 40,000), and hiding a genuinely cheap product is worse than showing a little junk.
OUTLIER_RATIO = 0.05
MIN_RESULTS_FOR_OUTLIER = 5


def junk_reason(title: str, price: float, query: str, median_price: Optional[float]) -> Optional[str]:
    """Why this listing looks like junk, or None if it looks fine."""
    if not _JUNK_RE.search(query):
        found = _JUNK_RE.search(_EXEMPT_RE.sub(" ", title))
        if found:
            return f"looks like an accessory or consumable (\"{found.group(0).lower()}\")"
    if median_price and price < median_price * OUTLIER_RATIO:
        return f"price is far below the others (under {int(OUTLIER_RATIO * 100)}% of the typical KSh {median_price:,.0f})"
    return None


def typical_price(prices: list[float]) -> Optional[float]:
    """The middle price of a search, or None when there are too few results to judge by."""
    return statistics.median(prices) if len(prices) >= MIN_RESULTS_FOR_OUTLIER else None
