import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from beismart import store
from beismart.db import connect
from beismart.publish import publish


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


@pytest.fixture
def conn():
    c = connect(":memory:")
    lid = c.execute("INSERT INTO listings (store, url, title, first_seen, last_seen) VALUES (?,?,?,?,?)",
                    ("Jumia", "https://j.test/tv", "Samsung 43U8000 43\" Crystal UHD 4K Smart TV", ago(3), ago(0))).lastrowid
    c.execute("INSERT INTO price_points (listing_id, price, in_stock, seen_at) VALUES (?,?,1,?)", (lid, 45000.0, ago(3)))
    store.record_search(c, "samsung tv")
    c.commit()
    return c


@pytest.fixture
def pages(tmp_path):
    """A bare 'GitHub' repo and a checkout of its gh-pages branch, like D:\\beismart-ke-pages."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    work = tmp_path / "pages"
    git(tmp_path, "init", "-q", "-b", "gh-pages", str(work))
    git(work, "config", "user.email", "test@example.com")
    git(work, "config", "user.name", "Test")
    git(work, "remote", "add", "origin", str(remote))
    return work, remote


def test_publish_pushes_the_export_as_a_single_commit(conn, pages):
    work, remote = pages
    r = publish(conn, str(work))
    assert r.pushed and r.summary.queries
    assert os.path.exists(work / "index.html") and os.path.exists(work / "data" / "index.json")
    assert not os.path.exists(work / ".beismart-export")              # the export's marker is not published
    publish(conn, str(work))                                           # the next day's publish
    assert git(remote, "rev-list", "--count", "gh-pages") == "1"       # replaced, not piled up
    assert git(remote, "rev-parse", "gh-pages") == git(work, "rev-parse", "HEAD")


def test_nothing_is_published_when_the_export_is_empty(pages):
    work, remote = pages
    with pytest.raises(SystemExit):
        publish(connect(":memory:"), str(work))                        # no saved prices at all
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "gh-pages"], cwd=remote).returncode != 0


def test_refuses_a_folder_that_is_not_a_git_checkout(conn, tmp_path):
    with pytest.raises(SystemExit):
        publish(conn, str(tmp_path))


def test_does_not_overwrite_changes_someone_else_pushed(conn, pages, tmp_path):
    work, remote = pages
    publish(conn, str(work))
    other = tmp_path / "other"                                         # someone pushes to gh-pages meanwhile
    git(tmp_path, "clone", "-q", "-b", "gh-pages", str(remote), str(other))
    git(other, "config", "user.email", "x@example.com")
    git(other, "config", "user.name", "X")
    (other / "theirs.txt").write_text("theirs")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "theirs")
    git(other, "push", "-q", "origin", "gh-pages")
    with pytest.raises(RuntimeError):
        publish(conn, str(work))                                       # --force-with-lease refuses
    assert "theirs" in git(remote, "log", "-1", "--format=%s", "gh-pages")
