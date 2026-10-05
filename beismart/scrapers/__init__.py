from .base import Scraper
from .registry import all_scrapers, get_scraper, register
from . import amazon, avechi, carrefour, hotpoint, jumia, kilimall, phoneplace  # noqa: F401  (importing a store module registers it)

__all__ = ["Scraper", "all_scrapers", "get_scraper", "register"]
