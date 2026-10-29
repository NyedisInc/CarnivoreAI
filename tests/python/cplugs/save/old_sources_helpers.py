
from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from src.cplugs.save.vault import constants as K
from src.core.deepsearch.fallback_hook import FallbackPoint, IncomingFile

ENC = "-Users-x-proj"


def incoming_point(unit: str, data: bytes, *, epoch: float = 1_700_000_000.0, tags: Optional[Dict[str, Any]] = None,
                   point_id: str = "20231114T221320Z-import", enc: str = ENC, sha: Optional[str] = None) -> FallbackPoint:
    file = IncomingFile(role=K.ROLE_TRANSCRIPT, home="claude", rel=f"projects/{enc}/{unit}.jsonl", source_path=f"/old/{unit}.jsonl",
                        length=len(data), sha256=sha or hashlib.sha256(data).hexdigest(), mode=0o600, mtime_ns=0, lines=data.count(b"\n"),
                        read=lambda d=data: iter([d]))
    return FallbackPoint(conversation_id=unit, point_id=point_id, reason=K.REASON_IMPORT, created_epoch=epoch, created_at="2023-11-14T22:13:20+00:00",
                         family="claude", files=(file,), working_dir="/Users/x/proj", encoded_folder=enc, tags=tags)


def make_copy(source: str, rel_in_source: str, data: bytes, captured: float = 1_700_000_000.0, locator: str = ""):
    from src.cplugs.save.vault.old_sources import model, names

    ident = names.identify(rel_in_source)
    assert ident is not None, rel_in_source
    return model.Copy(source, locator or f"{source}:{rel_in_source}:{len(data)}", ident, len(data), hashlib.sha256(data).hexdigest(),
                      captured, lambda d=data: iter([d[:7], d[7:]]))


def lines(n: int, tag: str = "a") -> bytes:
    return b"".join(b'{"type":"user","n":%d,"t":"%s","cwd":"/gone/%s"}\n' % (i, tag.encode(), tag.encode()) for i in range(n))
