import pytest

from beismart.models import StoreResult, StoreStatus
from beismart.scrapers import Scraper, all_scrapers, get_scraper, register
from beismart.scrapers import registry


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(registry._scrapers)
    registry._scrapers.clear()
    yield
    registry._scrapers.clear()
    registry._scrapers.update(saved)


def make(name):
    class Fake(Scraper):
        base_url = "https://example.test"

        async def search(self, query):
            return StoreResult(store=self.name, status=StoreStatus.EMPTY)

    Fake.name = name
    return Fake


def test_register_and_lookup():
    cls = register(make("Fake"))
    assert get_scraper("Fake") is cls
    assert "Fake" in all_scrapers()


def test_duplicate_names_are_rejected():
    register(make("Fake"))
    with pytest.raises(ValueError):
        register(make("Fake"))


def test_scraper_needs_a_name():
    with pytest.raises(ValueError):
        register(make(""))
