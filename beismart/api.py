"""The web API. Search reads saved data (instant); refreshing re-scrapes the stores.

Run it:  .venv\\Scripts\\python -m uvicorn beismart.api:app --host 127.0.0.1 --port 8000
Interactive docs are served at /docs."""

import asyncio
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from .db import connect, now
from .history import ProductHistory, Summary, build_history
from .mailer import Mailer, get_mailer
from .products import ProductGroup, group_listings
from .refresh import refresh_query
from .scrapers import Scraper
from .scheduler import queries_to_refresh
from .scrapers.browser import close_browser
from .watch_routes import watch_router

REFRESH_COOLDOWN_S = 300  # the same query can be refreshed at most once every 5 minutes
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


# ── Response shapes (these also drive the /docs page) ─────────────────────────

class ListingOut(BaseModel):
    id: int
    store: str
    title: str
    url: str
    image_url: Optional[str]
    price: float
    old_price: Optional[float]
    in_stock: bool
    last_seen: str
    converted: bool = False                # international price (excludes shipping and import fees)
    hidden_reason: Optional[str] = None


class StoreStatusOut(BaseModel):
    store: str
    status: str
    count: int
    message: str
    duration_ms: int
    ran_at: str
    query: str


class GroupOut(BaseModel):
    """One product with every store's listing of it (a listing that could not be identified is alone)."""
    id: str
    title: str
    image_url: Optional[str]
    key: Optional[str]                     # "brand | model | size or storage | new/refurbished"; None when unidentified
    brand: Optional[str] = None            # lower case, from the title even when the product is unidentified
    condition: str = "new"                 # "new" or "refurbished"
    store_count: int
    best_price: float                      # the cheapest listing that can be bought
    highest_price: float                   # the dearest in-stock listing, so a saving can be shown
    members: list[ListingOut]              # in stock first, cheapest first
    price_drop: Optional[float] = None     # KSh the best price fell by recently (for a "Price drop" badge)
    previous_best: Optional[float] = None  # the best price before that fall (the struck-through price)
    lowest_ever: bool = False              # today's best price is the lowest we have seen (a "Lowest ever" badge)


class DropOut(GroupOut):
    """A product whose best price fell recently, with the search it was found by (for links to it)."""
    query: str


class SearchOut(BaseModel):
    query: str
    count: int
    results: list[ListingOut]
    groups: list[GroupOut]                 # the same listings, merged by product
    hidden_count: int                      # listings judged to be junk (accessories, far-too-cheap oddities)
    hidden: list[ListingOut]               # filled only when show_hidden=true
    stores: list[StoreStatusOut]


class RefreshOut(BaseModel):
    query: str
    listings: int
    price_points_added: int
    stores: list[StoreStatusOut]


class ChangeOut(BaseModel):
    at: str
    price: Optional[float]                 # null: nothing was in stock from this moment


class StoreSeriesOut(BaseModel):
    store: str
    points: list[ChangeOut]


class SummaryOut(BaseModel):
    current: Optional[float]
    lowest_ever: Optional[float]
    lowest_at: Optional[str]
    highest_ever: Optional[float]
    first_seen: Optional[str]
    previous: Optional[float]
    changed_at: Optional[str]
    drop: Optional[float]
    is_lowest_ever: bool


class HistoryOut(BaseModel):
    """What a product cost over time, across every listed store. Points are the moments a price changed,
    so draw them as a step line that runs on to now."""
    best: list[ChangeOut]                  # cheapest in-stock price across all the stores
    stores: list[StoreSeriesOut]           # each store's cheapest in-stock price
    summary: SummaryOut
    as_of: str


class PricePointOut(BaseModel):
    price: float
    old_price: Optional[float]
    in_stock: bool
    seen_at: str


