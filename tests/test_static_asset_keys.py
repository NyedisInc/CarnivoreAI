
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core import static_asset_keys as keys

CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"


@pytest.fixture(autouse=True)
def _cold_module() -> None:
    keys.reset_for_tests()
    yield
    keys.reset_for_tests()


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    (tmp_path / "js").mkdir()
    (tmp_path / "css").mkdir()
    (tmp_path / "js" / "a.js").write_text("window.A = 1\n")
    (tmp_path / "css" / "one.css").write_text("body{color:red}\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n")
    return tmp_path




def test_the_key_is_derived_from_content_not_from_the_name(tree: Path) -> None:
    twin = tree / "js" / "twin.js"
    twin.write_text("window.A = 1\n")
    assert keys.content_key(tree / "js" / "a.js") == keys.content_key(twin)
    twin.write_text("window.A = 99\n")
    keys.reset_for_tests()
    assert keys.content_key(tree / "js" / "a.js") != keys.content_key(twin)


def test_an_edited_file_gets_a_new_key_with_no_restart(tree: Path) -> None:
    path = tree / "js" / "a.js"
    before = keys.content_key(path)
    path.write_text("window.A = 1 // edited\n")
    after = keys.content_key(path)
    assert before is not None and after is not None and before != after


def test_a_file_that_cannot_be_read_has_no_key(tree: Path) -> None:
    assert keys.content_key(tree / "js" / "nope.js") is None
    assert keys.key_is_current(tree / "js" / "nope.js", "abc") is False


def test_key_is_current_refuses_a_stale_or_empty_key(tree: Path) -> None:
    path = tree / "js" / "a.js"
    current = keys.content_key(path)
    assert keys.key_is_current(path, current) is True
    assert keys.key_is_current(path, "") is False
    assert keys.key_is_current(path, "deadbeefcafe") is False
    path.write_text("window.A = 3\n")
    assert keys.key_is_current(path, current) is False


def test_cache_control_for_is_immutable_only_on_a_match(tree: Path) -> None:
    path = tree / "js" / "a.js"
    assert keys.cache_control_for(path, keys.content_key(path)) == keys.IMMUTABLE
    assert keys.cache_control_for(path, "deadbeefcafe") == keys.REVALIDATE
    assert keys.cache_control_for(path, "") == keys.REVALIDATE
    assert keys.cache_control_for(None, "deadbeefcafe") == keys.REVALIDATE
    assert keys.cache_control_for(tree / "gone.js", "deadbeefcafe") == keys.REVALIDATE




def test_only_same_origin_static_urls_are_touched(tree: Path) -> None:
    html = (
        '<link rel="icon" href="data:image/png;base64,AAAA">\n'
        '<script src="https://cdn.example/x.js"></script>\n'
        '<script src="//cdn.example/y.js"></script>\n'
        '<link rel="manifest" href="/manifest.webmanifest">\n'
        '<script src="/static/js/a.js"></script>\n'
    )
    out = keys.render(html, tree)
    assert "data:image/png;base64,AAAA" in out
    assert 'src="https://cdn.example/x.js"' in out
    assert 'src="//cdn.example/y.js"' in out
    assert 'href="/manifest.webmanifest"' in out
    assert re.search(r'src="/static/js/a\.js\?v=[0-9a-f]{12}"', out)


def test_a_url_that_already_carries_a_query_is_left_alone(tree: Path) -> None:
    html = '<script src="/static/js/a.js?debug=1"></script>'
    assert keys.render(html, tree) == html


def test_an_anchor_href_is_never_keyed(tree: Path) -> None:
    html = (
        '<a href="/static/js/a.js">download</a>\n'
        '<link rel="stylesheet" href="/static/css/one.css">\n'
    )
    out = keys.render(html, tree)
    assert '<a href="/static/js/a.js">' in out
    assert re.search(
        r'<link rel="stylesheet" href="/static/css/one\.css\?v=[0-9a-f]{12}">', out
    )


@pytest.mark.parametrize(
    "tag",
    [
        '<script type="module" src="{u}"></script>',
        '<script defer src="{u}"></script>',
        '<script async src="{u}"></script>',
        '<img src="{u}" alt="">',
        '<source src="{u}">',
        "<video src='{u}'></video>",
    ],
)
def test_the_rewrite_does_not_care_what_kind_of_tag_it_is(tree: Path, tag: str) -> None:
    out = keys.render(tag.format(u="/static/logo.png"), tree)
    assert re.search(r"/static/logo\.png\?v=[0-9a-f]{12}", out), out


def test_one_tag_and_two_hundred_tags_get_the_same_treatment(tree: Path) -> None:
    one = keys.render('<script src="/static/js/a.js"></script>', tree)
    many = keys.render('<script src="/static/js/a.js"></script>\n' * 200, tree)
    assert many.count("?v=") == 200
    assert many.splitlines()[0] == one


