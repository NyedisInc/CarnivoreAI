
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from src.core.catalog.publish_prepare_kinds import own_cplug_locations
from src.cplugs.host import sideload, sideload_git
from src.cplugs.host.sideload import SideloadRefused
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401
from tests.python.cplugs.test_cplug_sideload import NAME, URL, world, write_plugin  # noqa: F401

GIT_URL = f"{URL}/git"
TOKEN = "ghp_SECRETtoken1234567890"

REFUSED = [
    "file:///tmp/repo", "ext::sh -c touch% /tmp/pwned", "fd::17", "/tmp/repo", "./repo", "../repo", "repo",
    "http://github.com/me/clock.git", "git://github.com/me/clock.git", "ftp://github.com/me/clock.git",
    f"https://me:{TOKEN}@github.com/me/clock.git", f"https://{TOKEN}@github.com/me/clock.git",
    f"ssh://git:{TOKEN}@github.com/me/clock.git", "ssh://-oProxyCommand=touch%20x/repo", "-uhack", "--upload-pack=touch x",
    "git@-oProxyCommand=x:repo", "https://github.com/", "https://github.com/me/clock.git\n", "", None, 7,
]
ALLOWED = ["https://github.com/me/clock.git", "ssh://git@github.com/me/clock.git", "git@github.com:me/clock.git",
           "ssh://github.com:2222/me/clock"]


@pytest.mark.parametrize("url", REFUSED)
def test_every_other_scheme_and_any_credential_is_refused(url):
    with pytest.raises(SideloadRefused) as caught:
        sideload_git.check_url(url)
    assert caught.value.code == "git_url_refused" and caught.value.status == 422
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("url", ALLOWED)
def test_https_and_ssh_pass(url):
    assert sideload_git.check_url(url) == url


@pytest.mark.parametrize("ref", ["-uhack", "a..b", "a b", "x@{1}", "main.lock", "dir/", ".hidden", "a//b"])
def test_a_bad_ref_is_refused(ref):
    with pytest.raises(SideloadRefused) as caught:
        sideload_git.check_ref(ref)
    assert caught.value.code == "ref_invalid"


@pytest.mark.parametrize("subdir", ["../x", "/abs", "a/../../x", ".git/hooks", "a\\b"])
def test_a_subfolder_outside_the_checkout_is_refused(subdir):
    with pytest.raises(SideloadRefused) as caught:
        sideload_git.check_subdir(subdir)
    assert caught.value.code == "subdir_invalid"


def test_the_route_refuses_a_credential_url_and_never_logs_it(world, capsys):
    w = world
    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).status_code == 200
    r = w.client.post(GIT_URL, json={"url": f"https://me:{TOKEN}@github.com/me/clock.git"}, headers=w.owner)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "git_url_refused", r.text
    assert TOKEN not in r.text and TOKEN not in "".join(capsys.readouterr())
    assert not sideload_git.checkouts_root(w.state).exists()


def test_the_route_is_off_with_the_switch_and_fenced_from_api_keys(world):
    w = world
    r = w.client.post(GIT_URL, json={"url": "https://github.com/me/clock.git"}, headers=w.owner)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sideload_off"
    r = w.client.post(GIT_URL, json={"url": "https://github.com/me/clock.git"}, headers=w.key)
    assert r.status_code == 403 and r.json()["detail"] == {"reason": "api_key_forbidden"}


def _git(*args, cwd=None) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    from src.core.dev_tools import git_guard

    monkeypatch.setattr(git_guard, "git_available", lambda: True)
    monkeypatch.setattr(sideload_git, "check_url", lambda url: url)
    monkeypatch.setattr(sideload_git, "ALLOWED_PROTOCOLS", ("https", "ssh", "file"))
    bare, work = tmp_path / "remote.git", tmp_path / "work"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(work))
    write_plugin(work / "plugin")
    (work / "README.md").write_text("not part of the plugin\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "first", cwd=work)
    _git("remote", "add", "origin", str(bare), cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    return {"url": f"file://{bare}", "work": work}


def test_a_git_sideload_installs_resyncs_a_new_commit_is_found_by_publish_and_is_removed_with_its_checkout(world, repo):
    w = world
    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).status_code == 200

    first = w.client.post(GIT_URL, json={"url": repo["url"], "subdir": "plugin"}, headers=w.owner)
    assert first.status_code == 200, first.text
    body = first.json()
    head = _git("rev-parse", "HEAD", cwd=repo["work"])
    assert body["id"] == NAME and body["unverified"] is True and body["git"]["commit"] == head
    checkout = sideload_git.checkout_of(w.state, NAME)
    root = sideload.code_root_of(w.state, NAME)
    assert (root / "main.py").read_text() == "print('tick')\n" and not (root / "README.md").exists()
    assert not list(sideload_git.checkouts_root(w.state).glob(".incoming-*"))

    listed = {i["id"]: i for i in w.client.get(URL, headers=w.owner).json()["items"]}
    assert listed[NAME]["git"] == {**body["git"], "url": repo["url"], "ref": None, "subdir": "plugin"}
    assert listed[NAME]["source"] == str(checkout / "plugin")

    locations = own_cplug_locations(sideload.items(w.state))
    assert [loc["path"] for loc in locations if loc["name"] == NAME] == [str(checkout / "plugin")]

    (repo["work"] / "plugin" / "main.py").write_text("print('edited')\n")
    _git("commit", "-q", "-am", "edit", cwd=repo["work"])
    _git("push", "-q", "origin", "main", cwd=repo["work"])
    again = w.client.post(GIT_URL, json={"url": repo["url"], "ref": "main", "subdir": "plugin", "name": NAME}, headers=w.owner)
    assert again.status_code == 200, again.text
    assert again.json()["changed"] == ["main.py"] and again.json()["git"]["commit"] == _git("rev-parse", "HEAD", cwd=repo["work"])
    assert (root / "main.py").read_text() == "print('edited')\n"
    assert json.loads((w.state / "cplugs" / "sideload-git.json").read_text())[NAME]["ref"] == "main"

    other = repo["work"].parent / "folder"
    write_plugin(other)
    assert w.client.post(URL, json={"path": str(other)}, headers=w.owner).status_code == 200
    assert {i["id"]: i for i in w.client.get(URL, headers=w.owner).json()["items"]}[NAME]["git"] is None
    assert w.client.post(GIT_URL, json={"url": repo["url"], "subdir": "plugin", "name": NAME}, headers=w.owner).status_code == 200

    r = w.client.delete(f"{URL}?name={NAME}", headers=w.owner)
    assert r.status_code == 200 and not checkout.exists() and not root.exists()
    assert NAME not in sideload_git.records(w.state)


def test_a_failed_first_sync_leaves_no_checkout(world, repo):
    w = world
    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).status_code == 200
    r = w.client.post(GIT_URL, json={"url": repo["url"], "subdir": "missing", "name": NAME}, headers=w.owner)
    assert r.status_code == 422, r.text
    r = w.client.post(GIT_URL, json={"url": repo["url"], "ref": "no-such-branch"}, headers=w.owner)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "git_failed", r.text
    root = sideload_git.checkouts_root(w.state)
    assert not root.exists() or list(root.iterdir()) == []
