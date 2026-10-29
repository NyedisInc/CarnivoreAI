
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cpr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cpr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api import catalog_publish_routes
from src.core.catalog.token_store import CatalogSession, open_token_store
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

MANIFEST = """---
name: my-skill
description: use when you need a thing done well and want it stated plainly
---
# my skill

do the thing.
"""

LOC = "root1:my-skill"
SUBMITTED = {
    "submission_id": "abc123",
    "status": "pending",
    "item_id": "bob/my-skill",
    "new_version": False,
    "version": "1.0.0",
}


def make_skill(tmp_path: Path, extra: dict | None = None) -> Path:
    folder = tmp_path / "skills" / "my-skill"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(MANIFEST)
    for name, text in (extra or {}).items():
        (folder / name).write_text(text)
    return folder


def location(folder: Path, **over) -> dict:
    loc = {
        "location_id": LOC, "name": "my-skill", "harness": "claude",
        "scope": "personal", "path": str(folder), "description": "d",
        "description_tokens_est": 42, "is_symlink": False, "read_only": False,
        "plugin": None, "managed": None,
    }
    loc.update(over)
    return loc


def sign_in(state: Path) -> None:
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(CatalogSession(
            login="bob", access_token="HELD-ACCESS-SECRET", access_expires_at=now + 3600,
            refresh_token="HELD-REFRESH-SECRET", refresh_expires_at=now + 86400,
        ))


@pytest.fixture
def scan(monkeypatch):
    box: dict = {"locs": []}

    async def own(_request):
        return list(box["locs"])

    monkeypatch.setattr(catalog_publish_routes, "_own_locations", own)
    return box


def host(routes=None):
    return route_responder(routes or {"/submissions": (201, SUBMITTED)})


def preview(client, version="1.0.0"):
    return client.post("/catalog/publish/preview", json={"location": LOC, "version": version})


class TestTheSendIsTheConsentTheUserRead:

    def test_a_folder_edited_after_the_preview_is_refused_folder_changed(self, tmp_path, scan):
        folder = make_skill(tmp_path)
        scan["locs"] = [location(folder)]
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            sign_in(app.state)
            shown = preview(app.client)
            assert shown.status_code == 200, shown.text
            digest = shown.json()["digest"]
            (folder / "SKILL.md").write_text(MANIFEST + "\nsneaked in after the preview\n")
            answer = app.client.post(
                "/catalog/submissions", json={"location": LOC, "version": "1.0.0", "digest": digest}
            )
            assert answer.status_code == 409
            assert answer.json()["detail"]["code"] == "folder_changed"
            assert app.sent == [], "nothing may leave the Mac for a changed folder"

    def test_an_unchanged_folder_is_forwarded_with_the_held_token_and_its_exact_bytes(
        self, tmp_path, scan
    ):
        folder = make_skill(tmp_path, {"notes.md": "hello"})
        scan["locs"] = [location(folder)]
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            sign_in(app.state)
            digest = preview(app.client).json()["digest"]
            answer = app.client.post(
                "/catalog/submissions", json={"location": LOC, "version": "1.0.0", "digest": digest}
            )
            assert answer.status_code == 200
            assert answer.json()["submission_id"] == "abc123"
            (request,) = app.sent
            assert request.url.path == "/api/v1/submissions"
            assert request.headers["authorization"] == "Bearer HELD-ACCESS-SECRET"
            import json

            sent = json.loads(request.content)
            assert sent["name"] == "my-skill" and sent["version"] == "1.0.0"
            files = {f["path"]: base64.b64decode(f["content_base64"]) for f in sent["files"]}
            assert files == {"SKILL.md": MANIFEST.encode(), "notes.md": b"hello"}
            assert "HELD-ACCESS-SECRET" not in answer.text

    def test_a_new_version_changes_the_digest(self, tmp_path, scan):
        folder = make_skill(tmp_path)
        scan["locs"] = [location(folder)]
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            assert preview(app.client, "1.0.0").json()["digest"] != preview(app.client, "1.1.0").json()["digest"]


