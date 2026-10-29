
from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.api.auth import require_auth
from src.config.uploads import UploadsConfig
from src.core.mcp import protocol, write_tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.huddle import board_port
from src.cplugs.reviewboard import scan, scratch
from src.cplugs.reviewboard.errors import TooLarge
from src.cplugs.sdk import ToolError, signed_links, uploads as sdk_uploads
from src.cplugs.sdk.local_files import read_local_file
from tests.python.cplugs.reviewboard.harness import BASE, PANE, Env, task_manager_on, task_manager_store, make_env

TOKEN = AgentCaller("mcp-token:7", "mcp-token:7", "mcp-token:7", token_name="phone", scope="write")
APPROVED_TOKEN = AgentCaller("mcp-token:7", "mcp-token:7", "mcp-token:7")
PAGE = "<!doctype html><html><head><title>p</title></head><body><img src=\"files/a.png\"><img src='./files/b.png'>" \
       "<div style=\"background:url(files/a.png)\"></div><img src=\"files/nope.png\"></body></html>"


def png(color=(200, 30, 30), size=(4, 4)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture(autouse=True)
def signing(monkeypatch):
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))


@pytest.fixture
def caps(monkeypatch) -> UploadsConfig:
    cfg = UploadsConfig()
    monkeypatch.setattr(sdk_uploads, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(uploads=cfg)))
    return cfg


@pytest.fixture
def env(tmp_path: Path, monkeypatch, caps) -> Env:
    made = make_env(tmp_path)
    task_manager_on(made, monkeypatch)
    yield made
    board_port.unregister()


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


def post(env: Env, caller: AgentCaller = PANE, **over):
    args = {"name": "phone", "html": PAGE, "files": [{"name": "a.png", "content_base64": b64(png())},
                                                     {"name": "b.png", "content_base64": b64(png((10, 200, 10)))}], **over}
    return env.call("task_manager_scratch_post", args, caller)


def served(client: TestClient, slug: str, revision: str = "r1") -> str:
    url = client.post(f"{BASE}/boards/{slug}/revisions/{revision}/ticket", json={}).json()["url"]
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.text


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}



def test_a_multi_file_post_is_served_with_each_file_inlined(env: Env, client):
    ok, answer = post(env, TOKEN)
    assert ok, answer
    assert answer["created"] and answer["revision"] == "r1" and [f["name"] for f in answer["files"]] == ["a.png", "b.png"]
    folder = env.board(answer["slug"])
    assert (folder / "files" / "r001" / "a.png").read_bytes() == png()
    assert (folder / ".gitignore").read_text() == "*\n"
    page = served(client, answer["slug"])
    a, b = b64(png()), b64(png((10, 200, 10)))
    assert page.count(f"data:image/png;base64,{a}") == 2 and f"src='data:image/png;base64,{b}'" in page
    assert "files/a.png" not in page and "files/b.png" not in page
    assert 'src="files/nope.png"' in page
    assert (folder / "r001.html").read_text() == PAGE
    row = scan.scan(env.root).boards[0]
    assert row.scratch and row.status == "ok", scan.scan(env.root).findings


def test_a_changed_file_is_not_served(env: Env, client):
    ok, answer = post(env)
    stored = env.board(answer["slug"]) / "files" / "r001" / "a.png"
    swapped = bytearray(stored.read_bytes())
    swapped[-20] ^= 0xFF
    stored.write_bytes(bytes(swapped))
    page = served(client, answer["slug"])
    assert "files/a.png" in page and b64(bytes(swapped)) not in page


def test_a_second_post_by_name_is_the_next_revision_on_the_same_task(env: Env, client):
    ok, first = post(env, TOKEN)
    ok, second = post(env, TOKEN, html="<img src=\"files/c.png\">", files=[{"name": "c.png", "content_base64": b64(png((1, 2, 3)))}])
    assert ok and not second["created"] and second["slug"] == first["slug"] and second["revision"] == "r2"
    assert second["task"] == first["task"]
    item = task_manager_store(env).item(first["task"])
    assert item["state"] == "todo" and item["list"] == "all" and item["title"].startswith("scratch: ")
    assert f"data:image/png;base64,{b64(png((1, 2, 3)))}" in served(client, first["slug"], "r2")


def test_the_multipart_route_posts_the_same_way(env: Env, client):
    response = client.post(f"{BASE}/scratch", data={"name": "desk", "summary": "from curl"},
                           files=[("page", ("page.html", PAGE.encode(), "text/html")), ("files", ("a.png", png(), "image/png")),
                                  ("files", ("b.png", png((10, 200, 10)), "application/octet-stream"))])
    assert response.status_code == 200, response.text
    assert f"data:image/png;base64,{b64(png())}" in served(client, response.json()["slug"])


