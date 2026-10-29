
from __future__ import annotations

import hashlib
import http.server
import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

import pytest

from scripts.crate import flows
from scripts.crate.client import CrateClient, sha256_of
from scripts.crate.errors import ApiError, AuthError, IntegrityError, JobFailedError, JobTimeoutError, NetworkError
from scripts.crate.tokens import EnvToken, OnePasswordToken, StaticToken
from scripts.crate.transport import Body, HttpTransport, Response
from src.cplugs.host.routes import host_router
from tests.python.cplugs.crate.api_world import ApiWorld, stop_runner
from tests.python.crate_headless.test_headless_cycle import exported_and_sent
from tests.python.crate_headless.world import A, TwoInstalls

SECRET = "sentinel-not-a-real-token"


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


class Scripted:

    def __init__(self, *answers: Any) -> None:
        self.answers, self.seen = list(answers), []

    def send(self, method: str, path: str, headers: Mapping[str, str], body: Body = None, length: Optional[int] = None) -> Response:
        self.seen.append((method, path, dict(headers)))
        status, payload = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return Response(status, {}, iter([json.dumps(payload).encode()]))



def test_the_token_rides_only_in_the_authorization_header_and_never_in_an_error() -> None:
    stub = Scripted((401, {"detail": "Invalid token"}))
    client = CrateClient(transport=stub, tokens=StaticToken(SECRET))
    with pytest.raises(AuthError) as refused:
        client.plan_import({})
    assert refused.value.exit_code == 3 and SECRET not in str(refused.value) and SECRET not in repr(client)
    assert stub.seen[0][2]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in json.dumps(refused.value.as_json())


def test_a_403_with_a_code_is_an_api_refusal_not_an_auth_one() -> None:
    stub = Scripted((403, {"detail": {"code": "permission_missing", "detail": "imports.write"}}))
    with pytest.raises(ApiError) as refused:
        CrateClient(transport=stub).start_import({}, "0" * 64)
    assert refused.value.code == "permission_missing" and refused.value.status == 403 and refused.value.exit_code == 4


def test_env_token_names_the_variable_not_the_value() -> None:
    with pytest.raises(AuthError, match="CARNIVORE_X is not set"):
        EnvToken("CARNIVORE_X", {}).token()
    assert EnvToken("CARNIVORE_X", {"CARNIVORE_X": f" {SECRET}\n"}).token() == SECRET


def test_one_password_token_puts_only_the_reference_on_the_childs_argv() -> None:
    calls: List[Any] = []

    class Done:
        returncode, stdout, stderr = 0, SECRET + "\n", ""

    def runner(argv: Any, timeout: float) -> Done:
        calls.append(list(argv))
        return Done()

    source = OnePasswordToken("op://Claude/carnivore-m4/credential", runner)
    assert source.token() == SECRET
    assert calls == [["op", "read", "--no-newline", "op://Claude/carnivore-m4/credential"]] and SECRET not in repr(source)

    class Failed:
        returncode, stdout, stderr = 1, "", f"[ERROR] could not read {SECRET}"

    with pytest.raises(AuthError) as bad:
        OnePasswordToken("op://Claude/x/y", lambda argv, timeout: Failed()).token()
    assert SECRET not in str(bad.value)
    with pytest.raises(AuthError):
        OnePasswordToken("not-a-reference")



