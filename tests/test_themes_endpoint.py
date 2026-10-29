from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_themes_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_themes_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.themes_routes as themes_routes_mod
from src.api.auth import require_auth




def _write_manifest(parent: Path, theme_id: str, **overrides) -> Path:
    theme_dir = parent / theme_id
    theme_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": theme_id,
        "name": f"Theme {theme_id}",
        "description": f"description for {theme_id}",
        "cssVars": {"--bg": "#000"},
        "xterm": {"background": "#000"},
    }
    manifest.update(overrides)
    path = theme_dir / "theme.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_raw(parent: Path, theme_id: str, content: bytes) -> Path:
    theme_dir = parent / theme_id
    theme_dir.mkdir(parents=True, exist_ok=True)
    path = theme_dir / "theme.json"
    path.write_bytes(content)
    return path


@pytest.fixture
def themes_app():
    app = FastAPI()
    app.include_router(themes_routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return app


@pytest.fixture
def themes_app_no_auth_override():
    app = FastAPI()
    app.include_router(themes_routes_mod.router, prefix="/api/v1")
    return app


@pytest.fixture
def spy_logger(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(themes_routes_mod, "logger", spy)
    return spy


def _warning_event_names(spy: MagicMock) -> list[str]:
    return [
        call.args[0] if call.args else ""
        for call in spy.warning.call_args_list
    ]


@pytest.fixture
def patched_roots(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    monkeypatch.setattr(themes_routes_mod, "_bundled_themes_root", lambda: bundled)
    monkeypatch.setattr(themes_routes_mod, "_user_themes_root", lambda: user)
    return bundled, user




def test_returns_valid_manifest(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "alpha")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "alpha"
    assert data[0]["source"] == "builtin"


def test_skips_manifest_with_missing_required_field(
    themes_app, patched_roots, spy_logger
):
    bundled, _ = patched_roots
    _write_manifest(bundled, "good")
    bad_dir = bundled / "broken"
    bad_dir.mkdir()
    (bad_dir / "theme.json").write_text(
        json.dumps({"id": "broken", "name": "Broken"}), encoding="utf-8"
    )

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert ids == ["good"]
    assert "theme_manifest_validation_failed" in _warning_event_names(spy_logger)


def test_skips_malformed_json(themes_app, patched_roots, spy_logger):
    bundled, _ = patched_roots
    _write_raw(bundled, "junk", b"{not valid json")
    _write_manifest(bundled, "good")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert ids == ["good"]
    assert "theme_manifest_parse_failed" in _warning_event_names(spy_logger)


def test_skips_id_dir_mismatch(themes_app, patched_roots, spy_logger):
    bundled, _ = patched_roots
    _write_manifest(bundled, "actualname", id="wrongid")
    _write_manifest(bundled, "good")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert ids == ["good"]
    assert "theme_manifest_id_dir_mismatch" in _warning_event_names(spy_logger)




def test_source_labels_bundled_and_user(themes_app, patched_roots):
    bundled, user = patched_roots
    _write_manifest(bundled, "bun-only")
    _write_manifest(user, "usr-only")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    by_id = {t["id"]: t for t in resp.json()}
    assert by_id["bun-only"]["source"] == "builtin"
    assert by_id["usr-only"]["source"] == "user"




def test_bundled_wins_on_id_collision(themes_app, patched_roots, spy_logger):
    bundled, user = patched_roots
    _write_manifest(bundled, "shared", name="Bundled Shared")
    _write_manifest(user, "shared", name="User Shared")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    shared = [t for t in data if t["id"] == "shared"]
    assert len(shared) == 1
    assert shared[0]["source"] == "builtin"
    assert shared[0]["name"] == "Bundled Shared"




def test_sort_order_bundled_first_then_user_alphabetical(
    themes_app, patched_roots
):
    bundled, user = patched_roots
    _write_manifest(bundled, "bz", name="Z-bundled")
    _write_manifest(bundled, "ba", name="A-bundled")
    _write_manifest(bundled, "bm", name="M-bundled")
    _write_manifest(user, "uz", name="user-z-name")
    _write_manifest(user, "ua", name="user-a-name")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    sources = [t["source"] for t in data]
    assert sources == ["builtin", "builtin", "builtin", "user", "user"]
    bundled_names = [t["name"] for t in data if t["source"] == "builtin"]
    assert bundled_names == ["A-bundled", "M-bundled", "Z-bundled"]
    user_ids = [t["id"] for t in data if t["source"] == "user"]
    assert user_ids == ["ua", "uz"]




def test_auth_required_returns_401(themes_app_no_auth_override, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "alpha")

    client = TestClient(themes_app_no_auth_override)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 401




def test_empty_dirs_return_empty_list(themes_app, patched_roots):
    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    assert resp.json() == []


def test_dir_with_no_theme_json_returns_empty(themes_app, patched_roots):
    bundled, _ = patched_roots
    sub = bundled / "no-manifest"
    sub.mkdir()
    (sub / "README.md").write_text("not a theme", encoding="utf-8")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    assert resp.json() == []


def test_binary_garbage_theme_json_does_not_500(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_raw(
        bundled,
        "binary",
        bytes(range(256)),
    )
    _write_manifest(bundled, "ok")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert ids == ["ok"]


def test_user_root_none_does_not_500(themes_app, monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    _write_manifest(bundled, "only-bundled")
    monkeypatch.setattr(themes_routes_mod, "_bundled_themes_root", lambda: bundled)
    monkeypatch.setattr(themes_routes_mod, "_user_themes_root", lambda: None)

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "only-bundled"
    assert data[0]["source"] == "builtin"


def test_hidden_dirs_are_ignored(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "visible")
    hidden = bundled / ".hidden"
    hidden.mkdir()
    (hidden / "theme.json").write_text(
        json.dumps(
            {
                "id": ".hidden",
                "name": "Hidden",
                "description": "should never appear",
                "cssVars": {},
                "xterm": {},
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert ids == ["visible"]


def test_client_supplied_source_field_is_overwritten(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "spoof", source="user")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source"] == "builtin"


def test_bad_shaped_publisher_and_feedback_item_id_do_not_drop_the_theme(
    themes_app, patched_roots
):
    bundled, _ = patched_roots
    _write_manifest(
        bundled,
        "spoof",
        publisher={"name": "not a string"},
        feedbackItemId=12345,
    )

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "spoof"
    assert data[0]["feedbackItemId"] == "bundled/spoof"
    assert data[0]["publisher"] is None



_BACKGROUND_BLOCK = {
    "image": "background.webp",
    "dim": 0.8,
}


def test_background_block_survives_the_response_model(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "withbackground", background=dict(_BACKGROUND_BLOCK))
    (bundled / "withbackground" / _BACKGROUND_BLOCK["image"]).write_bytes(b"fake-webp")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["background"] == _BACKGROUND_BLOCK


def test_theme_without_background_reports_null_not_missing(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "flat")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert "background" in data[0]
    assert data[0]["background"] is None


def test_every_bundled_theme_serves_its_background_block():
    app = FastAPI()
    app.include_router(themes_routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True

    resp = TestClient(app).get("/api/v1/themes")
    assert resp.status_code == 200
    bundled = [t for t in resp.json() if t["source"] == "builtin"]
    assert bundled, "no bundled themes discovered"

    manifests = {json.loads(p.read_text())["id"]: json.loads(p.read_text())
                 for p in (ROOT / "client/css/themes").glob("*/theme.json")}
    for theme in bundled:
        expected = (manifests[theme["id"]].get("background") or {}).get("image")
        assert (theme.get("background") or {}).get("image") == expected, theme["id"]
    assert sum(bool(m.get("background")) for m in manifests.values()) >= 10


def test_out_of_range_background_dim_is_clamped_not_rejected(
    themes_app, patched_roots
):
    bundled, _ = patched_roots
    _write_manifest(
        bundled,
        "overdim",
        background={**_BACKGROUND_BLOCK, "dim": 9.0},
    )
    (bundled / "overdim" / _BACKGROUND_BLOCK["image"]).write_bytes(b"fake-webp")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1, "a clampable value must not drop the theme"
    assert data[0]["background"]["dim"] == 1.0


def test_background_block_without_image_drops_the_theme(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "broken", background={"dim": 0.5})

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    assert resp.json() == []




def test_declared_themecss_missing_file_drops_theme_and_logs_loudly(
    themes_app, patched_roots, spy_logger
):
    bundled, _ = patched_roots
    _write_manifest(bundled, "good")
    _write_manifest(bundled, "dangling", themeCss="theme.css")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert ids == ["good"]
    assert "theme_manifest_themecss_missing" in _warning_event_names(spy_logger)


def test_declared_themecss_with_file_present_still_validates(
    themes_app, patched_roots
):
    bundled, _ = patched_roots
    theme_dir = _write_manifest(bundled, "has-css", themeCss="theme.css").parent
    (theme_dir / "theme.css").write_text("/* real */", encoding="utf-8")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["themeCss"] == "theme.css"


def test_theme_without_themecss_validates_with_null_field(
    themes_app, patched_roots
):
    bundled, _ = patched_roots
    _write_manifest(bundled, "plain")

    client = TestClient(themes_app)
    resp = client.get("/api/v1/themes")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["themeCss"] is None


def test_no_bundled_theme_css_files_remain_on_disk():
    root = themes_routes_mod._bundled_themes_root()
    leftovers = sorted(str(p) for p in root.glob("*/theme.css"))
    assert leftovers == [], f"theme.css files still present: {leftovers}"


def test_no_bundled_theme_declares_a_dangling_themecss():
    root = themes_routes_mod._bundled_themes_root()
    dangling = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "theme.json"
        if not manifest_path.is_file():
            continue
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        theme_css = raw.get("themeCss")
        if theme_css and not (child / theme_css).is_file():
            dangling.append(child.name)
    assert dangling == [], f"themes declaring a missing themeCss: {dangling}"


def test_every_bundled_theme_declares_and_ships_effects_js():
    root = themes_routes_mod._bundled_themes_root()
    theme_dirs = sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    assert theme_dirs, "no bundled theme directories found"

    not_declared = []
    declared_but_missing = []
    for theme_dir in theme_dirs:
        manifest_path = theme_dir / "theme.json"
        effects_on_disk = (theme_dir / "effects.js").is_file()
        effects_declared = None
        if manifest_path.is_file():
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            effects_declared = raw.get("effects")
        if effects_on_disk and effects_declared != "effects.js":
            not_declared.append(theme_dir.name)
        if effects_declared and not (theme_dir / effects_declared).is_file():
            declared_but_missing.append(theme_dir.name)

    assert not_declared == [], f"effects.js present but undeclared: {not_declared}"
    assert declared_but_missing == [], (
        f"effects declared but missing on disk: {declared_but_missing}"
    )




def test_effects_digest_is_stamped_from_the_folder_on_disk(themes_app, patched_roots):
    import hashlib

    from src.core.skills.digest import digest_directory

    _, user = patched_roots
    _write_manifest(user, "withfx", effects="effects.js")
    body = b"export function init() {}\n"
    (user / "withfx" / "effects.js").write_bytes(body)

    client = TestClient(themes_app)
    data = client.get("/api/v1/themes").json()

    assert data[0]["effectsDigest"] == digest_directory(user / "withfx")[0]
    assert data[0]["effectsDigest"] != hashlib.sha256(body).hexdigest()


def test_a_manifest_cannot_declare_its_own_effects_digest(themes_app, patched_roots):
    from src.core.skills.digest import digest_directory

    _, user = patched_roots
    _write_manifest(user, "liar", effects="effects.js", effectsDigest="f" * 64)
    body = b"export function init() {}\n"
    (user / "liar" / "effects.js").write_bytes(body)

    client = TestClient(themes_app)
    data = client.get("/api/v1/themes").json()

    assert data[0]["effectsDigest"] == digest_directory(user / "liar")[0]
    assert data[0]["effectsDigest"] != "f" * 64


def test_a_declared_script_that_is_missing_digests_as_none(themes_app, patched_roots):
    _, user = patched_roots
    _write_manifest(user, "nofile", effects="effects.js")

    client = TestClient(themes_app)
    data = client.get("/api/v1/themes").json()

    assert data[0]["id"] == "nofile"
    assert data[0]["effectsDigest"] is None


def test_a_theme_with_no_script_digests_as_none(themes_app, patched_roots):
    bundled, _ = patched_roots
    _write_manifest(bundled, "plain")

    client = TestClient(themes_app)
    data = client.get("/api/v1/themes").json()

    assert data[0]["effectsDigest"] is None


def test_characters_block_survives_the_response_model(themes_app, patched_roots):
    bundled, _user = patched_roots
    _write_manifest(bundled, "withpack", characters={"pack": "pixel"})
    _write_manifest(bundled, "nopack")

    response = TestClient(themes_app).get("/api/v1/themes")

    assert response.status_code == 200
    by_id = {t["id"]: t for t in response.json()}
    assert by_id["withpack"]["characters"] == {"pack": "pixel"}
    assert by_id["nopack"]["characters"] is None


@pytest.mark.parametrize("bad", ["../x", "Pixel", "a b", "", "x" * 33, "-x", "a--b", "pixel\"onload"])
def test_unsafe_characters_pack_drops_the_theme(themes_app, patched_roots, bad):
    bundled, _user = patched_roots
    _write_manifest(bundled, "badpack", characters={"pack": bad})

    response = TestClient(themes_app).get("/api/v1/themes")

    assert response.status_code == 200
    assert response.json() == []




def _first_party_row(name, digest, **over):
    from src.core.catalog.first_party_listing import pinned_key_id
    from src.core.skills.ledger_types import InstalledItem

    fields = dict(
        install_id="i1", item_id=f"nyedis/{name}", kind="theme", publisher="nyedis",
        name=name, version="1", digest=digest, scope="global", project_path="",
        auto_update=True, source_index_url="", consented_digest=None,
        consented_body_sha=None, publisher_key_id=pinned_key_id(), revision=1,
        installed_at="2026-10-10T00:00:00Z", updated_at="2026-10-10T00:00:00Z", consent_via="sheet",
    )
    fields.update(over)
    return InstalledItem(**fields)


def _signed_theme(user, name="snes", **manifest_over):
    from src.core.skills.digest import digest_directory

    _write_manifest(user, name, effects="effects.js", **manifest_over)
    (user / name / "effects.js").write_bytes(b"export function init() {}\n")
    digest = digest_directory(user / name)[0]
    (user / name / ".carnivore-skill.json").write_text("{}")
    return digest


def _trust(themes_app, patched_roots, monkeypatch, rows, name="snes"):
    monkeypatch.setattr(themes_routes_mod, "_theme_installs_reader", lambda _r: (lambda: tuple(rows)))
    data = TestClient(themes_app).get("/api/v1/themes").json()
    return next(t for t in data if t["id"] == name)["scriptTrust"]


def test_script_trust_first_party_only_for_signed_unedited_owner_install(
    themes_app, patched_roots, monkeypatch
):
    _, user = patched_roots
    digest = _signed_theme(user)
    row = _first_party_row("snes", digest)

    assert _trust(themes_app, patched_roots, monkeypatch, [row]) == "first_party"

    other = _first_party_row("snes", digest, publisher="someone", item_id="someone/snes")
    assert _trust(themes_app, patched_roots, monkeypatch, [other]) is None
    assert _trust(themes_app, patched_roots, monkeypatch, [_first_party_row(
        "snes", digest, publisher_key_id="0000000000000000")]) is None
    assert _trust(themes_app, patched_roots, monkeypatch, []) is None

    fx = user / "snes" / "effects.js"
    fx.write_bytes(b"export function init() {};\n"[: len(fx.read_bytes())])
    assert _trust(themes_app, patched_roots, monkeypatch, [row]) is None


def test_script_trust_withheld_for_a_symlink_and_wiped_from_theme_json(
    themes_app, patched_roots, monkeypatch
):
    _, user = patched_roots
    digest = _signed_theme(user, scriptTrust="first_party")
    assert _trust(themes_app, patched_roots, monkeypatch, []) is None

    from src.core.skills.digest import digest_directory

    sidecar = user / "snes" / ".carnivore-skill.json"
    sidecar.unlink()
    digest = digest_directory(user / "snes")[0]
    sidecar.write_text("{}")
    row = _first_party_row("snes", digest)
    assert _trust(themes_app, patched_roots, monkeypatch, [row]) == "first_party"

    (user / "snes" / "link").symlink_to(user / "snes" / "effects.js")
    assert _trust(themes_app, patched_roots, monkeypatch, [row]) is None
