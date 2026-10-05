"""Keeping pages a scraper could not read, so a failure can be diagnosed afterwards.

The refresh job runs unattended, so when a store answers with something unexpected the page is the only
evidence. Pages go to logs/debug/ (git-ignored); only the newest few are kept."""

import os
import re
import time

KEEP = 20


def save_unreadable_page(store: str, query: str, html: str, folder: str = os.path.join("logs", "debug")) -> str | None:
    """Write the page to disk and return its path (None if it could not be written)."""
    try:
        os.makedirs(folder, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", f"{store}-{query}".lower()).strip("-")[:60]
        path = os.path.join(folder, f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        for old in sorted(os.listdir(folder))[:-KEEP]:
            os.remove(os.path.join(folder, old))
        return path
    except OSError:
        return None
