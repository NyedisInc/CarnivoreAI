
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_psf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_psf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hosted" / "catalog" / "api"))

# ruff: noqa: E402
import folder_digest as hosted_digest

from src.api import catalog_publish_routes
from src.core.catalog import publish_facts, publish_sends
from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

GOLDEN = ROOT / "tests" / "fixtures" / "publish_page" / "item_facts.json"
SKILL_MD = "---\nname: my-skill\ndescription: use when you need a thing done well\nversion: 1.4.0\nlicense: MIT\n---\n# my skill\n\ndo it.\n"
SUBMITTED = {"submission_id": "a" * 32, "status": "pending", "item_id": "bob/my-skill", "version": "1.4.0"}
MEDIA = {"submission_id": "b" * 32, "status": "pending"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
T0 = 1_760_000_000


def loc(kind: str, folder: Path, harness: str = "") -> dict:
    return {"location_id": f"{kind}:{folder.name}", "kind": kind, "name": folder.name, "harness": harness,
            "scope": "personal", "path": str(folder), "description": "", "description_tokens_est": 12,
            "is_symlink": False, "read_only": False, "plugin": None, "managed": None}


def make_skill(tmp_path: Path) -> Path:
    folder = tmp_path / "skills" / "my-skill"
    (folder / "notes").mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD)
    (folder / "LICENSE").write_text("MIT License\n")
    note = folder / "notes" / "more.md"
    note.write_text("more notes\n")
    note.chmod(0o755)
    for name in ("SKILL.md", "LICENSE", "notes/more.md"):
        os.utime(folder / name, (T0, T0))
    return folder


def sign_in(state: Path) -> None:
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(login="bob", access_token="HELD-ACCESS", access_expires_at=now + 3600,
                                  refresh_token="HELD-REFRESH", refresh_expires_at=now + 86400))


@pytest.fixture
def scan(monkeypatch):
    box: dict = {"locs": [], "writes": 0, "tick": 0}

    async def own(_request):
        return list(box["locs"])

    def after_write(_request):
        box["writes"] += 1

    def clock() -> str:
        box["tick"] += 1
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 + 100 * box["tick"]))

    monkeypatch.setattr(catalog_publish_routes, "_own_locations", own)
    monkeypatch.setattr(catalog_publish_routes.submissions_watch, "after_write", after_write)
    monkeypatch.setattr(publish_sends, "now_iso", clock)
    return box


def app_for(tmp_path: Path):
    routes = {"/submissions/media": (201, MEDIA), "/submissions": (201, SUBMITTED)}
    return hosted_proxy_app(tmp_path, responder=route_responder(routes), include_aggregator=True)


def preview_and_send(app, location: dict, version: str = "1.4.0"):
    body = {"location": location["location_id"], "version": version}
    shown = app.client.post("/catalog/publish/preview", json=body)
    return shown, app.client.post("/catalog/submissions", json={**body, "digest": shown.json()["digest"]})


def test_a_send_records_the_hosted_digest_and_every_member(tmp_path, scan):
    folder = make_skill(tmp_path)
    scan["locs"] = [loc("skill", folder, "claude")]
    with app_for(tmp_path) as app:
        sign_in(app.state)
        _shown, sent = preview_and_send(app, scan["locs"][0])
        assert sent.status_code == 200, sent.text
        upstream = [r for r in app.sent if r.url.path.endswith("/submissions")][-1]
        members = [(f["path"], base64.b64decode(f["content_base64"])) for f in json.loads(upstream.content)["files"]]
        record = publish_sends.PublishSends(app.state).latest_send("skill:my-skill")
    assert record["digest"] == hosted_digest.folder_digest(members)
    assert set(record["files"]) == {"SKILL.md", "LICENSE", "notes/more.md"}
    assert (record["submission_id"], record["harness"], record["kind"], record["name"], record["version"]) == (
        "a" * 32, "claude", "skill", "my-skill", "1.4.0")
    assert scan["writes"] == 1


