
from __future__ import annotations

import random
import string

import structlog

from src.cplugs.sdk import file_secrets
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_store
from tests.python.cplugs.reviewboard.test_attachments import MD, PDF, b64, board, client, env, sidecar, tree  # noqa: F401

FAKE = "ghp_" + "".join(random.Random(1835).choices(string.ascii_letters + string.digits, k=36))
PLACEHOLDER = "ghp_" + "x" * 36
_RNG = random.Random(1836)
_B64 = string.ascii_letters + string.digits + "-_"
BEARER = "".join(_RNG.choices(_B64, k=40))
JWT = "eyJ" + "".join(_RNG.choices(_B64, k=20)) + ".eyJ" + "".join(_RNG.choices(_B64, k=30)) + "." + "".join(_RNG.choices(_B64, k=43))


def post(client, board: dict, *files: tuple):
    return client.post(f"{BASE}/boards/{board['slug']}/attachments",
                       json={"files": [{"name": n, "content_base64": b64(d)} for n, d in files]})


def test_a_planted_credential_in_a_text_attachment_is_refused_and_never_echoed(env, client, board):
    before, thread = tree(env.root), task_manager_store(env).item(board["item"])["thread"]
    with structlog.testing.capture_logs() as logs:
        r = post(client, board, ("ok.md", MD), ("notes.md", f"deploy with token {FAKE} today\n".encode()))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "reviewboard_file_has_secret"
    assert detail["files"] == [{"file": "notes.md", "detectors": {"github_token": 1}}]
    assert FAKE not in r.text and FAKE[4:] not in r.text and FAKE not in repr(logs) and FAKE[4:] not in repr(logs)
    assert any(line["event"] == "reviewboard_attach_secret_refused" for line in logs)
    assert tree(env.root) == before and task_manager_store(env).item(board["item"])["thread"] == thread
    assert "attachments" not in sidecar(env, board["slug"]).get("ext", {})


def test_the_mcp_door_refuses_it_too_without_the_value(env, board):
    ok, text = env.call("task_manager_board_attachment_add", {"board": board["slug"], "files": [{"name": "n.txt", "content_base64": b64(FAKE.encode())}]})
    assert not ok and "reviewboard_file_has_secret" in text and "n.txt" in text and FAKE not in text, text


def test_a_clean_file_and_a_placeholder_still_attach(env, client, board):
    files = (("a.md", MD), ("hashes.json", b'{"sha": "' + b"a" * 64 + b'"}'), ("doc.md", f"use {PLACEHOLDER}\n".encode()), ("s.pdf", PDF))
    assert post(client, board, *files).status_code == 200


def test_every_file_with_a_credential_is_named(env, client, board):
    r = post(client, board, ("a.txt", f"{FAKE}\n{FAKE}".encode()), ("b.yaml", f"key: {FAKE}".encode()))
    assert r.status_code == 422
    assert r.json()["detail"]["files"] == [{"file": "a.txt", "detectors": {"github_token": 2}}, {"file": "b.yaml", "detectors": {"github_token": 1}}]


def test_the_sdk_door_counts_detectors_and_keeps_no_value():
    assert file_secrets.credential_counts(f"a {FAKE} b") == {"github_token": 1}
    assert file_secrets.credential_counts("nothing here") == {}
    assert FAKE not in repr(file_secrets.credential_counts(FAKE))


def test_a_bearer_header_in_a_log_and_a_jwt_in_a_json_are_refused_without_the_value(env, client, board):
    log = f"> GET /api HTTP/1.1\n> Authorization: Bearer {BEARER}\n< HTTP/1.1 200 OK\n".encode()
    doc = ('{"session": "' + JWT + '"}').encode()
    r = post(client, board, ("curl.log", log), ("session.json", doc))
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["files"] == [{"file": "curl.log", "detectors": {"bearer_token": 1}}, {"file": "session.json", "detectors": {"jwt": 1}}]
    assert BEARER not in r.text and JWT not in r.text


