
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import zlib
from pathlib import Path

from src.cplugs.save.engine.codec import _zstd as zstd
from src.cplugs.save.vault.old_sources import archive_db, folder_tree, model, old_store, tar_files

A, B, C, D = (f"{n}" * 8 + "-1111-2222-3333-" + f"{n}" * 12 for n in "abcd")
ENC = "-Users-x-proj"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blocks(copy: model.Copy) -> bytes:
    return b"".join(copy.opener())


def test_archive_db_reader_refuses_a_row_whose_hash_is_wrong(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE transcript_archives (id INTEGER PRIMARY KEY, source_path TEXT, content_gzip BLOB, content_sha256 TEXT, "
                "raw_byte_length INTEGER, ingested_at TEXT, ingest_source_mtime TEXT, superseded_by_archive_id INTEGER)")
    good, sub, bad, old = b'{"a":1}\n' * 5, b'{"s":1}\n', b'{"b":1}\n', b'{"o":1}\n'
    rows = [(1, f"{ENC}/{A}.jsonl", good, sha(good), None), (2, f"{ENC}/{A}/subagents/agent-1.jsonl", sub, sha(sub), None),
            (3, f"{ENC}/{B}.jsonl", bad, "0" * 64, None), (4, f"{ENC}/{C}.jsonl", old, sha(old), 1),
            (5, f"/Users/x/.codex/sessions/2026/03/18/rollout-2026-03-18T16-54-04-{C}.jsonl", good, sha(good), None),
            (6, f"/mnt/ARCHIVE/claude-archive-20260830/03-history.tar.zst#projects/{ENC}/{D}.jsonl", good, sha(good), None),
            (7, "/Users/x/Library/Application Support/Claude/local-agent-mode-sessions/a/local_1/audit.jsonl", good, sha(good), None)]
    for rid, path, data, digest, sup in rows:
        con.execute("INSERT INTO transcript_archives VALUES (?,?,?,?,?,?,?,?)", (rid, path, zlib.compress(data), digest, len(data),
                                                                                   "2026-10-01T00:18:20.851026Z", None, sup))
    con.commit()
    con.close()
    before = db.read_bytes()
    intake = model.Intake()
    copies = list(archive_db.iter_copies(db, intake))
    assert [c.ident.rel for c in copies] == [f"projects/{ENC}/{A}.jsonl", f"projects/{ENC}/{A}/subagents/agent-1.jsonl",
                                             f"sessions/2026/03/18/rollout-2026-03-18T16-54-04-{C}.jsonl", f"projects/{ENC}/{D}.jsonl"]
    assert [r.locator for r in intake.skipped] == ["db:old.db:7"] and [r.locator for r in intake.refused] == ["db:old.db:3"] and blocks(copies[0]) == good and copies[2].ident.family == "codex"
    assert db.read_bytes() == before


def test_folder_reader_strips_the_export_suffix_skips_finder_files_and_refuses_a_wrong_hash(tmp_path: Path) -> None:
    layer = tmp_path / "export" / "message-layer-claude-session" / ENC
    layer.mkdir(parents=True)
    (tmp_path / "export" / "archive-metadata").mkdir()
    (tmp_path / "export" / "archive-metadata" / "tables.jsonl").write_text("{}\n")
    ok, wrong = b'{"ok":1}\n', b'{"w":1}\n'
    (layer / f"{A}@20260903T141624Z-m3682.jsonl").write_bytes(ok)
    (layer / f"{B}@20260903T141624Z-m3.jsonl").write_bytes(wrong)
    (layer / f"._{A}.jsonl").write_bytes(b"\x00\x05")
    (layer / "assistants-mac-52c8040d-stub.jsonl").write_bytes(ok)
    intake = model.Intake()
    recorded = {str(layer / f"{B}@20260903T141624Z-m3.jsonl"): "f" * 64}
    copies = list(folder_tree.iter_copies(tmp_path / "export", intake, "recovered", recorded))
    assert [c.ident.rel for c in copies] == [f"projects/{ENC}/{A}.jsonl"] and copies[0].sha256 == sha(ok)
    assert len(intake.refused) == 1 and sorted(s.reason for s in intake.skipped) == ["appledouble", "not a transcript path"]


def test_old_store_reader_decodes_points_and_refuses_a_wrong_hash(tmp_path: Path) -> None:
    root = tmp_path / "retired"
    data, wrong = b'{"u":1}\n' * 3, b'{"w":1}\n'
    for conv, body, recorded in ((A, data, sha(data)), (B, wrong, "e" * 64)):
        point = root / "time-machine" / "proj" / conv / "20260915T101010Z-kill"
        point.mkdir(parents=True)
        (point / "transcript.jsonl.zst").write_bytes(zstd.compress(body))
        meta = {"agent_family": "claude", "codec": "zstd", "conversation_id": conv, "created_epoch": 1789000000.5,
                "transcript": {"file": "transcript.jsonl.zst", "raw_bytes": len(body), "sha256": recorded,
                               "source_path": f"/Users/x/.claude/projects/{ENC}/{conv}.jsonl"}}
        if conv == A:
            tar_bytes = io.BytesIO()
            with tarfile.open(fileobj=tar_bytes, mode="w") as tar:
                info = tarfile.TarInfo("agent-1.jsonl")
                info.size = len(wrong)
                tar.addfile(info, io.BytesIO(wrong))
            (point / "subagents.tar.zst").write_bytes(zstd.compress(tar_bytes.getvalue()))
            meta["subagents"] = {"file": "subagents.tar.zst", "files": [{"path": "agent-1.jsonl", "sha256": sha(wrong), "bytes": len(wrong)}]}
        (point / "meta.json").write_text(json.dumps(meta))
    intake = model.Intake()
    copies = list(old_store.iter_copies(root, intake))
    assert [c.ident.rel for c in copies] == [f"projects/{ENC}/{A}.jsonl", f"projects/{ENC}/{A}/subagents/agent-1.jsonl"]
    assert copies[0].captured_epoch == 1789000000.5 and blocks(copies[1]) == wrong and len(intake.refused) == 1


def test_tar_reader_refuses_a_damaged_tar_and_yields_the_rest(tmp_path: Path) -> None:
    def make(path: Path, member: str, body: bytes) -> None:
        with tarfile.open(path, "w") as tar:
            for name, data in ((member, body), (f"{ENC}/._{A}.jsonl", b"\x00")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    make(tmp_path / "a.tar", f"{ENC}/{A}.jsonl", b'{"t":1}\n' * 50)
    make(tmp_path / "b.tar", f"{ENC}/{B}.jsonl", b'{"t":2}\n' * 5000)
    damaged = (tmp_path / "b.tar").read_bytes()
    (tmp_path / "b.tar").write_bytes(damaged[:600])
    intake = model.Intake()
    copies = list(tar_files.iter_copies(tmp_path, intake))
    assert [c.ident.conv for c in copies] == [A] and [s.reason for s in intake.skipped] == ["appledouble"]
    assert len(intake.refused) == 1 and intake.refused[0].locator.endswith("b.tar")