def test_an_edited_file_is_counted_with_its_mtime(tmp_path, scan):
    folder = make_skill(tmp_path)
    scan["locs"] = [loc("skill", folder, "claude")]
    with app_for(tmp_path) as app:
        sign_in(app.state)
        preview_and_send(app, scan["locs"][0])
        before = app.client.get("/catalog/publish/items/skill:my-skill").json()
        (folder / "LICENSE").write_text("MIT License\nedited\n")
        os.utime(folder / "LICENSE", (T0 + 5000, T0 + 5000))
        after = app.client.get("/catalog/publish/items/skill:my-skill").json()
    assert (before["changed_files"], before["changed_at"]) == (0, "")
    assert (after["changed_files"], after["changed_at"]) == (1, "2025-10-09T10:16:40Z")


def test_the_declared_version_is_read_for_every_kind(tmp_path):
    def write(folder: Path, rel: str, text: str) -> str:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)
        return str(folder)

    theme = write(tmp_path / "t", "theme.json", '{"version": "2.0.1"}')
    plugin = write(tmp_path / "p", ".claude-plugin/plugin.json", '{"version": "0.3.0"}')
    cplug = write(tmp_path / "c", "cplug.json", '{"version": "1.1.0"}')
    skill = write(tmp_path / "s", "SKILL.md", "---\nname: s\nmetadata:\n  version: 3.2.1\n---\n")
    bare = write(tmp_path / "b", "SKILL.md", "---\nname: b\n---\n")
    got = [publish_facts.declared_version(k, p) for k, p in
           (("theme", theme), ("plugin", plugin), ("mod", plugin), ("cplug", cplug), ("skill", skill), ("skill", bare))]
    assert got == ["2.0.1", "0.3.0", "0.3.0", "1.1.0", "3.2.1", ""]


def test_checks_are_recorded_clean_and_refused_and_bounded_at_twenty(tmp_path, scan):
    folder = make_skill(tmp_path)
    scan["locs"] = [loc("skill", folder, "claude")]
    body = {"location": "skill:my-skill", "version": "1.4.0"}
    with app_for(tmp_path) as app:
        for _ in range(20):
            app.client.post("/catalog/publish/preview", json=body)
        (folder / ".env").write_text("x=1\n")
        refused = app.client.post("/catalog/publish/preview", json=body).json()
        facts = app.client.get("/catalog/publish/items/skill:my-skill").json()
    assert refused["can_send"] is False
    assert len(facts["checks"]) == 20
    assert facts["checks"][0]["ok"] is False and facts["checks"][0]["summary"]
    assert facts["checks"][1]["ok"] is True and facts["checks"][1]["summary"] == "clean"
    assert facts["checks"][0]["at"] > facts["checks"][1]["at"]


def test_the_facts_answer_equals_the_golden_and_carries_no_path(tmp_path, scan):
    folder = make_skill(tmp_path)
    scan["locs"] = [loc("skill", folder, "claude")]
    with app_for(tmp_path) as app:
        sign_in(app.state)
        preview_and_send(app, scan["locs"][0])
        facts = app.client.get("/catalog/publish/items/skill:my-skill")
        missing = app.client.get("/catalog/publish/items/skill:nope")
    assert facts.status_code == 200 and missing.status_code == 404
    assert str(tmp_path) not in facts.text
    assert facts.json() == json.loads(GOLDEN.read_text())


def test_a_hero_send_records_its_source_and_notifies(tmp_path, scan):
    folder = make_skill(tmp_path)
    scan["locs"] = [loc("skill", folder, "claude")]
    image = base64.b64encode(PNG).decode()
    with app_for(tmp_path) as app:
        sign_in(app.state)
        preview_and_send(app, scan["locs"][0])
        for source in ("made", "yours"):
            sent = app.client.post("/catalog/submissions/media",
                                   json={"kind": "skill", "name": "my-skill", "image_base64": image, "source": source})
            assert sent.status_code == 200, sent.text
            record = publish_sends.PublishSends(app.state).latest_send("skill:my-skill")
            assert (record["hero"], record["media_submission_id"]) == (source, "b" * 32)
    assert scan["writes"] == 3


