
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_brw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_brw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import pytest

from src.core.browsers.input import MAX_TEXT_BYTES, InputRejected, map_input
from src.core.browsers.url_policy import (
    UrlRefused,
    error_code,
    is_allowed,
    normalize_url,
    origin_of,
    storable_url,
)

REFUSED = [
    "file:///etc/passwd",
    "file://localhost/etc/passwd",
    "FILE://localhost/Users",
    "chrome://settings",
    "chrome-untrusted://x",
    "chrome-extension://abc/page.html",
    "devtools://devtools/bundled/inspector.html",
    "view-source:https://example.com",
    "javascript:alert(1)",
    "javascript://example.com/%0aalert(1)",
    "JavaScript:alert(document.cookie)",
    "data:text/html,<script>alert(1)</script>",
    "data://example.com/x",
    "blob:https://example.com/uuid",
    "about:config",
    "ftp://example.com",
    "https:example.com",
    "http://[::1",
    "https://example.com/\nx",
]


@pytest.mark.parametrize("url", REFUSED)
def test_every_refused_scheme_is_refused(url):
    with pytest.raises(UrlRefused):
        normalize_url(url)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, "about:blank"),
        ("", "about:blank"),
        ("about:blank", "about:blank"),
        ("example.com", "https://example.com"),
        ("https://example.com/a?b=1#c", "https://example.com/a?b=1#c"),
        ("localhost:3000/app", "http://localhost:3000/app"),
        ("127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("203.0.113.13:5173", "https://203.0.113.13:5173"),
        ("  http://example.com  ", "http://example.com"),
        ("HTTPS://Example.com/P", "https://Example.com/P"),
    ],
)
def test_allowed_urls_pass_and_bare_hosts_get_a_scheme(raw, expected):
    assert normalize_url(raw) == expected


def test_page_produced_urls_are_checked_without_rewriting():
    assert is_allowed("https://example.com/x")
    assert is_allowed("about:blank")
    assert not is_allowed("example.com")
    assert not is_allowed("file:///etc/passwd")


def test_logs_get_the_origin_and_storage_drops_the_query():
    url = "https://user:pw@example.com:8443/cb?code=SECRET#frag"
    assert origin_of(url) == "https://example.com:8443"
    assert "SECRET" not in storable_url(url)
    assert storable_url(url) == "https://example.com:8443/cb"
    assert storable_url("http://[::1]:3000/a?x=1") == "http://[::1]:3000/a"
    assert storable_url("javascript:alert(1)") == "about:blank"


def test_an_error_is_logged_as_its_code_never_its_url():
    exc = RuntimeError("Page.goto: net::ERR_ABORTED at https://a.b/f?X-Amz-Signature=S")
    assert error_code(exc) == "net::ERR_ABORTED"
    assert error_code(TimeoutError("Timeout 15000ms navigating to https://a/?t=S")) == "TimeoutError"




def test_a_click_maps_to_a_clamped_cdp_mouse_event():
    method, params = map_input(
        {"type": "mouse", "event": "down", "x": 5000, "y": -3,
         "button": "left", "clickCount": 1}, 800, 600)
    assert method == "Input.dispatchMouseEvent"
    assert params["type"] == "mousePressed"
    assert (params["x"], params["y"]) == (800.0, 0.0)


def test_a_printable_key_carries_text_and_a_control_key_does_not():
    _, printable = map_input({"type": "key", "event": "down", "key": "a",
                              "code": "KeyA", "keyCode": 65, "text": "a"}, 800, 600)
    _, control = map_input({"type": "key", "event": "down", "key": "Enter",
                            "code": "Enter", "keyCode": 13}, 800, 600)
    assert printable["type"] == "keyDown" and printable["text"] == "a"
    assert control["type"] == "rawKeyDown" and "text" not in control


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "mouse", "event": "down", "x": float("nan"), "y": 1},
        {"type": "mouse", "event": "drag", "x": 1, "y": 1},
        {"type": "mouse", "event": "down", "x": 1, "y": 1, "button": "back"},
        {"type": "mouse", "event": "down", "x": 1, "y": 1, "clickCount": 99},
        {"type": "key", "event": "down", "key": "k" * 100},
        {"type": "key", "event": "press", "key": "a"},
        {"type": "text", "value": "x" * (MAX_TEXT_BYTES + 1)},
        {"type": "text", "value": 5},
        {"type": "evaluate", "expression": "1"},
    ],
)
def test_malformed_or_oversized_input_is_rejected(msg):
    with pytest.raises(InputRejected):
        map_input(msg, 800, 600)
