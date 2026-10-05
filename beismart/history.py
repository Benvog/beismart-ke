"""Price history of a product: what it cost over time, across all the stores that sell it.

Everything here is pure (no database), so it can be tested with made-up price points. The input is the
price points of every listing of one product; the output is compact "change points", the moments a price
moved, which is exactly what a step chart needs."""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

# A listing the stores stopped showing no longer counts after this long (matches the search's freshness).
STOPS_COUNTING_AFTER = timedelta(days=3)
# A drop is "recent" if the price fell within this long.
RECENT = timedelta(days=7)


@dataclass
class Point:
    at: str                       # ISO timestamp
    price: float
    in_stock: bool
    old_price: Optional[float] = None


@dataclass
class Tracked:
    """One listing and every price it has had."""
    store: str
    last_seen: str
    points: list[Point]


@dataclass
class Change:
    at: str
    price: Optional[float]        # None: nothing in stock at that moment


@dataclass
class Summary:
    current: Optional[float]      # cheapest price you could buy at now
    lowest_ever: Optional[float]
    lowest_at: Optional[str]
    highest_ever: Optional[float]
    first_seen: Optional[str]
    previous: Optional[float]     # the best price before the latest change
    changed_at: Optional[str]     # when the best price last changed
    drop: Optional[float]         # KSh the best price fell by in its latest change, if it fell recently
    is_lowest_ever: bool          # today's best equals the lowest ever, and the price has moved at least once


@dataclass
class ProductHistory:
    best: list[Change] = field(default_factory=list)                 # cheapest in-stock price across all stores
    by_store: dict[str, list[Change]] = field(default_factory=dict)  # each store's cheapest in-stock price
    summary: Summary = field(default_factory=lambda: Summary(None, None, None, None, None, None, None, None, False))


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def build_history(listings: list[Tracked], now: Optional[datetime] = None) -> ProductHistory:
    now = now or datetime.now(timezone.utc)
    tracked = [t for t in listings if t.points]
    if not tracked:
        return ProductHistory()
    for t in tracked:
        t.points.sort(key=lambda p: p.at)

    ends = {id(t): _parse(t.last_seen) + STOPS_COUNTING_AFTER for t in tracked}
    moments = {p.at for t in tracked for p in t.points}
    moments |= {e.isoformat(timespec="seconds") for e in ends.values() if e < now}      # a listing stops counting
    best: list[Change] = []
    by_store: dict[str, list[Change]] = {}

    for moment in sorted(moments):
        at = _parse(moment)
        prices: dict[str, list[float]] = {}
        for t in tracked:
            if at < _parse(t.points[0].at) or at >= ends[id(t)]:
                continue                                          # not yet listed, or no longer shown
            idx = bisect_right([p.at for p in t.points], moment) - 1
            point = t.points[idx]
            if point.in_stock:
                prices.setdefault(t.store, []).append(point.price)
        _record(by_store.setdefault("", []), moment, min((p for ps in prices.values() for p in ps), default=None))
        for store in {t.store for t in tracked}:
            _record(by_store.setdefault(store, []), moment, min(prices.get(store, []), default=None))
    best = by_store.pop("")
    return ProductHistory(best=best, by_store=by_store, summary=_summarize(best, now))


def _record(series: list[Change], at: str, price: Optional[float]) -> None:
    if not series and price is None:
        return                                  # a line starts when it first has a price, not before
    if not series or series[-1].price != price:
        series.append(Change(at=at, price=price))


def _summarize(best: list[Change], now: datetime) -> Summary:
    priced = [c for c in best if c.price is not None]
    if not priced:
        return Summary(None, None, None, None, best[0].at if best else None, None, None, None, False)
    current = best[-1].price
    lowest = min(priced, key=lambda c: c.price)
    previous = changed_at = drop = None
    if len(priced) >= 2 or len(best) >= 2:
        before = [c for c in best[:-1] if c.price is not None]
        if before:
            previous, changed_at = before[-1].price, best[-1].at
            if current is not None and current < previous and now - _parse(changed_at) <= RECENT:
                drop = round(previous - current, 2)
    moved = len({c.price for c in priced}) > 1
    return Summary(
        current=current,
        lowest_ever=lowest.price,
        lowest_at=lowest.at,
        highest_ever=max(c.price for c in priced),
        first_seen=best[0].at,
        previous=previous,
        changed_at=changed_at,
        drop=drop,
        is_lowest_ever=bool(moved and current is not None and current <= lowest.price),
    )