DOC_LINES = (
    "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6...",
    "Authorization: Bearer ACCESS_TOKEN_FROM_LOGIN_RESPONSE",
    "Authorization: Bearer access_token_from_step_two",
    "Bearer authentication-scheme (RFC 6750)",
    "use Bearer OAuth2-AccessToken-Format here",
)


def test_prose_about_bearer_tokens_still_attaches(env, client, board):
    text = b"A bearer token is sent in the Authorization header: Bearer ${TOKEN} or bearer <your-token>.\n"
    assert post(client, board, ("howto.md", text)).status_code == 200
    for i, line in enumerate(DOC_LINES):
        assert post(client, board, (f"doc{i}.md", (line + "\n").encode())).status_code == 200, line


def test_the_file_scan_keeps_real_bearer_tokens_and_drops_doc_placeholders():
    for line in DOC_LINES:
        assert file_secrets.credential_counts(line) == {}, line
    assert file_secrets.credential_counts(f"Authorization: Bearer {BEARER}") == {"bearer_token": 1}
    assert file_secrets.credential_counts("Authorization: Bearer " + "-".join(BEARER[i:i + 10] for i in range(0, 40, 10))) == {"bearer_token": 1}
    assert file_secrets.credential_counts(f"Authorization: Bearer {JWT}") == {"jwt": 1}
    assert file_secrets.credential_counts("Authorization: Bearer " + JWT.rsplit(".", 1)[0]) == {}
    assert FAKE not in repr(file_secrets.credential_counts(f"Bearer {BEARER} {FAKE}"))


def test_a_js_file_holding_a_key_is_refused_without_the_value(env, client, board):
    for name, body in (("config.js", f'const KEY = "{FAKE}";\n'), ("page.html", f"<script>fetch('/x', {{headers: {{k: '{FAKE}'}}}})</script>"),
                       ("logo.svg", f"<!-- {FAKE} --><svg/>")):
        r = post(client, board, (name, body.encode()))
        assert r.status_code == 422 and r.json()["detail"]["files"] == [{"file": name, "detectors": {"github_token": 1}}], (name, r.text)
        assert FAKE not in r.text


def test_a_five_part_jwe_is_counted_bare_and_after_bearer_and_a_placeholder_is_not():
    jwe = ".".join(["eyJ" + "hbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0", "", "dGhpc2lzZmFrZWl2", "ZmFrZWNpcGhlcnRleHRmb3J0ZXN0", "ZmFrZXRhZ2ZvcnRlc3Q"])
    assert file_secrets.credential_counts(f"token {jwe} end") == {"jwt": 1}
    assert file_secrets.credential_counts(f"Authorization: Bearer {jwe}") == {"jwt": 1}
    assert file_secrets.credential_counts("Authorization: Bearer eyJhbGciOiJkaXIifQ.<key>.<iv>.<ciphertext>.<tag>") == {}
    assert jwe not in repr(file_secrets.credential_counts(jwe))


def test_a_bearer_jws_the_detector_floor_misses_is_still_counted_as_bearer_not_dropped():
    head = "eyJ" + "hbGciOiJIUzI1NiJ9"
    for token in (f"{head}.e30.c2lnbmF0dXJlMTIzNDU2", f"{head}.bm90anNvbnBheWxvYWQ.c2lnbmF0dXJlMTIzNDU2", f"{head}.abc.def"):
        assert file_secrets.credential_counts(f"Authorization: Bearer {token}") == {"bearer_token": 1}, token[-12:]
    assert file_secrets.credential_counts(f"Authorization: Bearer {head}.e30") == {}


def test_a_credential_scan_that_runs_past_the_deadline_is_refused_as_unscannable(monkeypatch):
    import itertools

    import pytest

    from src.core.secret_scanning import deadline as scan_deadline
    from src.cplugs.reviewboard import attachment_secrets
    from src.cplugs.reviewboard.errors import UnscannableFile

    ticks = itertools.count(0, 20)
    monkeypatch.setattr(scan_deadline, "_now", lambda: float(next(ticks)))
    with pytest.raises(UnscannableFile) as exc:
        attachment_secrets.findings([("notes.md", b"# clean text\n")])
    assert exc.value.extra["files"] == [{"file": "notes.md", "reason": "scan_timeout"}]