def test_a_database_made_before_the_check_counts_gains_them(tmp_path):
    import sqlite3

    old = sqlite3.connect(tmp_path / "publish_sends.db")
    old.execute("CREATE TABLE checks (id INTEGER PRIMARY KEY AUTOINCREMENT, location_id TEXT NOT NULL, version TEXT NOT NULL, ok INTEGER NOT NULL, at TEXT NOT NULL, summary TEXT NOT NULL)")
    old.execute("INSERT INTO checks (location_id, version, ok, at, summary) VALUES ('skill:x','1.0.0',1,'2025-10-09T08:55:00Z','clean')")
    old.commit()
    old.close()
    store = publish_sends.PublishSends(tmp_path)
    store.record_check(location_id="skill:x", version="1.1.0", ok=True, summary="clean", grade="A", files=2, bytes=9)
    newest, oldest = store.checks_for("skill:x")
    assert (newest["grade"], newest["files"], newest["bytes"]) == ("A", 2, 9)
    assert (oldest["grade"], oldest["files"], oldest["bytes"]) == ("", None, None)


def test_a_stored_check_keeps_its_digest_and_finding_paths_and_an_old_record_reads_as_before(tmp_path):
    import sqlite3

    old = sqlite3.connect(tmp_path / "publish_sends.db")
    old.execute("CREATE TABLE checks (id INTEGER PRIMARY KEY AUTOINCREMENT, location_id TEXT NOT NULL, version TEXT NOT NULL, ok INTEGER NOT NULL, at TEXT NOT NULL, summary TEXT NOT NULL, grade TEXT NOT NULL DEFAULT '', files INTEGER, bytes INTEGER)")
    old.execute("INSERT INTO checks (location_id, version, ok, at, summary) VALUES ('skill:x','1.0.0',0,'2025-10-09T08:55:00Z','secret_found')")
    old.commit()
    old.close()
    store = publish_sends.PublishSends(tmp_path)
    store.record_check(location_id="skill:x", version="1.1.0", ok=False, summary="secret_found", digest="d" * 64,
                       findings=[{"code": "secret_found", "path": "scripts/render.sh"}, {"code": "hidden_file", "path": ""}])
    store.record_check(location_id="skill:x", version="1.2.0", ok=True, summary="clean", digest="e" * 64)
    clean, refused, before = store.checks_for("skill:x")
    assert (clean["digest"], clean["findings"]) == ("e" * 64, [])
    assert (refused["digest"], refused["findings"]) == ("d" * 64, [{"code": "secret_found", "path": "scripts/render.sh"}])
    assert (before["digest"], before["findings"]) == ("", [])


def test_the_preview_route_stores_the_digest_it_handed_out_and_the_paths_it_refused(tmp_path, scan):
    folder = make_skill(tmp_path)
    (folder / ".env").write_text("x=1\n")
    scan["locs"] = [loc("skill", folder, "claude")]
    with app_for(tmp_path) as app:
        preview = app.client.post("/catalog/publish/preview", json={"location": "skill:my-skill", "version": "1.4.0"}).json()
        stored = app.client.get("/catalog/publish/items/skill:my-skill").json()["checks"][0]
    assert stored["digest"] == preview["digest"]
    assert stored["findings"] == [{"code": r["code"], "path": r["path"]} for r in preview["refusals"] if r["path"]] != []


def test_an_own_image_is_kept_by_sha_and_served_and_a_made_one_is_not(tmp_path, scan):
    import hashlib

    folder = make_skill(tmp_path)
    scan["locs"] = [loc("skill", folder, "claude")]
    image = base64.b64encode(PNG).decode()
    sha = hashlib.sha256(PNG).hexdigest()
    with app_for(tmp_path) as app:
        sign_in(app.state)
        preview_and_send(app, scan["locs"][0])
        app.client.post("/catalog/submissions/media", json={"kind": "skill", "name": "my-skill", "image_base64": image, "source": "made"})
        assert app.client.get("/catalog/publish/items/skill:my-skill").json()["sends"][0]["hero_sha"] == ""
        app.client.post("/catalog/submissions/media", json={"kind": "skill", "name": "my-skill", "image_base64": image, "source": "yours"})
        sends = app.client.get("/catalog/publish/items/skill:my-skill").json()["sends"]
        served = app.client.get(f"/catalog/publish/images/{sha}")
        missing = app.client.get(f"/catalog/publish/images/{'0' * 64}")
        bad = app.client.get("/catalog/publish/images/not-a-sha")
    assert sends[0]["hero_sha"] == sha and served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert missing.status_code == 404 and bad.status_code == 404
