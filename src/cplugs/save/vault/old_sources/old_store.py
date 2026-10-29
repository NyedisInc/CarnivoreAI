
from __future__ import annotations

import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterator, Optional

from src.cplugs.save.engine import codec as codec_mod
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import legacy
from src.cplugs.save.vault.old_sources import model, names


def _stream(path: Path, codec: str) -> Iterator[bytes]:
    with codec_mod.open_reader(path, codec) as handle:
        while block := handle.read(model.READ_BLOCK):
            yield block


def _member(path: Path, codec: str, member_name: str) -> Iterator[bytes]:
    with codec_mod.open_reader(path, codec) as handle, tarfile.open(fileobj=handle, mode="r|") as tar:
        for member in tar:
            if member.name == member_name and member.isreg():
                inner = tar.extractfile(member)
                while block := inner.read(model.READ_BLOCK):
                    yield block
                return
    raise KeyError(member_name)


def _main_ident(meta: Dict[str, Any], conv: str) -> Optional[names.Ident]:
    source = str(meta["transcript"].get("source_path") or "")
    if (meta.get("agent_family") or "claude") == "codex":
        return names.Ident(conv, "codex", names.KIND_MAIN, "", "", legacy.codex_rel(source), K.ROLE_CODEX_ROLLOUT)
    enc = legacy._encoded_folder(meta, conv)
    return names.Ident(conv, "claude", names.KIND_MAIN, "", enc, f"projects/{enc}/{conv}.jsonl", K.ROLE_TRANSCRIPT)


def iter_copies(root: Path, intake: model.Intake, name: str = "oldstore", *, trust: bool = False) -> Iterator[model.Copy]:
    if not legacy.tree_dir(Path(root)).is_dir():
        raise model.SourceError(f"{root} holds no {legacy.TREE_DIR} folder")
    for point in legacy.iter_points(Path(root)):
        meta, directory = point.meta, point.directory
        conv = str(meta.get("conversation_id") or directory.parent.name)
        ident = _main_ident(meta, conv)
        record = meta["transcript"]
        codec = meta.get("codec", "zstd")
        packed = directory / record.get("file", "transcript.jsonl.zst")
        captured = float(meta.get("created_epoch") or 0.0)
        copy = model.checked(intake, name, f"{point.key}", ident, lambda p=packed, c=codec: _stream(p, c), captured,
                             want_sha=record.get("sha256"), want_length=record.get("raw_bytes"),
                             errors=(OSError, codec_mod.CodecError, ValueError), trust=trust)
        if copy is None:
            continue
        yield copy
        sub = meta.get("subagents")
        if not sub or ident.family != "claude":
            continue
        recorded = {str(s.get("path")): s for s in (sub.get("files") or []) if isinstance(s, dict)}
        tar_path, tar_codec = directory / sub["file"], sub.get("codec", codec)
        if trust and recorded:
            members = [(p, int(r.get("bytes") or 0)) for p, r in recorded.items() if p.endswith(".jsonl")]
        else:
            try:
                with codec_mod.open_reader(tar_path, tar_codec) as handle, tarfile.open(fileobj=handle, mode="r|") as tar:
                    members = [(m.name, m.size) for m in tar if m.isreg() and m.name.endswith(".jsonl")]
            except (OSError, tarfile.TarError, codec_mod.CodecError) as exc:
                intake.refused.append(model.Refusal(name, f"{point.key}/subagents", f"unreadable: {type(exc).__name__}"))
                continue
        for member_name, _size in members:
            pure = PurePosixPath(member_name)
            if pure.is_absolute() or ".." in pure.parts:
                intake.refused.append(model.Refusal(name, f"{point.key}/{member_name}", "unsafe path"))
                continue
            rec = recorded.get(member_name) or recorded.get(pure.name) or {}
            sub_ident = names.Ident(conv, "claude", names.KIND_SUB, conv, ident.enc,
                                    f"projects/{ident.enc}/{conv}/subagents/{pure}", K.ROLE_SUBAGENT)
            sub_copy = model.checked(intake, name, f"{point.key}/{member_name}", sub_ident,
                                     lambda p=tar_path, c=tar_codec, n=member_name: _member(p, c, n), captured,
                                     want_sha=rec.get("sha256"), want_length=rec.get("bytes"),
                                     errors=(OSError, tarfile.TarError, codec_mod.CodecError, KeyError), trust=trust)
            if sub_copy is not None:
                yield sub_copy
