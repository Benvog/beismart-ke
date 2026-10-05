import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from beismart import store
from beismart.db import connect
from beismart.export import MARKER, export, history_name, query_slug


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def add(conn, store_name, url, title, points, converted=False):
    lid = conn.execute("INSERT INTO listings (store, url, title, first_seen, last_seen) VALUES (?,?,?,?,?)",
                       (store_name, url, title, ago(points[0][0]), ago(0))).lastrowid
    for d, price in points:
        conn.execute("INSERT INTO price_points (listing_id, price, in_stock, converted, seen_at) VALUES (?,?,1,?,?)",
                     (lid, price, int(converted), ago(d)))
    return lid


@pytest.fixture
def conn():
    c = connect(":memory:")
    add(c, "Jumia", "https://j.test/tv", "Samsung 43U8000 43\" Crystal UHD 4K Smart TV", [(9, 50000.0), (2, 45000.0)])
    add(c, "Hotpoint", "https://h.test/tv", "Samsung 43\" LED UHD TV UA43U8000FUXKE", [(8, 48000.0)])
    add(c, "Amazon", "https://a.test/tv", "Samsung 43 Inch U8000F Smart TV", [(5, 39000.0)], converted=True)
    add(c, "Kilimall", "https://k.test/fryer", "Ramtons 5L Digital Air Fryer", [(6, 7000.0)])
    store.record_search(c, "samsung tv")
    c.commit()
    return c


@pytest.fixture
def web(tmp_path):
    d = tmp_path / "web"
    (d / "js").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html>")
    (d / "js" / "data.js").write_text("// data layer")
    (d / "data").mkdir()
    (d / "data" / "local-sample.json").write_text("{}")          # a local demo export must not be published
    return str(d)


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_export_writes_the_site_and_the_data_files(conn, web, tmp_path):
    out = str(tmp_path / "demo")
    s = export(conn, out, queries=["samsung tv", "air fryer", "kettle"], web_dir=web)
    assert s.queries == ["samsung tv", "air fryer"] and s.skipped == ["kettle"]         # no results: left out
    assert os.path.exists(os.path.join(out, "index.html")) and os.path.exists(os.path.join(out, "js", "data.js"))
    assert os.path.exists(os.path.join(out, ".nojekyll"))
    assert not os.path.exists(os.path.join(out, "data", "local-sample.json"))
    assert read(os.path.join(out, "data", "index.json"))["queries"] == ["samsung tv", "air fryer"]
    tv = read(os.path.join(out, "data", "search", "samsung-tv.json"))
    assert tv["query"] == "samsung tv" and tv["groups"] and "hidden" in tv


def test_amazon_is_left_out_everywhere(conn, web, tmp_path):
    out = str(tmp_path / "demo")
    export(conn, out, queries=["samsung tv"], web_dir=web)
    for root, _, files in os.walk(os.path.join(out, "data")):
        for name in files:
            assert "Amazon" not in open(os.path.join(root, name), encoding="utf-8").read(), name
    tv = read(os.path.join(out, "data", "search", "samsung-tv.json"))
    assert tv["count"] == 2 and {m["store"] for g in tv["groups"] for m in g["members"]} == {"Jumia", "Hotpoint"}


def test_history_and_drops_use_the_names_the_website_asks_for(conn, web, tmp_path):
    out = str(tmp_path / "demo")
    export(conn, out, queries=["samsung tv"], web_dir=web)
    group = read(os.path.join(out, "data", "search", "samsung-tv.json"))["groups"][0]
    hist = read(os.path.join(out, "data", "history", history_name([m["id"] for m in group["members"]]) + ".json"))
    assert [c["price"] for c in hist["best"]] == [50000.0, 48000.0, 45000.0]
    drops = read(os.path.join(out, "data", "drops.json"))
    assert len(drops) == 1 and drops[0]["query"] == "samsung tv" and drops[0]["price_drop"] == 3000.0


@pytest.mark.parametrize("q,slug", [("samsung tv", "samsung-tv"), ("  Air   Fryer ", "air-fryer"),
                                    ('samsung 43" tv', "samsung-43-tv"), ("iphone 15 pro-max", "iphone-15-pro-max")])
def test_file_names_match_the_website(q, slug):
    assert query_slug(q) == slug                       # same rule as querySlug() in web/js/data.js
    assert history_name([12, 3, 7]) == "3-7-12"        # same rule as history() in web/js/data.js


def test_never_deletes_a_folder_it_did_not_make(conn, web, tmp_path):
    out = tmp_path / "mine"
    out.mkdir()
    (out / "notes.txt").write_text("keep me")
    with pytest.raises(SystemExit):
        export(conn, str(out), queries=["samsung tv"], web_dir=web)
    assert (out / "notes.txt").read_text() == "keep me"


def test_rerunning_replaces_its_own_earlier_export(conn, web, tmp_path):
    out = str(tmp_path / "demo")
    export(conn, out, queries=["samsung tv", "air fryer"], web_dir=web)
    export(conn, out, queries=["air fryer"], web_dir=web)
    assert os.path.exists(os.path.join(out, MARKER))
    assert not os.path.exists(os.path.join(out, "data", "search", "samsung-tv.json"))   # nothing stale left behind