def test_the_multipart_route_judges_its_size_before_it_reads_the_body(env: Env, client, monkeypatch):
    from src.cplugs.reviewboard import routes_scratch
    form = {"data": {"name": "desk"}, "files": [("page", ("page.html", PAGE.encode(), "text/html")), ("files", ("a.png", png(), "image/png"))]}
    monkeypatch.setattr(routes_scratch, "MAX_REQUEST_BYTES", 200)
    response = client.post(f"{BASE}/scratch", **form)
    assert response.status_code == 413 and response.json()["detail"]["code"] == "reviewboard_too_large"
    monkeypatch.setattr(routes_scratch, "MAX_REQUEST_BYTES", 10 * 1024 * 1024)
    chunked = client.post(f"{BASE}/scratch", content=iter([b"--x\r\n"]), headers={"content-type": "multipart/form-data; boundary=x"})
    assert chunked.status_code == 411 and chunked.json()["detail"]["code"] == "reviewboard_length_required"
    assert not list(env.root.rglob("sidecar.json"))



@pytest.mark.parametrize("files, code", [
    ([{"name": "../a.png", "content_base64": b64(png())}], "path separator"),
    ([{"name": "sub/a.png", "content_base64": b64(png())}], "path separator"),
    ([{"name": "a b.png", "content_base64": b64(png())}], "reviewboard_invalid"),
    ([{"name": ".hidden.png", "content_base64": b64(png())}], "reviewboard_invalid"),
    ([{"name": "a.png", "content_base64": b64(b"not a png at all")}], "reviewboard_invalid"),
    ([{"name": "a.png", "content_base64": b64(png())}] * 2, "reviewboard_invalid"),
    ([{"name": f"f{i}.png", "content_base64": b64(png())} for i in range(scratch.MAX_FILES + 1)], "reviewboard_too_large"),
])
def test_a_bad_name_type_repeat_or_count_is_refused_and_nothing_is_written(env: Env, files, code):
    before = tree(env.root)
    ok, text = post(env, TOKEN, files=files)
    assert not ok and code in text, text
    assert tree(env.root) == before


def test_an_oversize_image_is_refused(env: Env, caps):
    caps.max_size_mb = 1
    data = png() + b"\0" * (1024 * 1024)
    before = tree(env.root)
    ok, text = post(env, files=[{"name": "big.png", "content_base64": b64(data)}])
    assert not ok and "reviewboard_invalid" in text and "1 MB" in text, text
    assert tree(env.root) == before


def test_more_bytes_than_a_post_may_carry_is_refused(env: Env, monkeypatch):
    monkeypatch.setattr(scratch, "MAX_TOTAL_BYTES", 100)
    ok, text = post(env)
    assert not ok and "reviewboard_too_large" in text, text


def test_the_caps_hold_for_every_door_not_only_the_mcp_decoder(env: Env):
    with pytest.raises(TooLarge, match="files"):
        scratch.check_files([scratch.Upload(f"f{i}.png", png()) for i in range(scratch.MAX_FILES + 1)])
    with pytest.raises(TooLarge, match="MB"):
        scratch.check_files([scratch.Upload("a.bin", b"\0" * (scratch.MAX_TOTAL_BYTES + 1))])


def test_a_review_board_name_takes_no_scratch_post(env: Env, client):
    ok, answer = post(env, name="mock")
    folder = env.board(answer["slug"])
    sidecar = json.loads((folder / "sidecar.json").read_text())
    sidecar["ext"] = {}
    (folder / "sidecar.json").write_text(json.dumps(sidecar, indent=2) + "\n")
    home = task_manager_store(env).item(answer["task"])["list"]
    tasks = len(task_manager_store(env).list_items(home)["items"])
    ok, text = post(env, name="mock")
    assert not ok and "reviewboard_not_scratch" in text, text
    assert len(task_manager_store(env).list_items(home)["items"]) == tasks
    assert client.delete(f"{BASE}/boards/{answer['slug']}").json()["detail"]["code"] == "reviewboard_not_scratch"
    assert folder.is_dir()



