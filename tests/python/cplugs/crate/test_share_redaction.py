
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import string
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Dict

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for
from src.cplugs.crate import constants as K
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.share import ShareUnscannable
from src.cplugs.crate.share_out import NOT_TEXT
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import UUID_A, crate_text, env_for, make_world, session_request
from tests.python.inventory.world import CONV_A

_ALPHABET = string.ascii_letters + string.digits


def _github() -> str:
    return "ghp_" + "".join(secrets.choice(_ALPHABET) for _ in range(36))


def _pem() -> str:
    body = "\n".join(base64.b64encode(secrets.token_bytes(48)).decode() for _ in range(4))
    return "-----BEGIN " + "RSA PRIVATE KEY-----\n" + body + "\n-----END " + "RSA PRIVATE KEY-----\n"


def _escaped(text: str) -> str:
    return "".join(f"\\u{ord(c):04x}" for c in text)


def _plant(w: SimpleNamespace) -> Dict[str, str]:
    folder = Path(w.home) / "projects" / slugify_project_dir(w.root1)
    home = str(Path.home())
    enc_home = re.sub(r"[^A-Za-z0-9]", "-", home) + "-"
    planted = {"plain": _github(), "escaped": _github(), "uescaped": _github(), "nested": _github(), "title": _github(),
               "pem": _pem()}
    lines = [
        json.dumps({"type": "user", "message": {"content": f"my key is {planted['plain']}"}}),
        json.dumps({"type": "tool", "content": json.dumps({"env": {"TOKEN": planted["escaped"]}})}),
        '{"type":"user","message":{"content":"' + _escaped(planted["uescaped"]) + '"}}',
        json.dumps({"type": "tool", "content": json.dumps(json.dumps({"deep": planted["nested"]}))}),
        json.dumps({"type": "user", "message": {"content": "placeholder ghp_" + "x" * 36}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}]}}),
        json.dumps({"cwd": f"{home}/work/app", "folder": f"{enc_home}work-app"}),
    ]
    (folder / f"{CONV_A}.jsonl").write_bytes(("\n".join(lines) + "\n").encode() + b'{"type":"user","mess')
    tools = folder / CONV_A / "tool-results"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "out.txt").write_text(f"deploy log\n{planted['pem']}done\n")
    (tools / "screen.bin").write_bytes(b"\xff\xfe\x00 not text")
    with closing(connect(db_path_for(w.state))) as conn:
        conn.execute("UPDATE sessions SET title = ? WHERE session_uuid = ?", (f"fix {planted['title']}", UUID_A))
        conn.commit()
    return planted


@pytest.fixture
def shared(tmp_path: Path) -> SimpleNamespace:
    w = make_world(tmp_path)
    w.planted = _plant(w)
    with closing(connect(db_path_for(w.state))) as conn:
        w.rows_before = conn.execute("SELECT (SELECT count(*) FROM export_bundles), "
                                     "(SELECT count(*) FROM export_pointers)").fetchone()
    env = env_for(w)
    w.result = run_export(env, build_plan(env, session_request(variant="share")), JobHandle("s"))
    w.text = crate_text(w.result.path)
    return w


def _transcript(w: SimpleNamespace) -> bytes:
    with cf.open_crate(w.result.path) as reader:
        record = next(r for r in reader.files() if r.rel == f"projects/_shared/{CONV_A}.jsonl")
        return b"".join(reader.file_chunks(record))


def test_every_token_shape_is_starred_and_every_line_parses(shared: SimpleNamespace) -> None:
    for name, value in shared.planted.items():
        needle = value.split("\n")[1] if name == "pem" else value
        assert needle.encode() not in shared.text, name
    data = _transcript(shared)
    lines = data.split(b"\n")
    assert lines[-1] == b"" and len(lines) == 8
    parsed = [json.loads(line) for line in lines[:-1]]
    assert b"ghp_" + b"x" * 36 not in data and b"*" * 20 in data
    assert parsed[5]["message"]["content"] == [{"type": "text", "text": K.IMAGE_PLACEHOLDER}]
    assert str(Path.home()).encode() not in shared.text and parsed[6]["cwd"] == f"{K.HOME_SCRUB_TO}/work/app"
    assert parsed[6]["folder"] == "-Users-user-work-app"


