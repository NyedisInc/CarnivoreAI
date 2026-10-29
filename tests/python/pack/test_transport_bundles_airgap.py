
from __future__ import annotations

import asyncio
import os
import stat
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_transport_routes as routes  # noqa: E402
from src.api import peer_auth  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants  # noqa: E402
from src.core.pack.identity import replicas  # noqa: E402
from src.core.pack.transport import blobs, bundles, gh_helper, github_account, ladder, publish, sync, tarball  # noqa: E402

TOKEN = "g" + "hp_SENTINEL0123456789abcdefghijklmnopqrs"


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)
    return done.stdout.strip()


class Machine:

    def __init__(self, tmp_path: Path, name: str, install_id: str) -> None:
        self.name, self.install_id = name, install_id
        self.state = tmp_path / f"{name}-state"
        self.state.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        self.repo = tmp_path / f"{name}-work"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/api/v1")
        self.client = TestClient(self.app)

    def conn(self):
        return connect(db_path_for(self.state), create=False)

    def open_db(self):
        return self.conn()

    def grant_to(self, sender_install_id: str):
        with closing(self.conn()) as conn:
            key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([7]) * 32))
            grants.create_grant(conn, peer_install_id=sender_install_id, public_key=key, label=sender_install_id, scopes=("replica",))
            return next(g for g in grants.list_grants(conn) if g.peer_install_id == sender_install_id)


def commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def pair(monkeypatch, tmp_path):
    a, b = Machine(tmp_path, "a", "iid-a"), Machine(tmp_path, "b", "iid-b")
    with closing(a.conn()) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, 'ledgerbot', 'user', 't', 't')",
                     (str(a.repo), str(a.repo)))
        conn.commit()
        uid = conn.execute("SELECT uid FROM projects").fetchone()[0]
        replicas.record_replica(conn, uid, "iid-b", str(b.repo), "carried")
    with closing(b.conn()) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, uid, pack_state, home_install_id, created_at, updated_at) "
                     "VALUES (?, ?, 'ledgerbot', 'user', ?, 'replica', 'iid-a', 't', 't')", (str(b.repo), str(b.repo), uid))
        conn.commit()
    principals = {("iid-a", "iid-b"): peer_auth.Principal("peer", b.grant_to("iid-a")),
                  ("iid-b", "iid-a"): peer_auth.Principal("peer", a.grant_to("iid-b"))}

    def link(sender: Machine, receiver: Machine) -> blobs.Request:
        receiver.app.dependency_overrides[routes._require_replica] = lambda: principals[(sender.install_id, receiver.install_id)]

        async def request(method: str, path: str, *, content: Any = None, headers: Any = None, json: Any = None):
            monkeypatch.setattr(type(settings), "get_state_dir", lambda self, s=receiver.state: s, raising=True)
            reply = receiver.client.request(method, "/api/v1" + path, content=content, headers=headers, json=json)
            return reply.status_code, reply.json()

        return request

    return a, b, uid, link


def carry(sender: Machine, receiver: Machine, uid: str, link, *, air_gap: bool = False, full: bool = False) -> Dict[str, Any]:
    return asyncio.run(sync.carry_bundle(repo=str(sender.repo), project_uid=uid, peer_install_id=receiver.install_id,
                                         request=link(sender, receiver), open_db=sender.open_db,
                                         outbox=str(sender.state / "pack" / "outbox"), air_gap=air_gap, full=full))


def refs(repo: Path, prefix: str) -> Dict[str, str]:
    out = git(repo, "for-each-ref", "--format=%(refname) %(objectname)", prefix)
    return dict(line.split(" ") for line in out.splitlines())


