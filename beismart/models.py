"""Plain data types shared by scrapers, the database and the API."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class StoreStatus(str, Enum):
    """What happened when a store was scraped. Anything but OK is shown to the user."""
    OK = "ok"
    EMPTY = "empty"                    # page loaded, the store has no matching products
    BLOCKED = "blocked"                # 403 or a bot-check page
    LAYOUT_CHANGED = "layout_changed"  # page loaded but the selectors found nothing
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class Listing:
    """One product on one store at one moment."""
    store: str
    title: str
    price: float                       # in KSh
    url: str
    image_url: Optional[str] = None
    currency: str = "KSh"
    old_price: Optional[float] = None  # struck-through price when the store shows a discount
    in_stock: bool = True
    converted: bool = False            # True when the price was converted from another currency
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StoreResult:
    """The outcome of scraping one store for one query."""
    store: str
    status: StoreStatus
    listings: list[Listing] = field(default_factory=list)
    message: str = ""
    duration_ms: int = 0