def _group_out(group: ProductGroup, summary: Summary) -> GroupOut:
    in_stock = [m.price for m in group.members if m.in_stock] or [m.price for m in group.members]
    return GroupOut(price_drop=summary.drop, previous_best=summary.previous if summary.drop else None,
                    lowest_ever=summary.is_lowest_ever, id=group.id, title=group.title, image_url=group.image_url,
                    key=str(group.key) if group.key else None, brand=group.brand, condition=group.condition,
                    store_count=len(group.stores),
                    best_price=group.best.price, highest_price=max(in_stock),
                    members=[ListingOut(**vars(m)) for m in group.members])


def _groups(conn: sqlite3.Connection, shown: list) -> list[GroupOut]:
    tracked = store.tracked(conn, [l.id for l in shown])          # every price history in one go
    out = []
    for group in group_listings(shown):
        history = build_history([tracked[m.id] for m in group.members if m.id in tracked])
        out.append(_group_out(group, history.summary))
    return out


def _status_rows(conn: sqlite3.Connection, skip_stores: frozenset[str] = frozenset()) -> list[StoreStatusOut]:
    return [StoreStatusOut(**dict(row)) for row in store.store_status(conn) if row["store"] not in skip_stores]


# ── Responses shared by the routes and the static export (beismart/export.py) ──
# `skip_stores` leaves stores out entirely, as if they had never been scraped (the public demo has no Amazon).

def search_response(conn: sqlite3.Connection, q: str, limit: int, show_hidden: bool,
                    skip_stores: frozenset[str] = frozenset()) -> SearchOut:
    outcome = store.search(conn, q, limit)
    shown = [l for l in outcome.shown if l.store not in skip_stores]
    hidden = [l for l in outcome.hidden if l.store not in skip_stores]
    return SearchOut(query=q, count=len(shown), results=[ListingOut(**vars(f)) for f in shown],
                     groups=_groups(conn, shown),
                     hidden_count=len(hidden),
                     hidden=[ListingOut(**vars(f)) for f in hidden] if show_hidden else [],
                     stores=_status_rows(conn, skip_stores))


def find_drops(conn: sqlite3.Connection, queries: list[str], limit: int) -> list[DropOut]:
    """Products whose best price fell recently, across `queries`. Only Kenyan prices count: international ones exclude
    delivery and import fees, and one appearing must not look like a fall. Biggest fall first, as a share of the old
    price."""
    found: dict[str, DropOut] = {}
    for q in queries:
        local = [l for l in store.search(conn, q, 200).shown if not l.converted]
        for g in _groups(conn, local):
            if g.id in found or not g.price_drop or not g.previous_best or not any(m.in_stock for m in g.members):
                continue
            found[g.id] = DropOut(**g.model_dump(), query=q)
    ranked = sorted(found.values(), key=lambda d: d.price_drop / d.previous_best, reverse=True)
    return ranked[:limit]


def history_response(conn: sqlite3.Connection, ids: list[int]) -> Optional[HistoryOut]:
    """Price history of the listings `ids` (one product's members); None when none of them exist."""
    found = store.tracked(conn, ids)
    if not found:
        return None
    h: ProductHistory = build_history(list(found.values()))
    return HistoryOut(
        best=[ChangeOut(at=c.at, price=c.price) for c in h.best],
        stores=[StoreSeriesOut(store=name, points=[ChangeOut(at=c.at, price=c.price) for c in series])
                for name, series in sorted(h.by_store.items()) if series],      # a store that never had an in-stock price has no line
        summary=SummaryOut(**vars(h.summary)),
        as_of=now(),
    )


# ── App ───────────────────────────────────────────────────────────────────────