def test_the_manifest_says_what_a_share_is(shared: SimpleNamespace) -> None:
    with cf.open_crate(shared.result.path) as reader:
        manifest = reader.manifest
        files = reader.files()
        reconcile = reader.read_json(cf.constants.M_RECONCILE)["artifacts"]
        secrets_json = reader.read_json(cf.constants.M_SECRETS)
    assert shared.result.path.parent.name == "share" and shared.result.file_name.startswith("share-")
    assert manifest.variant == "share" and not manifest.byte_exact and manifest.resume == "fork_only"
    assert set(manifest.source) == {"share_id"} and all(h.path is None for h in manifest.homes)
    assert {c.family: c.resume for c in manifest.conversations} == {"claude": "fork_only"}
    assert any(r.home == "codex" and r.rel.startswith("sessions/_shared/rollout-") for r in files)
    assert all(c.working_dir is None and c.enc_folder is None for c in manifest.conversations)
    title = next(c.title for c in manifest.conversations if c.id == CONV_A)
    assert title.startswith("fix ") and "*" * 20 in title
    assert all(r.source_path is None and r.enc_folder is None for r in files)
    assert all(r.rel.startswith(("projects/_shared/", "sessions/_shared/")) for r in files)
    redaction = manifest.redaction
    assert redaction["residual_scan"] == "clean" and redaction["torn_dropped"] == 1
    assert redaction["images_stripped"] == 1 and redaction["home_scrubbed"] >= 2 and redaction["files_changed"] >= 2
    assert redaction["findings"].get("github_token", 0) >= 4 and redaction["findings"].get("pem_private_key", 0) >= 1
    assert "do not find personal data" in redaction["note"]
    assert secrets_json["total"] == sum(redaction["findings"].values())
    assert {"kind": "policy", "store": "claude", "reason": NOT_TEXT} in manifest.excluded
    assert all("what" not in e for e in manifest.excluded) and all("what" not in r for r in reconcile)
    assert len({(r["store"], r["decision"]) for r in reconcile}) == len(reconcile)
    assert not any(r.rel.endswith("screen.bin") for r in files)


def test_a_share_is_never_recorded_and_resumes_as_a_fork(shared: SimpleNamespace, tmp_path: Path) -> None:
    with closing(connect(db_path_for(shared.state))) as conn:
        after = conn.execute("SELECT (SELECT count(*) FROM export_bundles), (SELECT count(*) FROM export_pointers)").fetchone()
    assert after == shared.rows_before and not shared.result.recorded
    with cf.open_crate(shared.result.path) as reader:
        out = cf.extract_conversation(reader, CONV_A, tmp_path / "x", enc_for=slugify_project_dir)
    assert "--fork-session" in out.resume_hint and out.enc_folder == "_shared"


def test_the_own_variant_of_the_same_input_is_byte_exact(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    planted = _plant(w)
    env = env_for(w)
    result = run_export(env, build_plan(env, session_request()), JobHandle("o"))
    source = (Path(w.home) / "projects" / slugify_project_dir(w.root1) / f"{CONV_A}.jsonl").read_bytes()
    with cf.open_crate(result.path) as reader:
        record = next(r for r in reader.files() if r.conversation_id == CONV_A and r.role == "transcript")
        assert b"".join(reader.file_chunks(record)) == source
        found = reader.read_json(cf.constants.M_SECRETS)
    assert found["total"] >= 4 and all(isinstance(n, int) for per in found["by_file"].values() for n in per.values())
    text = crate_text(result.path)
    for value in planted.values():
        assert hashlib.sha256(value.encode()).hexdigest().encode() not in text


def test_an_unparseable_middle_line_refuses_the_share(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    transcript = Path(w.home) / "projects" / slugify_project_dir(w.root1) / f"{CONV_A}.jsonl"
    transcript.write_bytes(b'{"a":1}\nnot json at all\n{"b":2}\n')
    env = env_for(w)
    with pytest.raises(ShareUnscannable) as caught:
        run_export(env, build_plan(env, session_request(variant="share")), JobHandle("u"))
    assert "line 2 is not JSON" in str(caught.value) and not any((Path(w.state) / "crates" / "share").iterdir())
