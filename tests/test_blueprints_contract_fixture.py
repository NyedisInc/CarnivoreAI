
from __future__ import annotations

import json
import os
import random
import re
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

from tests.blueprints_helpers import client_for, make_repo, member, spec

# ruff: noqa: E402
from src.core.blueprints_ddl import REVERSAL_SQL_V35
from src.core.db import connect

FIXTURE = Path(__file__).parent / "fixtures" / "blueprints_api.json"
API = "/api/v1/blueprints"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
SESSION_ID = re.compile(r"ses_[0-9a-f]{8}")
FAKE_KEY = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


class Recorder:

    def __init__(self, client, tmp_path: Path) -> None:
        self.client = client
        self.out: List[Dict[str, Any]] = []
        self.names: Dict[str, str] = {os.path.realpath(tmp_path): "<tmp>", str(tmp_path): "<tmp>",
                                      FAKE_KEY: "<fake_github_token>"}

    def _name(self, value: Any, kind: str) -> None:
        if isinstance(value, str) and value not in self.names:
            count = sum(1 for v in self.names.values() if v.startswith(f"<{kind}_"))
            self.names[value] = f"<{kind}_{count + 1}>"

    def norm(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.norm(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.norm(v) for v in value]
        if isinstance(value, str):
            if STAMP.match(value):
                return "<timestamp>"
            for real in sorted(self.names, key=len, reverse=True):
                value = value.replace(real, self.names[real])
            return SESSION_ID.sub("<session_id>", value)
        return value

    def call(self, title: str, method: str, path: str, body: Any = None) -> Any:
        res = self.client.request(method, path, json=body)
        data = res.json()
        if isinstance(data, dict):
            self._name(data.get("blueprint_uuid"), "blueprint_uuid")
            layout = data.get("layout")
            if isinstance(layout, dict):
                self._name(layout.get("layout_uuid"), "layout_uuid")
        self.out.append({"title": title, "method": method, "path": self.norm(path),
                         "request": self.norm(body), "status": res.status_code,
                         "response": self.norm(data)})
        return data


def _examples(env, tmp_path: Path) -> List[Dict[str, Any]]:
    rec = Recorder(env.client, tmp_path)
    project = tmp_path / "proj"
    repo = make_repo(tmp_path / "app")
    team = spec("Team",
                member("api", project, model="anthropic/claude-opus-4",
                       opening_prompt="read the README and run the tests"),
                {"label": "web", "family": "codex", "folder": {
                    "mode": "worktree", "repo_path": str(repo), "base_branch": "master",
                    "branch": "feat/web"}})

    rec.call("list, empty install", "GET", API)
    uid = rec.call("create", "POST", API, {"spec": team})["blueprint_uuid"]
    rec.call("create, 409 name taken (case folded)", "POST", API,
             {"spec": {**team, "name": "TEAM"}})
    rec.call("create, 422 unknown field", "POST", API,
             {"spec": {**team, "sessions": [{**team["sessions"][0], "token": "x"}]}})
    rec.call("create, 400 secret in the spec", "POST", API, {"spec": spec("leak", member(
        "a", project, opening_prompt=f"use {FAKE_KEY} now"))})
    rec.call("get", "GET", f"{API}/{uid}")
    rec.call("get, 404", "GET", f"{API}/00000000-0000-0000-0000-000000000000")
    rec.call("replace", "PUT", f"{API}/{uid}", {"spec": team})
    rec.call("settings, default root", "GET", f"{API}/settings")
    rec.call("settings, set root", "PUT", f"{API}/settings", {"worktree_root": str(tmp_path / "wt")})
    rec.call("settings, 400 system root", "PUT", f"{API}/settings", {"worktree_root": "/"})
    rec.call("export", "POST", f"{API}/{uid}/export", {"project_path": str(project)})
    rec.call("export, 409 unknown project", "POST", f"{API}/{uid}/export",
             {"project_path": str(tmp_path)})
    rec.call("import under a new name", "POST", f"{API}/import",
             {"project_path": str(project), "name": "Team copy"})
    (project / ".carnivore" / "swarm.json").write_text('{"name": "broken",')
    rec.call("import, 409 malformed file", "POST", f"{API}/import", {"project_path": str(project)})
    (project / ".carnivore" / "swarm.json").unlink()
    rec.call("import, 404 no file", "POST", f"{API}/import", {"project_path": str(project)})
    rec.call("launch preview", "POST", f"{API}/{uid}/launch/preview", {})
    rec.call("launch preview, 400 unknown member", "POST", f"{API}/{uid}/launch/preview",
             {"members": [5]})
    launched = rec.call("launch (sequential; saved as a layout)", "POST", f"{API}/{uid}/launch",
                        {"cols": 120, "rows": 40})
    rec.call("launch, 409 the blueprint's layout already exists", "POST", f"{API}/{uid}/launch", {})
    rec.call("launch with overwrite_layout updates that layout in place", "POST",
             f"{API}/{uid}/launch", {"overwrite_layout": True})
    bad = spec("Mixed", member("ok one", project), member("ghost", project, family="nosuchwrapper"),
               member("fails", project), member("ok two", project))
    mixed = rec.call("create a blueprint with failing members", "POST", API, {"spec": bad})
    rec.call("launch, partial: failed members are outcomes, nothing rolled back", "POST",
             f"{API}/{mixed['blueprint_uuid']}/launch", {})
    layout_uuid = launched["layout"]["layout_uuid"]
    rec.call("from layout", "POST", f"{API}/from-layout/{layout_uuid}", {"name": "From layout"})
    rec.call("from layout, 404", "POST", f"{API}/from-layout/nope", {})
    rec.call("delete", "DELETE", f"{API}/{uid}")
    rec.call("delete, 404", "DELETE", f"{API}/{uid}")
    with closing(connect(env.db, create=False)) as conn:
        for statement in REVERSAL_SQL_V35:
            conn.execute(statement)
    rec.call("list, table unreadable: 200 unavailable, never an empty ok", "GET", API)
    rec.call("create, 503 datastore unavailable", "POST", API, {"spec": team})
    return rec.out


def test_the_fixture_matches_the_live_routes(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    env = client_for(tmp_path, monkeypatch, projects=(project,), fail_labels=("fails",))
    random.seed(20260926)
    examples = _examples(env, tmp_path)
    document = {
        "description": (
            "Request and response examples for every /api/v1/blueprints route (issue #759, "
            "Layouts slice E of #424). <tmp> is the test's own directory, <proj> under it a "
            "registered project, <tmp>/app a git repository on master; <blueprint_uuid_N>, "
            "<layout_uuid_N>, <session_id> and <timestamp> stand for generated values. "
            "Regenerated and checked by tests/test_blueprints_contract_fixture.py. "
            "Model: docs/blueprints.md."),
        "examples": examples,
    }
    if os.environ.get("BLUEPRINTS_FIXTURE_WRITE") == "1":
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(document, indent=2) + "\n")
    stored = json.loads(FIXTURE.read_text())
    assert len(stored["examples"]) == len(examples) >= 25
    for want, got in zip(stored["examples"], examples):
        assert got == want, want["title"]
    assert {e["status"] for e in examples} >= {200, 400, 404, 409, 422, 503}