def test_bundle_round_trip_with_no_remote_and_the_air_gap_argv_rule(pair, monkeypatch) -> None:
    a, b, uid, link = pair
    git(a.repo, "remote", "add", "origin", "https://github.com/acme/ledgerbot.git")
    with closing(a.conn()) as conn:
        conn.execute("UPDATE projects SET air_gap = 1")
        conn.commit()
    argvs: List[List[str]] = []
    real_run = subprocess.run

    def recording_run(argv, *args, **kwargs):
        argvs.append([str(x) for x in argv])
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(ladder.subprocess, "run", recording_run)

    c1 = commit(a.repo, "one.txt", "1")
    assert carry(a, b, uid, link, air_gap=True) == {"sent": True, "refs": 1}
    assert refs(b.repo, "refs/carnivore/iid-a") == {"refs/carnivore/iid-a/heads/main": c1}
    assert git(b.repo, "branch", "--list") == "* main" and git(b.repo, "rev-parse", "main") == c1
    assert git(b.repo, "remote") == ""
    assert carry(a, b, uid, link, air_gap=True)["sent"] is False

    c2 = commit(a.repo, "two.txt", "2")
    assert carry(a, b, uid, link, air_gap=True)["sent"] is True
    assert refs(b.repo, "refs/carnivore/iid-a")["refs/carnivore/iid-a/heads/main"] == c2
    assert git(b.repo, "rev-parse", "main") == c1
    assert git(b.repo, "cat-file", "-t", c1) == "commit"
    assert list((b.state / "pack" / "inbox").glob("*")) == []

    git(b.repo, "checkout", "-q", "-b", "feature", "refs/carnivore/iid-a/heads/main")
    d1 = commit(b.repo, "feat.txt", "f")
    with closing(b.conn()) as conn:
        conn.execute("UPDATE projects SET air_gap = 1")
        conn.commit()
    assert carry(b, a, uid, link, air_gap=True)["sent"] is True
    assert refs(a.repo, "refs/carnivore/iid-b")["refs/carnivore/iid-b/heads/feature"] == d1
    assert git(a.repo, "rev-parse", "main") == c2 and git(a.repo, "branch", "--list") == "* main"
    with closing(a.conn()) as conn:
        assert bundles.read_tips(conn, uid, "iid-b") == [c2]

    assert argvs, "the recorder saw no process: the test looked at nothing"
    assert [v for v in argvs if any("github.com" in x.lower() for x in v) or Path(v[0]).name == "gh"] == []
    before = len(argvs)
    for bad in (["git", "-C", str(a.repo), "fetch", "https://github.com/acme/ledgerbot.git"], ["git", "-C", str(a.repo), "push"],
                ["git", "-C", str(a.repo), "pull"], ["git", "-C", str(a.repo), "ls-remote"], ["git", "-C", str(a.repo), "fetch", "origin"],
                ["gh", "auth", "status"], ["/opt/homebrew/bin/gh", "api", "user"]):
        with pytest.raises(ladder.AirGapViolation):
            ladder.run(bad, air_gap=True)
    with pytest.raises(ladder.AirGapViolation):
        ladder.clone_from_origin("git@github.com:acme/ledgerbot.git", str(a.state / "clone"), gh_helper.config_pairs("acme", "/usr/bin/gh"), air_gap=True)
    with pytest.raises(ladder.AirGapViolation):
        gh_helper.install(str(a.repo), "acme", air_gap=True)
    with pytest.raises(publish.PublishRefused) as refused:
        publish.publish(str(a.repo), name="ledgerbot", owner="acme", account="acme", air_gap=True)
    assert refused.value.code == "air_gap"
    assert len(argvs) == before, "a refused call started a process"
    res = github_account.resolve(air_gap=True, project_account="acme", company_account="acme", origin_url="https://github.com/acme/x",
                                 logged_in=lambda: pytest.fail("air-gap asked gh who is logged in"))
    assert res.account is None and res.source == "air_gap"
    assert ladder.choose_rung(purpose="span", air_gap=True, has_git=True, has_remote=True).rung == "carried"
    assert ladder.choose_rung(purpose="move", air_gap=True, has_git=False, has_remote=False).rung == "tar"
    assert ladder.choose_rung(purpose="span", air_gap=False, has_git=True, has_remote=True).rung == "git"
    with pytest.raises(ladder.RungUnavailable):
        ladder.choose_rung(purpose="span", air_gap=False, has_git=False, has_remote=False)

    monkeypatch.setattr(ladder.subprocess, "run", lambda argv, *a_, **k_: subprocess.CompletedProcess(argv, 0, b"", b""))
    seen: List[List[str]] = []
    monkeypatch.setattr(ladder, "check_argv", lambda argv, air_gap: seen.append(list(argv)))
    ladder.run(["git", "clone", "https://github.com/acme/ledgerbot.git"], air_gap=False)
    assert any("github.com" in x for x in seen[0])


def test_the_credential_helper_holds_the_account_name_and_never_the_token(monkeypatch, tmp_path) -> None:
    bin_dir, log = tmp_path / "bin", tmp_path / "gh.log"
    bin_dir.mkdir()
    fake = bin_dir / "gh"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nif [ "$1 $2" = "auth token" ]; then echo {TOKEN}; fi\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "replica"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    argvs: List[List[str]] = []
    real_run = subprocess.run
    monkeypatch.setattr(ladder.subprocess, "run", lambda argv, *a, **k: (argvs.append([str(x) for x in argv]), real_run(argv, *a, **k))[1])

    assert gh_helper.install(str(repo), "acme", air_gap=False) == [gh_helper.HELPER_KEY, gh_helper.INSTEAD_KEY]
    config = (repo / ".git" / "config").read_text()
    assert "acme" in config and str(fake) in config and TOKEN not in config
    helpers = subprocess.run(["git", "-C", str(repo), "config", "--local", "--get-all", gh_helper.HELPER_KEY], capture_output=True, text=True).stdout.split("\n")
    assert helpers[0] == "" and helpers[1].startswith("!f()")

    asked = subprocess.run(["git", "-C", str(repo), "credential", "fill"], input="protocol=https\nhost=github.com\n\n", text=True,
                           capture_output=True, check=True)
    assert "username=acme" in asked.stdout and f"password={TOKEN}" in asked.stdout
    assert github_account.token_env("acme") == {"GH_TOKEN": TOKEN}
    assert not [v for v in argvs if any(TOKEN in x for x in v)], "the token appeared in an argv Carnivore started"
    assert TOKEN not in log.read_text() and "auth token --hostname github.com --user acme" in log.read_text()
    assert subprocess.run(["git", "-C", str(repo), "config", "--local", "--list"], capture_output=True, text=True).stdout.count(TOKEN) == 0
    for bad in ("x; rm -rf /", "a b", "$(id)", "", "-x" * 30, "a" * 40):
        with pytest.raises(github_account.AccountError):
            gh_helper.helper_script(bad, str(fake))
    assert github_account.resolve(air_gap=False, project_account="p", company_account="c", origin_url=None).source == "project"
    assert github_account.resolve(air_gap=False, project_account=None, company_account="c", origin_url=None).source == "company"
    owner = github_account.resolve(air_gap=False, project_account=None, company_account=None,
                                   origin_url="git@github.com:NyedisInc/x.git", logged_in=lambda: ["acme", "nyedisinc"])
    assert (owner.account, owner.source) == ("nyedisinc", "remote_owner")
    card = github_account.resolve(air_gap=False, project_account=None, company_account=None, origin_url="https://github.com/zzz/x", logged_in=lambda: ["a"])
    assert card.needs_card


