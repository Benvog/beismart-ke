"""Plain-HTTP fetching with failures mapped to a StoreStatus."""

import asyncio
from dataclasses import dataclass

import requests

from ..models import StoreStatus

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class FetchProblem(Exception):
    """A page could not be used; carries the status to report."""

    def __init__(self, status: StoreStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Page:
    url: str
    html: str


def _get(url: str, timeout: float) -> Page:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}, timeout=timeout)
    except requests.Timeout:
        raise FetchProblem(StoreStatus.TIMEOUT, f"No answer from {url} within {timeout:.0f}s")
    except requests.RequestException as exc:
        raise FetchProblem(StoreStatus.ERROR, f"Could not reach {url}: {exc.__class__.__name__}")
    if r.status_code in (401, 403, 429):
        raise FetchProblem(StoreStatus.BLOCKED, f"HTTP {r.status_code}: the store refused the request")
    if r.status_code != 200:
        raise FetchProblem(StoreStatus.ERROR, f"HTTP {r.status_code} from {url}")
    return Page(url=url, html=r.text)


async def get_page(url: str, timeout: float = 20.0, retries: int = 1) -> Page:
    """Fetch a page without blocking the event loop. Raises FetchProblem on any failure.

    A dropped connection or a timeout is retried once; a refusal (403/429) is not, because
    asking again straight away only makes it worse."""
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(_get, url, timeout)
        except FetchProblem as problem:
            transient = problem.status in (StoreStatus.TIMEOUT, StoreStatus.ERROR)
            if attempt == retries or not transient:
                raise
            await asyncio.sleep(2)
