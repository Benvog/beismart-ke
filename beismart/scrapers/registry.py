"""Stores register themselves here, so adding a store never touches other code."""

from .base import Scraper

_scrapers: dict[str, type[Scraper]] = {}


def register(cls: type[Scraper]) -> type[Scraper]:
    if not cls.name:
        raise ValueError(f"{cls.__name__} must set a name")
    if cls.name in _scrapers:
        raise ValueError(f"A scraper called {cls.name!r} is already registered")
    _scrapers[cls.name] = cls
    return cls


def all_scrapers() -> dict[str, type[Scraper]]:
    return dict(_scrapers)


def get_scraper(name: str) -> type[Scraper]:
    return _scrapers[name]