def create_app(db_path: Optional[str] = None, stores: Optional[list[Scraper]] = None,
               mailer: Optional[Mailer] = None, base_url: Optional[str] = None) -> FastAPI:
    """`db_path`, `stores` and `mailer` can be overridden (tests do); by default the real database, all stores and the
    mailer chosen by BEISMART_MAIL (an outbox folder unless set to smtp)."""
    path = db_path or os.environ.get("BEISMART_DB", "beismart_v2.db")
    lock = asyncio.Lock()          # one refresh at a time: the browser and the stores are shared
    last_refresh: dict[str, float] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.conn = connect(path)
        app.state.mailer = mailer or get_mailer()
        yield
        await close_browser()
        app.state.conn.close()

    app = FastAPI(title="BeiSmart KE", description="Price comparison across Kenyan online stores.", lifespan=lifespan)
    app.include_router(watch_router(base_url or os.environ.get("BEISMART_BASE_URL", "http://127.0.0.1:8000")))

    @app.get("/api/search", response_model=SearchOut, summary="Search saved prices")
    async def search(request: Request, q: str = Query(..., min_length=2, max_length=100),
                     limit: int = Query(60, ge=1, le=200),
                     show_hidden: bool = Query(False, description="also list the junk that was hidden, with reasons")):
        conn = request.app.state.conn
        store.record_search(conn, q)
        return search_response(conn, q, limit, show_hidden)

    @app.post("/api/refresh", response_model=RefreshOut, summary="Re-scrape the stores for a query")
    async def refresh(request: Request, q: str = Query(..., min_length=2, max_length=100)):
        key = store.normalize_query(q)
        wait = REFRESH_COOLDOWN_S - (time.monotonic() - last_refresh.get(key, -REFRESH_COOLDOWN_S))
        if wait > 0:
            raise HTTPException(429, detail=f"'{q}' was refreshed recently. Try again in {int(wait)} seconds.",
                                headers={"Retry-After": str(int(wait))})
        async with lock:
            conn = request.app.state.conn
            store.record_search(conn, q)
            summary = await refresh_query(conn, q, stores)
            last_refresh[key] = time.monotonic()
        return RefreshOut(query=q, listings=summary.listings, price_points_added=summary.price_points_added,
                          stores=_status_rows(conn))

    @app.get("/api/stores", response_model=list[StoreStatusOut], summary="Latest outcome for each store")
    async def stores_status(request: Request):
        return _status_rows(request.app.state.conn)

    @app.get("/api/drops", response_model=list[DropOut], summary="Products whose best price fell in the last 7 days")
    async def drops(request: Request, limit: int = Query(12, ge=1, le=50)):
        """Looks through every search the daily job keeps fresh (see find_drops)."""
        conn = request.app.state.conn
        return find_drops(conn, queries_to_refresh(conn), limit)

    @app.get("/api/popular", response_model=list[str], summary="Searches to suggest: most searched first, then the daily list")
    async def popular(request: Request, limit: int = Query(8, ge=1, le=30)):
        return queries_to_refresh(request.app.state.conn)[:limit]

    @app.get("/api/history", response_model=HistoryOut, summary="Price history of a product (a group of listings)")
    async def product_history(request: Request, ids: str = Query(..., description="listing ids of one product, comma separated (a group's members)")):
        try:
            wanted = sorted({int(i) for i in ids.split(",") if i.strip()})
        except ValueError:
            raise HTTPException(422, detail="ids must be whole numbers separated by commas")
        if not wanted or len(wanted) > 50:
            raise HTTPException(422, detail="give between 1 and 50 listing ids")
        hist = history_response(request.app.state.conn, wanted)
        if hist is None:
            raise HTTPException(404, detail="No such listings")
        return hist

    @app.get("/api/listings/{listing_id}/history", response_model=list[PricePointOut], summary="Price history of one listing")
    async def history(request: Request, listing_id: int):
        rows = store.price_history(request.app.state.conn, listing_id)
        if not rows:
            raise HTTPException(404, detail="No such listing")
        return [PricePointOut(price=r["price"], old_price=r["old_price"], in_stock=bool(r["in_stock"]),
                              seen_at=r["seen_at"]) for r in rows]

    # The web front end (web/), mounted last so every /api route above wins
    if os.path.isdir(WEB_DIR):
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app


app = create_app()