def test_tarball_keeps_uncommitted_work_and_drops_dependency_trees(tmp_path) -> None:
    src = tmp_path / "proj"
    (src / "node_modules" / "left-pad").mkdir(parents=True)
    (src / "node_modules" / "left-pad" / "i.js").write_text("x")
    (src / "pkg" / "__pycache__").mkdir(parents=True)
    (src / "pkg" / "__pycache__" / "m.pyc").write_text("x")
    (src / "dist").mkdir()
    (src / "dist" / "out.js").write_text("x")
    (src / "src").mkdir()
    (src / "src" / "dist").mkdir()
    (src / "src" / "dist" / "keep.txt").write_text("nested dist stays")
    (src / "draft.txt").write_text("uncommitted, never in git")
    (src / "package-lock.json").write_text("{}")
    archive = tmp_path / "p.tar.zst"
    assert tarball.make_tarball(str(src), str(archive)) > 0
    names = tarball.list_members(str(archive))
    assert "./draft.txt" in names and "./src/dist/keep.txt" in names
    assert not [n for n in names if "node_modules" in n or "__pycache__" in n or n.startswith("./dist")]
    dest = tmp_path / "out"
    assert tarball.extract_tarball(str(archive), str(dest)) == len(names)
    assert (dest / "draft.txt").read_text() == "uncommitted, never in git"
    with pytest.raises(tarball.TarballError):
        tarball.extract_tarball(str(archive), str(dest))
    assert tarball.install_commands(str(src)) == [["npm", "ci"]]
    assert tarball.unsafe_member("../x") and tarball.unsafe_member("/etc/passwd") and not tarball.unsafe_member("./a/b")


def test_blob_inbox_resumes_and_refuses_a_wrong_offset_or_hash(tmp_path) -> None:
    import hashlib

    inbox = blobs.Inbox(tmp_path / "inbox")
    blob = "b-0123456789abcdef"
    data = b"hello world" * 10
    sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    assert inbox.put(blob, 0, data[:40], sha(data[:40])) == 40
    with pytest.raises(blobs.BlobError) as skew:
        inbox.put(blob, 10, data[40:], sha(data[40:]))
    assert skew.value.code == "offset_mismatch" and skew.value.received == 40
    with pytest.raises(blobs.BlobError) as bad:
        inbox.put(blob, 40, data[40:], sha(b"other"))
    assert bad.value.code == "bad_chunk_hash"
    inbox.put(blob, 40, data[40:], sha(data[40:]))
    with pytest.raises(blobs.BlobError) as wrong:
        inbox.seal(blob, len(data), sha(b"x"), "bundle")
    assert wrong.value.code == "hash_mismatch" and inbox.status(blob) == {"received": 0, "sealed": False}
    inbox.put(blob, 0, data, sha(data))
    path = inbox.seal(blob, len(data), sha(data), "bundle")
    assert oct(path.stat().st_mode & 0o777) == "0o600" and inbox.status(blob)["sealed"] is True
    for evil in ("../x", "a/b", "", "b-1"):
        with pytest.raises(blobs.BlobError):
            inbox.status(evil)


def test_a_bundle_applies_into_a_fresh_replica_folder_that_is_not_a_repo_yet(tmp_path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    git(src, "init", "-q", "-b", "main")
    commit(src, "a.txt", "one")
    bundle = tmp_path / "x.bundle"
    assert bundles.make_bundle(str(src), str(bundle), known_tips=[], air_gap=True)
    assert bundles.apply_bundle(str(dst), str(bundle), "iid-a", air_gap=True) == 1
    assert refs(dst, "refs/carnivore/iid-a/heads/")
    assert git(dst, "remote").strip() == ""
