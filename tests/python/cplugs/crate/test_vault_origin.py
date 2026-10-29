
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, List

import pytest

from src.core.blobcodec.chunking import ChunkReader
from src.core.claude_transcript_correlate import slugify_project_dir
from src.cplugs.crate import constants as K
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.vault_files import VaultOpener
from src.cplugs.crate.writer import run_export
from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.vault import units
from src.cplugs.save.vault.identity import Identity
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.core.deepsearch import fallback_hook as fb
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request
from tests.python.inventory.world import CONV_A

SOURCE_ID = "crate-test-vault"


@pytest.fixture
def vaulted(tmp_path: Path) -> Iterator[SimpleNamespace]:
    (tmp_path / "world").mkdir()
    w = make_world(tmp_path / "world")
    root = tmp_path / "vault"
    root.mkdir()
    (root / "VAULT.json").write_text('{"format": 1}')
    w.vault = Vault(root)
    folder = Path(w.home) / "projects" / slugify_project_dir(w.root1)
    w.main = folder / f"{CONV_A}.jsonl"
    w.main.write_bytes(b"".join(b'{"type":"user","n":%d,"pad":"%s"}\n' % (i, b"p" * 300) for i in range(4000)))
    w.sub = folder / CONV_A / "subagents" / "agent-a1.jsonl"
    sources = units.Sources((Path(w.home) / "projects",), Path(w.codex), Path(w.state))
    w.vault.capture(units.plan_claude(sources, CONV_A), Identity(), "backfill")
    w.attic = tmp_path / "attic"
    w.attic.mkdir()
    fb.register(SOURCE_ID, BackupTranscripts(lambda: w.vault))
    try:
        yield w
    finally:
        fb.unregister(SOURCE_ID)


def _gone(w: SimpleNamespace, attic: Path) -> None:
    main = Path(w.home) / "projects" / slugify_project_dir(w.root1) / f"{CONV_A}.jsonl"
    for path in [main] + sorted(Path(w.codex).rglob(f"rollout-*{CONV_A}.jsonl")):
        path.rename(attic / path.name)


def _disk_chunk_names(data: bytes) -> List[str]:
    return [hashlib.sha256(c).hexdigest() for c in ChunkReader(io.BytesIO(data), len(data), True, keep_tail=True)]


def _codes(plan) -> List[str]:
    return [b["code"] for b in plan.blockers]


def test_a_gone_conversation_is_carried_from_the_vault(vaulted: SimpleNamespace, tmp_path: Path) -> None:
    original = vaulted.main.read_bytes()
    _gone(vaulted, vaulted.attic)
    env = env_for(vaulted)
    plan = build_plan(env, session_request())
    assert plan.ok, plan.blockers
    assert any(w.startswith(K.W_VAULT_FILE) and CONV_A in w for w in plan.warnings)
    result = run_export(env, plan, JobHandle("v"))
    newest = vaulted.vault.manifests.newest(CONV_A).main()
    with cf.open_crate(result.path) as reader:
        record = next(r for r in reader.files() if r.conversation_id == CONV_A and r.role == "transcript")
        assert record.origin == "vault" and record.vault_signature == newest.chain_sha() and record.source_path is None
        assert b"".join(reader.file_chunks(record)) == original
        assert [c.sha256 for c in record.chunks] == _disk_chunk_names(original) and len(record.chunks) > 1
        assert next(c for c in reader.manifest.conversations if c.id == CONV_A).origin == "vault"
        sub = next(r for r in reader.files() if r.rel.endswith("subagents/agent-a1.jsonl"))
        assert sub.origin == "disk"
        out = cf.extract_conversation(reader, CONV_A, tmp_path / "x", enc_for=slugify_project_dir)
    assert (out.dest / f"projects/{slugify_project_dir(vaulted.root1)}/{CONV_A}.jsonl").read_bytes() == original


def test_a_file_only_the_vault_holds_is_carried_with_a_warning(vaulted: SimpleNamespace) -> None:
    data = vaulted.sub.read_bytes()
    vaulted.sub.rename(vaulted.attic / vaulted.sub.name)
    env = env_for(vaulted)
    plan = build_plan(env, session_request())
    assert plan.ok, plan.blockers
    vault_files = [f for f in plan.files if f.origin == "vault"]
    assert [f.rel.split("/", 2)[2] for f in vault_files] == [f"{CONV_A}/subagents/agent-a1.jsonl"]
    assert any(w.startswith(K.W_VAULT_FILE) and "agent-a1.jsonl" in w for w in plan.warnings)
    result = run_export(env, plan, JobHandle("k"))
    with cf.open_crate(result.path) as reader:
        sub = next(r for r in reader.files() if r.rel.endswith("subagents/agent-a1.jsonl"))
        assert sub.origin == "vault" and b"".join(reader.file_chunks(sub)) == data


class _LinesOnly:

    def conversations(self) -> list:
        return []

    def files(self, conversation_id: str) -> list:
        return [fb.FallbackFile(conversation_id, "claude", "conversation", "/x.jsonl", "x.jsonl", 10, "s")] \
            if conversation_id == CONV_A else []

    def reader(self, conversation_id: str, source_path: str, file_kind: str) -> None:
        raise fb.FallbackUnavailable("not here")


class _Unreachable(_LinesOnly):

    def entries(self, conversation_id: str) -> list:
        raise OSError("no such volume")


@pytest.mark.parametrize("source, code", [(_LinesOnly(), K.B_VAULT_INCOMPLETE), (_Unreachable(), K.B_VAULT)])
def test_a_lines_only_or_unreachable_source_blocks_apart_from_missing(tmp_path: Path, source: object, code: str) -> None:
    w = make_world(tmp_path)
    attic = tmp_path / "attic"
    attic.mkdir()
    _gone(w, attic)
    fb.register(SOURCE_ID, source)
    try:
        codes = _codes(build_plan(env_for(w), session_request()))
    finally:
        fb.unregister(SOURCE_ID)
    assert code in codes and K.B_MISSING not in codes
    assert K.B_MISSING in _codes(build_plan(env_for(w), session_request()))


def test_the_opener_refuses_a_backup_that_changed_since_the_plan(vaulted: SimpleNamespace) -> None:
    _gone(vaulted, vaulted.attic)
    plan = build_plan(env_for(vaulted), session_request())
    planned = next(f for f in plan.files if f.origin == "vault")
    stale = type(planned)(**{**planned.__dict__, "vault": ("0" * 64, planned.rel)})
    with pytest.raises(cs.SourceUnavailable, match="no longer holds"):
        VaultOpener().open(stale)
    assert VaultOpener().open(planned).length == planned.size
