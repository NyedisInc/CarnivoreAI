
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.huddle import artifacts
from src.cplugs.sdk import sandboxed_html

ROOT = Path(__file__).resolve().parents[3]

BEFORE = {
    "Content-Security-Policy": ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                "img-src data:; font-src data:; media-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; "
                                "object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"),
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "private, no-store",
    "Content-Disposition": 'inline; filename="artifact.html"',
}


def test_the_artifact_viewer_headers_are_byte_identical_after_the_move() -> None:
    assert list(artifacts.VIEW_HEADERS.items()) == list(BEFORE.items())
    assert sandboxed_html.VIEW_CSP == BEFORE["Content-Security-Policy"]


def test_each_call_is_a_fresh_dict_with_its_own_file_name() -> None:
    one = sandboxed_html.view_headers("r001.html")
    one["X-Extra"] = "1"
    assert "X-Extra" not in sandboxed_html.view_headers("r001.html")
    assert one["Content-Disposition"] == 'inline; filename="r001.html"'


@pytest.mark.parametrize("name", ["", 'a".html', "a\r\nX: y", "../a.html", "a b.html", "x" * 65, "r001.html\n", None])
def test_a_file_name_that_could_break_the_header_is_refused(name: object) -> None:
    with pytest.raises(ValueError):
        sandboxed_html.view_headers(name)  # type: ignore[arg-type]


def test_there_is_one_copy_of_the_sandbox_policy_under_src() -> None:
    holders = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
                     if "sandbox allow-scripts; default-src 'none'" in p.read_text(encoding="utf-8"))
    assert holders == ["src/cplugs/sdk/sandboxed_html.py"]
