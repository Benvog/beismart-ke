"""The one interface every store follows."""

from abc import ABC, abstractmethod

from ..models import StoreResult


class Scraper(ABC):
    """Subclass this, set `name` and `base_url`, implement `search`, and decorate with @register."""

    name: str = ""
    base_url: str = ""

    @abstractmethod
    async def search(self, query: str) -> StoreResult:
        """Return a StoreResult. Never raise: report failures through the status instead."""
