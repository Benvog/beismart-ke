"""Publish the public demo: export today's prices and push them to the GitHub Pages branch.

    .venv\\Scripts\\python -m beismart.publish                   uses BEISMART_PAGES_DIR
    .venv\\Scripts\\python -m beismart.publish --pages <folder>

The pages folder is a git checkout of the demo branch (gh-pages) with its remote set up. The branch keeps a single commit
that is replaced each time (a snapshot's history has no use, and keeping it would grow the repo by megabytes a day); the
push uses --force-with-lease, so it refuses if the remote has anything this script did not put there.
Nothing is published when the export came out empty: the live demo keeps its last good data instead."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from .db import connect, now
from .export import MARKER, ExportSummary, export


@dataclass
class PublishResult:
    summary: ExportSummary
    changed: bool
    pushed: bool


def _git(cwd: str, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


def publish(conn, pages: str, push: bool = True) -> PublishResult:
    if not os.path.isdir(os.path.join(pages, ".git")):
        raise SystemExit(f"{pages} is not a git checkout of the demo branch")
    branch = _git(pages, "symbolic-ref", "--short", "HEAD")            # works before the first commit too

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "demo")
        summary = export(conn, out)
        if not summary.queries:
            raise SystemExit("The export has no searches with results; not publishing (the live demo is unchanged)")

        # Replace everything in the checkout except .git with the new export
        for name in os.listdir(pages):
            if name == ".git":
                continue
            p = os.path.join(pages, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        for name in os.listdir(out):
            if name == MARKER:
                continue
            src = os.path.join(out, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, os.path.join(pages, name))

    _git(pages, "add", "-A")
    has_commit = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=pages, capture_output=True).returncode == 0
    if has_commit and not _git(pages, "status", "--porcelain"):
        return PublishResult(summary, changed=False, pushed=False)

    message = (f"Demo: prices as of {now()[:10]}\n\n{len(summary.queries)} searches, {summary.products} products, "
               f"{summary.drops} price drops. Exported with python -m beismart.export (Amazon left out).")
    _git(pages, "commit", *(["--amend"] if has_commit else []), "-q", "-m", message)
    if push:
        _git(pages, "push", "--force-with-lease", "-q", "origin", branch)
    return PublishResult(summary, changed=True, pushed=push)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the demo and push it to GitHub Pages.")
    parser.add_argument("--pages", default=os.environ.get("BEISMART_PAGES_DIR"),
                        help="git checkout of the demo branch (default: BEISMART_PAGES_DIR)")
    parser.add_argument("--no-push", action="store_true", help="commit locally but do not push")
    args = parser.parse_args()
    if not args.pages:
        sys.exit("Give --pages <folder> or set BEISMART_PAGES_DIR")
    conn = connect(os.environ.get("BEISMART_DB", "beismart_v2.db"))
    r = publish(conn, args.pages, push=not args.no_push)
    s = r.summary
    state = "published" if r.pushed else "committed (not pushed)" if r.changed else "no changes since the last publish"
    print(f"Demo {state}: {len(s.queries)} searches, {s.products} products, {s.drops} price drops")


if __name__ == "__main__":
    main()
