"""Export the public demo: the website plus today's saved prices as static JSON files, ready for GitHub Pages.

The files have the same shapes the API returns, so the website reads them through the same data layer
(web/js/data.js) and every screen works unchanged. Amazon is left out entirely (owner's decision: Amazon
discourages automated access, and its prices exclude delivery and import fees to Kenya).

    .venv\\Scripts\\python -m beismart.export                 writes dist/demo
    .venv\\Scripts\\python -m beismart.export --out <folder>

Searches exported: the most searched ones, then starter_queries.txt (never the watched ones: those are people's
private alerts). A search with no results is left out."""

import argparse
import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field

from . import store
from .api import WEB_DIR, find_drops, history_response, search_response, _status_rows
from .db import connect, now
from .scheduler import starter_queries

DEMO_SKIP = frozenset({"Amazon"})
MARKER = ".beismart-export"          # marks a folder this script made, so it is safe to replace
SEARCH_LIMIT = 200
DROPS_LIMIT = 12


def query_slug(q: str) -> str:
    """The file name for a search; must match querySlug() in web/js/data.js."""
    return re.sub(r"[^a-z0-9]+", "-", store.normalize_query(q)).strip("-")


def history_name(ids: list[int]) -> str:
    """The file name for a product's history; must match history() in web/js/data.js."""
    return "-".join(str(i) for i in sorted(ids))


def demo_queries(conn: sqlite3.Connection, starters: list[str] | None = None) -> list[str]:
    starters = starter_queries() if starters is None else starters
    out: list[str] = []
    for q in store.popular_queries(conn) + starters:
        q = store.normalize_query(q)
        if q and q not in out:
            out.append(q)
    return out


@dataclass
class ExportSummary:
    out: str
    queries: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)      # searches with no results
    products: int = 0
    histories: int = 0
    drops: int = 0


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def _prepare(out: str) -> None:
    """Start from an empty folder. Only a folder this script made earlier (it has MARKER) is ever deleted."""
    if os.path.isdir(out) and os.listdir(out):
        if not os.path.exists(os.path.join(out, MARKER)):
            raise SystemExit(f"{out} is not empty and was not made by this export; choose another --out")
        shutil.rmtree(out)
    os.makedirs(out)
    open(os.path.join(out, MARKER), "w").close()


def export(conn: sqlite3.Connection, out: str, queries: list[str] | None = None, web_dir: str = WEB_DIR) -> ExportSummary:
    queries = demo_queries(conn) if queries is None else queries
    summary = ExportSummary(out=out)
    _prepare(out)

    # The website itself, without any local demo data
    shutil.copytree(web_dir, out, dirs_exist_ok=True, ignore=shutil.ignore_patterns("data"))
    open(os.path.join(out, ".nojekyll"), "w").close()          # GitHub Pages: serve files as they are

    data = os.path.join(out, "data")
    histories: set[str] = set()
    for q in queries:
        result = search_response(conn, q, SEARCH_LIMIT, show_hidden=True, skip_stores=DEMO_SKIP)
        if not result.groups:
            summary.skipped.append(q)
            continue
        _write(os.path.join(data, "search", f"{query_slug(q)}.json"), result.model_dump(mode="json"))
        summary.queries.append(q)
        summary.products += len(result.groups)
        for g in result.groups:
            ids = [m.id for m in g.members]
            name = history_name(ids)
            if name in histories:
                continue
            hist = history_response(conn, ids)
            if hist:
                _write(os.path.join(data, "history", f"{name}.json"), hist.model_dump(mode="json"))
                histories.add(name)
    summary.histories = len(histories)

    drops = [d for d in find_drops(conn, summary.queries, DROPS_LIMIT * 2)
             if not any(m.store in DEMO_SKIP for m in d.members)][:DROPS_LIMIT]
    summary.drops = len(drops)
    _write(os.path.join(data, "drops.json"), [d.model_dump(mode="json") for d in drops])
    _write(os.path.join(data, "stores.json"), [s.model_dump(mode="json") for s in _status_rows(conn, DEMO_SKIP)])
    _write(os.path.join(data, "index.json"), {"queries": summary.queries, "exported_at": now()})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the public demo (website + saved prices as JSON).")
    parser.add_argument("--out", default=os.path.join("dist", "demo"), help="folder to write (default dist/demo)")
    args = parser.parse_args()
    conn = connect(os.environ.get("BEISMART_DB", "beismart_v2.db"))
    s = export(conn, args.out)
    print(f"Exported {len(s.queries)} searches, {s.products} products, {s.histories} price histories and "
          f"{s.drops} price drops to {s.out}")
    if s.skipped:
        print("Left out (no results): " + ", ".join(s.skipped))


if __name__ == "__main__":
    main()