class TestPreflight:

    def test_scripts_are_refused_and_the_send_stops_before_the_host(self, tmp_path, scan):
        folder = make_skill(tmp_path)
        (folder / "scripts").mkdir()
        (folder / "scripts" / "run.sh").write_text("echo hi")
        scan["locs"] = [location(folder)]
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            sign_in(app.state)
            shown = preview(app.client).json()
            assert shown["can_send"] is False
            assert "scripts_not_supported" in [r["code"] for r in shown["refusals"]]
            sent = app.client.post(
                "/catalog/submissions", json={"location": LOC, "version": "1.0.0", "digest": shown["digest"]}
            )
            assert sent.status_code == 409 and sent.json()["detail"]["code"] == "folder_refused"
            assert app.sent == []

    def test_lint_cost_and_compat_are_reported_and_nothing_is_sent(self, tmp_path, scan):
        folder = make_skill(tmp_path)
        scan["locs"] = [location(folder)]
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            shown = preview(app.client).json()
            assert shown["can_send"] is True
            assert shown["lint"]["grade"] in {"A", "B", "C", "D", "F"}
            assert shown["cost"]["description_tokens_est"] == 42
            assert shown["compat"]["harness"] == "claude"
            assert app.sent == []

    def test_an_id_the_scan_does_not_list_is_404_and_a_path_is_never_accepted(self, tmp_path, scan):
        scan["locs"] = []
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            for wanted in (LOC, str(tmp_path)):
                answer = app.client.post("/catalog/publish/preview", json={"location": wanted})
                assert answer.status_code == 404
                assert answer.json()["detail"]["code"] == "unknown_location"


class TestAccountAndSubmissionProxies:

    def test_claim_and_reads_carry_the_bearer(self, tmp_path):
        responder = route_responder({
            "/register": (200, {"handle": "bob", "handle_status": "pending", "registered": True}),
            "/me": (200, {"provider": "email", "login": "", "handle": "", "handle_status": "", "email": "x@y.z", "registered": False, "terms_version": "2026-10-01", "terms_url": "https://x/t", "notify_replies": False}),
            "/submissions/mine": (200, {"submissions": []}),
        })
        with hosted_proxy_app(tmp_path, responder=responder, include_aggregator=True) as app:
            sign_in(app.state)
            account = app.client.get("/catalog/handle").json()
            assert account["can_claim"] is True and "email" not in account
            assert account["registered"] is False and account["terms_version"] == "2026-10-01"
            assert account["notify_replies"] is False
            registered = app.client.post(
                "/catalog/account/register",
                json={"terms_version": "2026-10-01", "age_16_plus": True, "handle": "bob"},
            ).json()
            assert registered["handle_status"] == "pending"
            assert json.loads(app.sent[-1].content) == {
                "terms_version": "2026-10-01", "age_16_plus": True, "handle": "bob"}
            assert app.client.get("/catalog/submissions/mine").json() == {"submissions": []}
            app.client.get("/catalog/submissions/" + "ab" * 16 + "/report")
            assert app.sent[-1].url.path.endswith("/submissions/" + "ab" * 16 + "/report")
            sent_before = len(app.sent)
            assert app.client.get("/catalog/submissions/not-an-id/report").status_code == 404
            assert len(app.sent) == sent_before
            assert {r.headers["authorization"] for r in app.sent} == {"Bearer HELD-ACCESS-SECRET"}

    def test_handle_change_relays_the_host_answer_and_refusal(self, tmp_path):
        responder = route_responder({"/account/handle": (409, {"code": "handle_locked", "detail": "permanent"})})
        with hosted_proxy_app(tmp_path, responder=responder, include_aggregator=True) as app:
            sign_in(app.state)
            assert app.client.post("/catalog/account/handle", json={"handle": ""}).status_code == 422
            answer = app.client.post("/catalog/account/handle", json={"handle": "new-name"})
            assert answer.status_code == 409 and answer.json()["detail"]["code"] == "handle_locked"
            assert json.loads(app.sent[-1].content) == {"handle": "new-name"}
            assert app.sent[-1].headers["authorization"] == "Bearer HELD-ACCESS-SECRET"

    def test_delete_and_export_relay_and_delete_forgets_the_local_sign_in(self, tmp_path):
        responder = route_responder({
            "/account/delete": (200, {"deleted": True, "deleting": False}),
            "/account/export": (200, {"format": "carnivore-account-export"}),
        })
        with hosted_proxy_app(tmp_path, responder=responder, include_aggregator=True) as app:
            sign_in(app.state)
            assert app.client.get("/catalog/account/export").json()["format"] == "carnivore-account-export"
            assert app.client.post("/catalog/account/delete", json={"confirm": ""}).status_code == 422
            done = app.client.post("/catalog/account/delete", json={"confirm": "bob"})
            assert done.json() == {"deleted": True, "deleting": False}
            assert json.loads(app.sent[-1].content) == {"confirm": "bob"}
            assert app.sent[-1].headers["authorization"] == "Bearer HELD-ACCESS-SECRET"
            assert app.client.get("/catalog/account/export").status_code == 403

    def test_signed_out_is_403_and_nothing_is_sent(self, tmp_path):
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            assert app.client.get("/catalog/submissions/mine").status_code == 403
            assert app.sent == []