def test_a_job_that_never_ends_times_out_and_a_failed_job_says_why() -> None:
    now = [0.0]
    running = Scripted((200, {"job_id": "j", "state": "running", "phase": "writing"}))
    slow = CrateClient(transport=running, poll_interval=1.0, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    with pytest.raises(JobTimeoutError) as late:
        slow.wait_job("j", timeout=5.0)
    assert late.value.exit_code == 9 and "writing" in str(late.value)

    failed = Scripted((200, {"job_id": "j", "state": "failed", "error": {"code": "busy", "detail": "a move holds the lock"}}))
    with pytest.raises(JobFailedError) as dead:
        CrateClient(transport=failed).wait_job("j")
    assert dead.value.exit_code == 6 and dead.value.code == "busy"



class FlipsADownloadedByte:

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def send(self, method: str, path: str, headers: Mapping[str, str], body: Body = None, length: Optional[int] = None) -> Response:
        reply = self.inner.send(method, path, headers, body, length)
        if "part=crate" in path and reply.status == 200:
            data = bytearray(reply.read())
            data[len(data) // 2] ^= 0xFF
            return Response(200, reply.headers, iter([bytes(data)]))
        return reply


def test_a_corrupted_download_is_refused_and_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    exported = flows.export_crate(w.client_a, flows.export_body("project", w.a.world.root1))
    broken = CrateClient(transport=FlipsADownloadedByte(w.transports[A]), poll_interval=0.02)
    dest = tmp_path / "dl"
    with pytest.raises(IntegrityError) as refused:
        broken.download_bundle(exported["bundle_id"], dest)
    assert refused.value.exit_code == 8 and refused.value.code == "sha256_mismatch"
    assert list(dest.iterdir()) == []


def test_upload_refuses_a_wrong_checksum_and_an_existing_name_and_leaves_one_clean_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    exported = flows.export_crate(w.client_a, flows.export_body("project", w.a.world.root1))
    path, sha = w.client_a.download_bundle(exported["bundle_id"], tmp_path / "dl")
    assert sha == exported["sha256"] == sha256_of(path)

    with pytest.raises(ApiError) as wrong:
        w.client_b.upload_crate(path, "0" * 64)
    assert wrong.value.status == 422 and w.client_b.folder_crates("primary")["crates"] == []

    stored = w.client_b.upload_crate(path, sha)
    assert stored["sha256"] == sha and stored["size"] == path.stat().st_size
    with pytest.raises(ApiError) as again:
        w.client_b.upload_crate(path, sha)
    assert again.value.status == 409
    assert [c["name"] for c in w.client_b.folder_crates("primary")["crates"]] == [path.name]


def test_send_twice_reports_the_name_taken_and_keeps_the_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    sent = exported_and_sent(w, tmp_path)
    with pytest.raises(ApiError) as again:
        flows.send_crate(w.client_a, w.client_b, sent["bundle_id"], workdir=tmp_path)
    assert again.value.status == 409
    assert [c["name"] for c in w.client_b.folder_crates("primary")["crates"]] == [sent["name"]]


def test_the_real_bearer_check_answers_401_and_the_client_calls_it_an_auth_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch, authed=False)
    with pytest.raises(AuthError) as refused:
        w.client_a.folder_crates("primary")
    assert refused.value.exit_code == 3


def test_setup_turns_the_plugin_on_with_every_grant_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch, on=False)
    api.app.include_router(host_router, prefix="/api/v1")
    test_client = api.client()

    class Direct:

        def send(self, method: str, path: str, headers: Mapping[str, str], body: Body = None, length: Optional[int] = None) -> Response:
            reply = test_client.request(method, path, headers=dict(headers), content=body)
            return Response(reply.status_code, {}, iter([reply.content]))

    client = CrateClient(transport=Direct())
    first = client.setup()
    assert first["enabled"] and first["changed"] and first["folder_ok"]
    assert "imports.write" in first["grants"]
    second = client.setup()
    assert second["enabled"] and not second["changed"]



class StubHost(http.server.BaseHTTPRequestHandler):

    CRATE = b"crate-bytes-" * 200_000
    STORE: Dict[str, Any] = {}

    def log_message(self, *args: Any) -> None:
        pass

    def _json(self, status: int, payload: Any) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if "part=sha256" in self.path:
            raw = (hashlib.sha256(self.CRATE).hexdigest() + "  crate-x.crate\n").encode()
        elif "part=crate" in self.path:
            raw = self.CRATE
        else:
            return self._json(404, {"detail": {"code": "nope", "detail": "no such route"}})
        self.send_response(200)
        self.send_header("Content-Disposition", 'attachment; filename="crate-x.crate"')
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.STORE.update(auth=self.headers.get("Authorization"), name=self.headers.get("X-Crate-Name"), size=len(body),
                          sha=hashlib.sha256(body).hexdigest(), claimed=self.headers.get("X-Crate-Sha256"))
        self._json(201, {"name": self.STORE["name"], "size": len(body), "sha256": self.STORE["sha"], "sidecar": True,
                         "project_root": None})


@pytest.fixture
def stub_url() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubHost)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_http_transport_streams_a_crate_both_ways_with_the_bearer(tmp_path: Path, stub_url: str) -> None:
    client = CrateClient(stub_url, EnvToken("X_TOKEN", {"X_TOKEN": SECRET}))
    path, sha = client.download_bundle("crate-20261020T000000Z-project-aaaaaaaa", tmp_path)
    assert path.name == "crate-x.crate" and path.read_bytes() == StubHost.CRATE and sha == hashlib.sha256(StubHost.CRATE).hexdigest()
    stored = client.upload_crate(path, sha)
    assert stored["size"] == len(StubHost.CRATE) and stored["sha256"] == sha
    assert StubHost.STORE["auth"] == f"Bearer {SECRET}" and StubHost.STORE["claimed"] == sha and StubHost.STORE["name"] == "crate-x.crate"
    with pytest.raises(FileExistsError):
        client.download_bundle("crate-20261020T000000Z-project-aaaaaaaa", tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["crate-x.crate"]


def test_an_unreachable_host_is_a_network_error() -> None:
    with pytest.raises(NetworkError) as down:
        CrateClient(transport=HttpTransport("http://127.0.0.1:1")).plugin_row()
    assert down.value.exit_code == 10
