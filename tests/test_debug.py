import os

from beismart.scrapers.debug import KEEP, save_unreadable_page


def test_the_page_is_saved_with_the_store_and_query_in_its_name(tmp_path):
    path = save_unreadable_page("Amazon", "air fryer", "<html>odd</html>", str(tmp_path))
    assert path and os.path.basename(path).endswith("amazon-air-fryer.html")
    assert open(path, encoding="utf-8").read() == "<html>odd</html>"


def test_only_the_newest_pages_are_kept(tmp_path):
    for i in range(KEEP + 5):
        save_unreadable_page("Amazon", f"q{i:02d}", "x", str(tmp_path))
    assert len(os.listdir(tmp_path)) == KEEP


def test_a_folder_that_cannot_be_written_does_not_crash_the_scraper():
    assert save_unreadable_page("Amazon", "q", "x", "Z:\no\such\drive\folder") is None
