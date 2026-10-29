
from __future__ import annotations

import json

import pytest

from src.core.browser_pages import open_pages, store

ART = {"item": 7, "artifact": "a1"}


@pytest.fixture(autouse=True)
def _clean():
    open_pages.reset_for_test()
    yield
    open_pages.reset_for_test()


def _restart(state_dir):
    open_pages.reset_for_test()
    open_pages.configure(state_dir)


def test_rows_survive_restart_with_same_id_order_and_target(tmp_path):
    open_pages.configure(tmp_path)
    first = open_pages.open_page("app:/static/popout.html?tab=flow", "app", "Flow", src="/static/popout.html?tab=flow")
    second = open_pages.open_page("artifact:7:a1", "artifact", "Report", ref=ART)
    open_pages.open_page("app:/static/popout.html?tab=flow", "app", "Flow again", src="/static/popout.html?tab=flow")
    before = open_pages.listing()
    _restart(tmp_path)
    after = open_pages.listing()
    assert [p.id for p in after] == [first.id, second.id]
    assert after == before
    assert after[1].ref == ART and after[0].title == "Flow again"
    third = open_pages.open_page("app:/static/popout.html?tab=x", "app", "X", src="/static/popout.html?tab=x")
    assert third.seq > max(p.seq for p in after)


def test_close_removes_row_from_disk(tmp_path):
    open_pages.configure(tmp_path)
    a = open_pages.open_page("k1", "app", "A", src="/static/popout.html?a")
    b = open_pages.open_page("k2", "app", "B", src="/static/popout.html?b")
    assert open_pages.close(a.id)
    stored = json.loads(store.path_in(tmp_path).read_text())["pages"]
    assert [r["id"] for r in stored] == [b.id]
    _restart(tmp_path)
    assert [p.id for p in open_pages.listing()] == [b.id]


def test_corrupt_file_does_not_break_load_and_is_moved_aside(tmp_path):
    target = store.path_in(tmp_path)
    target.write_text("{not json")
    open_pages.configure(tmp_path)
    assert open_pages.listing() == []
    assert not target.exists()
    assert len(list(tmp_path.glob("browser_pages.json.corrupt-*"))) == 1
    open_pages.open_page("k", "app", "A", src="/static/popout.html?a")
    assert target.exists()


def test_malformed_row_is_dropped_and_good_rows_kept(tmp_path):
    good = {"id": "a" * 16, "key": "k", "frame": "app", "title": "T", "opened_at": 1.0, "ref": None,
            "src": "/static/popout.html?a", "seq": 3}
    bad = {"id": 5, "key": "k2"}
    no_target = dict(good, id="b" * 16, key="k3", src=None)
    store.path_in(tmp_path).write_text(json.dumps({"version": 1, "pages": [good, bad, "junk", no_target]}))
    open_pages.configure(tmp_path)
    assert [p.id for p in open_pages.listing()] == ["a" * 16]


def test_unconfigured_writes_nothing(tmp_path):
    open_pages.open_page("k", "app", "A", src="/static/popout.html?a")
    assert list(tmp_path.iterdir()) == []
