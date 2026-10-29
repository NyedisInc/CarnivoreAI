
from __future__ import annotations

import pytest

from scripts.gate import default_state as ds


def test_the_walk_finds_every_screen_the_router_serves() -> None:
    hashes = ds.router_hashes()
    assert len(hashes) >= ds.MIN_ROUTES
    assert {"#sessions", "#settings", "#plugins", "#catalog", "#ledger"} <= set(hashes)
    assert all(h.startswith("#") and h == h.lower() for h in hashes)


def test_default_plugin_states_follow_each_manifest() -> None:
    states = ds.default_plugin_states()
    assert states["huddle"] is True and states["share"] is True and states["unread"] is True
    assert states["save"] is False and states["flow"] is False
    assert "tmdevtools" not in states and "devwidgetlab" not in states, "the dev tier is hidden on a fresh install"


def test_a_known_finding_is_split_out_and_a_new_one_stays() -> None:
    console_table = {"page:fake_console": "[FakeWidget] known noise"}
    request_table = {"page:fake_404": ("/api/v1/sessions", 404)}
    page = {"console": ["[FakeWidget] known noise on globalThis", ds.BROWSER_ECHO, "TypeError: something new"],
            "errors": [], "requests": [{"url": "http://x/api/v1/sessions", "status": 404}, {"url": "http://x/api/v1/projects", "status": 500}]}
    rest, matched = ds.split_known(page, console_table, request_table)
    assert sorted(matched) == ["page:fake_404", "page:fake_console"]
    assert rest["console"] == ["TypeError: something new"], "the browser echo of the known 404 goes with it; a new error stays"
    assert rest["requests"] == [{"url": "http://x/api/v1/projects", "status": 500}], "a different failed request is never swallowed"


def test_no_page_defect_is_known_any_more() -> None:
    assert ds.KNOWN_CONSOLE == {} and ds.KNOWN_REQUEST == {}
    page = {"console": ["[TerminalKeyBar] no string layer"], "errors": [], "requests": [{"url": "http://x/api/v1/sessions", "status": 404}]}
    rest, matched = ds.split_known(page)
    assert matched == [] and rest["console"] and rest["requests"]


def test_the_echo_of_an_unknown_404_is_not_swallowed() -> None:
    rest, matched = ds.split_known({"console": [ds.BROWSER_ECHO], "errors": [], "requests": [{"url": "http://x/api/v1/other", "status": 404}]})
    assert matched == [] and rest["console"] == [ds.BROWSER_ECHO] and len(rest["requests"]) == 1


def test_opened_needs_new_lines_and_the_hash() -> None:
    page = "ledger\nrow a\nrow b\nrow c\nrow d"
    assert ds.is_opened({"hash": "#ledger", "text": page}, "#ledger", "home")
    assert ds.is_opened({"hash": "#settings/account/status", "text": page}, "#settings", "home"), "a screen may move to a sub-route"
    assert not ds.is_opened({"hash": "#ledger", "text": "home\nclock 1s"}, "#ledger", "home\nclock 0s"), "only a ticking clock differs: not opened"
    assert not ds.is_opened({"hash": "", "text": page}, "#ledger", "home"), "the hash was lost"


def test_clean_room_judges_known_smoke_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.gate import clean_room as cr
    from scripts.gate import known_defects

    node = "tests/test_synthetic.py::test_listed"
    monkeypatch.setitem(known_defects.CLEAN_ROOM_SMOKE, node, "synthetic")
    monkeypatch.setitem(known_defects.KNOWN, "synthetic", (0, "a synthetic listed defect"))
    assert cr.judge_known(f"FAILED {node}\n", cr.FAIL) == cr.PASS, "only the listed defect failed"
    assert cr.judge_known(f"FAILED {node}\nFAILED tests/test_other.py::test_x\n", cr.FAIL) == cr.FAIL, "a new failure is never swallowed"
    assert cr.judge_known("", cr.PASS) == cr.FAIL, "the listed defect is fixed: the entry must go"
    monkeypatch.delitem(known_defects.CLEAN_ROOM_SMOKE, node)
    assert cr.judge_known("", cr.PASS) == cr.PASS, "an empty table judges nothing"
