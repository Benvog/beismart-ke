"""Helpers shared by all scrapers: reading prices and dropping irrelevant results."""

import re
from typing import Optional

_PRICE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Words that mark a product as an accessory rather than the thing itself.
ACCESSORY_TERMS = (
    "case", "cover", "screen protector", "tempered glass", "charger", "cable", "adapter",
    "holder", "stand", "skin", "pouch", "sleeve", "strap", "stylus", "protector", "film",
    "bumper", "shell", "wallet", "bracket", "wall mount", "remote", "remote control",
)
_ACCESSORY_RE = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in ACCESSORY_TERMS) + r")s?\b")


def parse_price(text: Optional[str]) -> Optional[float]:
    """'KSh 28,999.00' -> 28999.0. For a range like 'KSh 507 - KSh 508' returns the lower price.
    Returns None when there is no usable price."""
    if not text:
        return None
    numbers = [float(m.replace(",", "")) for m in _PRICE_RE.findall(text)]
    numbers = [n for n in numbers if n > 0]
    return min(numbers) if numbers else None


def _stem(word: str) -> str:
    """'headphones' -> 'headphone', so a plural search still finds singular titles."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def is_relevant(title: str, query: str, threshold: float = 0.6) -> bool:
    """True when a result looks like what was searched for.

    At least `threshold` of the query words must appear in the title, and accessories
    are dropped unless the query itself asks for one."""
    title_l, query_l = title.lower(), query.lower()
    if not _ACCESSORY_RE.search(query_l) and _ACCESSORY_RE.search(title_l):
        return False
    words = [w for w in re.findall(r"[a-z0-9]+", query_l) if len(w) >= 2]
    if not words:
        return True
    hits = sum(1 for w in words if _stem(w) in title_l)
    return hits / len(words) >= threshold


def query_wants_accessory(query: str) -> bool:
    return bool(_ACCESSORY_RE.search(query.lower()))