def test_a_path_is_refused_for_a_token_and_read_for_a_pane(env: Env, tmp_path: Path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(png((9, 9, 9)))
    for caller in (TOKEN, APPROVED_TOKEN):
        ok, text = post(env, caller, files=None, file_paths=[str(shot)])
        assert not ok and "only a session running here" in text, text
    ok, text = post(env, TOKEN, html=None, file_path=str(tmp_path / "p.html"), files=None)
    assert not ok and "only a session running here" in text
    ok, answer = post(env, PANE, files=None, file_paths=[str(shot)], html="<img src=files/shot.png>")
    assert ok and answer["files"][0]["name"] == "shot.png"
    link = tmp_path / "link.png"
    link.symlink_to(shot)
    ok, text = post(env, PANE, files=None, file_paths=[str(link)])
    assert not ok and "symlink" in text


def test_the_reader_itself_refuses_an_approved_tokens_path(tmp_path: Path, caps):
    shot = tmp_path / "shot.png"
    shot.write_bytes(png())
    with pytest.raises(ToolError, match="only a session running here"):
        read_local_file(APPROVED_TOKEN, str(shot))
    assert read_local_file(PANE, str(shot)) == (png(), "shot.png")


def test_task_manager_reply_attaches_a_panes_path_and_refuses_a_tokens(env: Env, tmp_path: Path):
    item = task_manager_store(env).add("12", "a task", actor="claude")["id"]
    shot = tmp_path / "shot.png"
    shot.write_bytes(png())
    for caller in (TOKEN, APPROVED_TOKEN):
        ok, text = env.call("task_manager_reply", {"item": item, "text": "look", "file_paths": [str(shot)]}, caller)
        assert not ok and "only a session running here" in text, text
    ok, answer = env.call("task_manager_reply", {"item": item, "text": "look", "file_paths": [str(shot)]}, PANE)
    assert ok, answer
    files = task_manager_store(env).item(item)["thread"][-1]["files"]
    assert [f["name"] for f in files] == ["shot.png"] and files[0]["image"]
    ok, text = env.call("task_manager_reply", {"item": item, "text": "x", "file_paths": [str(tmp_path / "missing.png")]}, PANE)
    assert not ok and "cannot be opened" in text



def test_a_tokens_scratch_post_runs_at_once_and_a_board_create_still_waits(env: Env, monkeypatch):
    parked = []

    async def park(manager, caller, target_id, target_tmux, name, summary, shown, run, *args, **kwargs):
        parked.append(name)
        return {"content": [{"type": "text", "text": json.dumps({"status": "pending", "id": "act_1"})}]}

    monkeypatch.setattr(write_tools, "park", park)
    ok, answer = post(env, TOKEN)
    assert ok and answer["revision"] == "r1" and parked == []
    item = task_manager_store(env).add("all", "a task", actor="claude")["id"]
    ok, pending = env.call("task_manager_board_create", {"name": "mock", "title": "m", "task": item, "summary": "s", "viewport": 320,
                                                         "html": "<p>x</p>"}, TOKEN)
    assert ok and pending["status"] == "pending"
    assert parked == ["task_manager_board_create"]
    ok, text = env.call("task_manager_scratch_clear", {"board": answer["slug"]}, PANE)
    assert ok and parked == ["task_manager_board_create", "task_manager_scratch_clear"]


def test_a_large_request_reaches_only_the_scratch_post(env: Env):
    big = "x" * (protocol.MAX_BODY_BYTES + 10)
    scratch_call = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "task_manager_scratch_post", "arguments": {"html": big}}}).encode()
    other = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "task_manager_reply", "arguments": {"text": big}}}).encode()
    assert protocol.body_allowed(scratch_call, TOKEN)
    assert not protocol.body_allowed(other, TOKEN)
    assert not protocol.body_allowed(b"[" + scratch_call + b"]", TOKEN)
    assert not protocol.body_allowed(scratch_call, AgentCaller("r", "r", "r", token_name="ro", scope="read"))
    assert not protocol.body_allowed(scratch_call + b" " * protocol.MAX_READ_BYTES, TOKEN)



def test_the_clear_removes_the_board_and_every_file(env: Env, client):
    ok, first = post(env)
    post(env)
    folder = env.board(first["slug"])
    assert (folder / "files" / "r002" / "b.png").is_file()
    answer = client.delete(f"{BASE}/boards/{first['slug']}")
    assert answer.status_code == 200 and answer.json() == {"slug": first["slug"], "revisions": 2, "files": 4,
                                                            "bytes": 2 * (len(png()) + len(png((10, 200, 10))))}
    assert not folder.exists() and not list(folder.parent.glob(f".gone-{first['slug']}-*"))
    assert task_manager_store(env).item(first["task"])["id"] == first["task"]
    assert client.delete(f"{BASE}/boards/{first['slug']}").status_code == 404