class TestOwnSkillsFilter:

    def test_only_unmanaged_personal_writable_non_plugin_skills(self, monkeypatch, tmp_path):
        def loc(name, **over):
            return location(Path("/x"), location_id=f"r:{name}", name=name, **over)

        groups = [{"locations": [
            loc("mine"),
            loc("catalog-installed", managed={"source": "ledger"}),
            loc("from-plugin", plugin="p"),
            loc("bundled", read_only=True),
            loc("proj", scope="project"),
        ]}]

        async def index_get():
            return None

        monkeypatch.setattr(catalog_publish_routes, "_profiles", lambda _home: ["p"])
        monkeypatch.setattr(
            catalog_publish_routes, "_inventory_now", lambda *_a: {"skills": groups}
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            services=SimpleNamespace(
                catalog=SimpleNamespace(index_cache=SimpleNamespace(get=index_get)),
                settings_reader=SimpleNamespace(state_dir=lambda: tmp_path),
            )
        )))
        import asyncio

        got = asyncio.run(catalog_publish_routes._own_locations(request))
        assert [g["name"] for g in got] == ["mine"]


class TestNothingSecretOrLinkedLeaves:

    @staticmethod
    def _fake_keys():
        anthropic = "sk-ant-" + "api03-" + "aZ9kQ2mX7vB4nL8cR1tY6wE3uH5jP0dF" * 2
        github = "gh" + "p_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bD2fG4hJ6"
        return anthropic, github

    def test_a_env_and_a_git_config_are_refused_at_preview_and_at_send(self, tmp_path, scan):
        anthropic, github = self._fake_keys()
        folder = make_skill(tmp_path)
        (folder / ".env").write_text(f"ANTHROPIC_API_KEY={anthropic}\n")
        (folder / ".git").mkdir()
        (folder / ".git" / "config").write_text(f"[remote]\n\turl = https://{github}@github.com/x/y\n")
        (folder / "notes.md").write_text(f"my token is {github}\n")
        scan["locs"] = [location(folder)]
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            sign_in(app.state)
            shown = preview(app.client)
            assert shown.status_code == 200, shown.text
            body = shown.json()
            assert body["can_send"] is False
            refused = {r["path"]: r["detail"] for r in body["refusals"] if r["path"]}
            assert ".env" in refused and ".git/config" in refused
            assert "github_token" in refused["notes.md"]
            for key in (anthropic, github):
                assert key not in shown.text
            sent = app.client.post(
                "/catalog/submissions",
                json={"location": LOC, "version": "1.0.0", "digest": body["digest"]},
            )
            assert sent.status_code == 409
            assert sent.json()["detail"]["code"] == "folder_refused"
            for key in (anthropic, github):
                assert key not in sent.text
            assert app.sent == []

    def test_a_hardlinked_file_is_refused_and_a_clean_folder_still_sends(self, tmp_path, scan):
        folder = make_skill(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("SENTINEL-HARDLINK-TARGET")
        os.link(outside, folder / "linked.md")
        scan["locs"] = [location(folder)]
        with hosted_proxy_app(tmp_path, responder=host(), include_aggregator=True) as app:
            sign_in(app.state)
            shown = preview(app.client)
            body = shown.json()
            assert body["can_send"] is False
            assert "linked.md" in [r["path"] for r in body["refusals"]]
            assert "SENTINEL-HARDLINK-TARGET" not in shown.text
            (folder / "linked.md").unlink()
            clean = preview(app.client).json()
            assert clean["can_send"] is True
