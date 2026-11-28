
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.plugin import plugin as script_plugin
from src.plugins.cli import main as cli_main
from src.plugins.cli.install_publish import parse_publish_target, run_publish
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401
from tests.python.plugins_v3.test_cli_install_publish_v3 import WAREZSMOKE_FIXTURE, live_app  # noqa: F401

SHA_A = "a" * 40


def test_parse_publish_target_handles_github_shorthand_and_local_folder(tmp_path: Path) -> None:
    kind, spec = parse_publish_target("harbor/myplug@v1.2.3")
    assert kind == "github"
    assert spec == {"pointer": "harbor/myplug@v1.2.3", "repo": "harbor/myplug", "tag": "v1.2.3"}

    kind2, spec2 = parse_publish_target(None, github="https://github.com/harbor/myplug.git", tag="v2.0.0")
    assert kind2 == "github"
    assert spec2 == {"pointer": "harbor/myplug@v2.0.0", "repo": "harbor/myplug", "tag": "v2.0.0"}

    local = tmp_path / "localplug"
    local.mkdir()
    kind3, spec3 = parse_publish_target(str(local))
    assert kind3 == "local" and spec3["path"] == local.resolve()

    with pytest.raises(ValueError, match="explicit @tag"):
        parse_publish_target("harbor/myplug")


def test_cli_publish_pure_github_pointer_end_to_end(live_app: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    w = live_app
    rc = run_publish(
        "harbor/pubplug@v0.1.0",
        commit_sha=SHA_A,
        subdir="plugins/pubplug",
        client=w.owner_cli,
        assume_yes=True,
        as_json=True,
    )
    assert rc == 0
    out_doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out_doc["status"] == "pending"

    post_reqs = [r for r in w.sent_hosted if r.method == "POST" and r.url.path.endswith("/submissions")]
    assert len(post_reqs) == 1
    sent_body = json.loads(post_reqs[0].content.decode("utf-8"))
    assert sent_body["source_type"] == "github"
    assert sent_body["pointer"] == "harbor/pubplug@v0.1.0"
    assert sent_body["repo"] == "harbor/pubplug"
    assert sent_body["tag"] == "v0.1.0"
    assert sent_body["commit_sha"] == SHA_A
    assert sent_body["subdir"] == "plugins/pubplug"
    assert sent_body["kind"] == "cplug"
    assert sent_body["name"] == "pubplug"
    assert sent_body["version"] == "0.1.0"
    assert "files" not in sent_body


def test_cli_publish_hybrid_local_folder_and_github_pointer(
    live_app: SimpleNamespace,  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    w = live_app
    plug = tmp_path / "myplug"
    assert cli_main(["new", "myplug", "--template", "python", "--dir", str(plug)]) == 0
    capsys.readouterr()

    rc = run_publish(
        str(plug),
        github="harbor/myplug@v0.1.0",
        commit_sha=SHA_A,
        client=w.owner_cli,
        assume_yes=True,
        as_json=True,
    )
    assert rc == 0
    post_reqs = [r for r in w.sent_hosted if r.method == "POST" and r.url.path.endswith("/submissions")]
    assert len(post_reqs) == 1
    sent_body = json.loads(post_reqs[0].content.decode("utf-8"))
    assert sent_body["source_type"] == "github"
    assert sent_body["pointer"] == "harbor/myplug@v0.1.0"
    assert sent_body["commit_sha"] == SHA_A
    assert any(f["path"] == "carnivore.toml" for f in sent_body["files"])


def test_catalog_submissions_route_supports_github_pointer(live_app: SimpleNamespace) -> None:  # noqa: F811
    w = live_app
    prev = w.tc.post(
        "/api/v1/cplug-owner/publish",
        json={"source_type": "github", "pointer": "harbor/myskill@v1.2.3", "kind": "skill", "name": "my-skill", "dry_run": True},
        headers=w.owner_headers,
    )
    assert prev.status_code == 200, prev.text
    digest = prev.json()["digest"]
    assert prev.json()["source_type"] == "github"

    resp = w.tc.post(
        "/api/v1/catalog/submissions",
        json={
            "location": "github:harbor/myskill@v1.2.3",
            "version": "1.2.3",
            "digest": digest,
            "source_type": "github",
            "pointer": "harbor/myskill@v1.2.3",
            "kind": "skill",
            "name": "my-skill",
        },
        headers=w.owner_headers,
    )
    assert resp.status_code == 200, resp.text
    post_reqs = [r for r in w.sent_hosted if r.method == "POST" and r.url.path.endswith("/submissions")]
    assert len(post_reqs) == 1
    sent_body = json.loads(post_reqs[0].content.decode("utf-8"))
    assert sent_body["source_type"] == "github"
    assert sent_body["kind"] == "skill"
    assert sent_body["name"] == "my-skill"


@pytest.mark.parametrize("bad_body", [
    {"source_type": "github", "pointer": "harbor/pubplug", "dry_run": True},
    {"source_type": "github", "pointer": "harbor/pubplug@v1.0.0", "commit_sha": "z" * 40, "dry_run": True},
    {"source_type": "github", "pointer": "git@github.com:harbor/pubplug@v1.0.0", "dry_run": True},
    {"source_type": "github", "pointer": "harbor/pubplug@v1.0.0", "subdir": "../etc", "dry_run": True},
    {"source_type": "github", "pointer": "harbor/pubplug@v1.0.0", "subdir": ".GIT/hooks", "dry_run": True},
    {"source_type": "github", "pointer": "harbor/pubplug@v1.0.0", "subdir": "-rf", "dry_run": True},
    {"source_type": "github", "pointer": "harbor/pubplug@v1.0.0", "subdir": "./-rf", "dry_run": True},
    {"source_type": "github", "pointer": "harbor/pubplug@v1.0.0", "subdir": "plugins\nfoo", "dry_run": True},
    {"source_type": "upload", "dry_run": True},
])
def test_owner_publish_refuses_invalid_github_or_missing_source(live_app: SimpleNamespace, bad_body: dict) -> None:  # noqa: F811
    resp = live_app.tc.post("/api/v1/cplug-owner/publish", json=bad_body, headers=live_app.owner_headers)
    assert resp.status_code == 422, resp.text


def test_scripts_plugin_publish_cli_subcommand_parses_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    live_app: SimpleNamespace,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(script_plugin, "CliHttpClient", lambda base_url=None: live_app.owner_cli)
    rc = script_plugin.main(["publish", "harbor/pubplug@v0.1.0", "-y", "--json"])
    assert rc == 0
    out_doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out_doc["status"] == "pending"

    rc_cli = cli_main(["publish", "--github", "harbor/pubplug@v0.1.0", "--commit-sha", SHA_A, "-y", "--json"])
    assert rc_cli in (0, 2)