def test_url_to_path_refuses_an_escape(tree: Path) -> None:
    assert keys.url_to_path("/static/../../etc/passwd", tree) is None
    assert keys.url_to_path("/static/../../etc/passwd", tree) is None
    assert keys.url_to_path("/etc/passwd", tree) is None
    assert keys.url_to_path("/static/js/a.js", tree) == (tree / "js" / "a.js").resolve()


def test_an_unresolvable_url_is_passed_through_rather_than_dropped(tree: Path) -> None:
    html = '<script src="/static/js/gone.js"></script>'
    assert keys.render(html, tree) == html


def test_the_rewrite_is_stable_for_an_unchanged_tree(tree: Path) -> None:
    html = '<script src="/static/js/a.js"></script>'
    assert keys.render(html, tree) == keys.render(html, tree)




def test_the_real_shell_keys_every_static_url_it_references() -> None:
    html = (CLIENT_DIR / "index.html").read_text(encoding="utf-8")
    out = keys.render(html, CLIENT_DIR)
    unkeyed = [u for u in keys.iter_static_urls(out) if "?v=" not in u]
    assert unkeyed == [], f"unkeyed static URLs survived the rewrite: {unkeyed}"


def test_the_real_shell_still_loads_exactly_the_same_assets() -> None:
    html = (CLIENT_DIR / "index.html").read_text(encoding="utf-8")
    before = list(keys.iter_static_urls(html))
    after = [
        u.split("?", 1)[0]
        for u in keys.iter_static_urls(keys.render(html, CLIENT_DIR))
    ]
    assert before == after
    assert len(before) > 100, "the shell should reference many assets; did the scan break?"


def _client() -> TestClient:
    from src.api.shell.static import NoCacheStaticFiles

    app = FastAPI()
    app.mount("/static", NoCacheStaticFiles(directory=str(CLIENT_DIR)), name="static")
    return TestClient(app)


def test_a_matching_key_is_immutable_and_anything_else_revalidates() -> None:
    url = "/static/js/app.js"
    key = keys.content_key(CLIENT_DIR / "js" / "app.js")
    with _client() as client:
        keyed = client.get(f"{url}?v={key}")
        stale = client.get(f"{url}?v=000000000000")
        bare = client.get(url)
    assert keyed.status_code == 200
    assert keyed.headers["cache-control"] == keys.IMMUTABLE
    assert stale.headers["cache-control"] == keys.REVALIDATE
    assert bare.headers["cache-control"] == keys.REVALIDATE


def test_a_conditional_request_for_a_keyed_url_is_still_immutable() -> None:
    url = "/static/css/styles.css"
    key = keys.content_key(CLIENT_DIR / "css" / "styles.css")
    with _client() as client:
        first = client.get(f"{url}?v={key}")
        second = client.get(
            f"{url}?v={key}", headers={"If-None-Match": first.headers["etag"]}
        )
    assert second.status_code == 304
    assert second.headers["cache-control"] == keys.IMMUTABLE


def test_a_keyed_css_response_is_still_served_and_still_compressible() -> None:
    key = keys.content_key(CLIENT_DIR / "css" / "styles.css")
    with _client() as client:
        response = client.get(
            f"/static/css/styles.css?v={key}", headers={"Accept-Encoding": "gzip"}
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.headers.get("content-encoding") == "gzip"
    assert response.headers["cache-control"] == keys.IMMUTABLE


def test_the_shell_itself_is_never_immutable() -> None:
    with _client() as client:
        response = client.get("/static/index.html?v=deadbeefcafe")
    assert response.headers["cache-control"] == keys.REVALIDATE


def test_an_image_is_left_on_the_browser_default() -> None:
    with _client() as client:
        response = client.get("/static/assets/icons/icon-192.png?v=deadbeefcafe")
    assert response.status_code == 200
    assert response.headers.get("cache-control") is None


def test_the_shell_fingerprint_tracks_the_rendered_bytes() -> None:
    assert keys.shell_fingerprint("a") == keys.shell_fingerprint("a")
    assert keys.shell_fingerprint("a") != keys.shell_fingerprint("b")


def test_warm_hashes_the_real_shells_assets() -> None:
    keys.reset_for_tests()
    assert keys.warm(CLIENT_DIR, CLIENT_DIR / "index.html") > 100


def test_warm_survives_a_missing_shell(tmp_path: Path) -> None:
    assert keys.warm(tmp_path, tmp_path / "nope.html") == 0


@pytest.mark.parametrize("page", ["style-guide.html", "popout.html"])
def test_hand_written_pages_get_keyed_links_and_never_immutable(page: str) -> None:
    html = _client().get(f"/static/{page}")
    assert html.status_code == 200
    assert "immutable" not in html.headers["cache-control"]
    stamped = [u for u in keys.iter_static_urls(html.text) if "?v=" in u]
    assert stamped, f"{page} references no keyed /static/ url"
    unkeyed = [u for u in keys.iter_static_urls(html.text) if "?v=" not in u]
    assert not unkeyed, unkeyed[:3]
    raw = _client().get("/static/css/layers.css")
    assert raw.text == (CLIENT_DIR / "css" / "layers.css").read_text(encoding="utf-8")
