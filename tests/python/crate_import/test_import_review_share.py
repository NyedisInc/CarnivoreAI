
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from src.core.crate_import import share_in
from src.core.crate_import.model import B_BAD_IDENTIFIER, ImportRequest
from src.core.crate_import.plan import build_plan
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.install import make_install
from tests.python.crate_import.test_import_share import SHARE


def test_a_share_conversation_id_that_is_not_a_uuid_blocks_the_plan(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    sha = hashlib.sha256(SHARE.read_bytes()).hexdigest()
    request = ImportRequest(mode="relocate", new_root=str(install.projects / "shared-in"))
    with cf.open_crate(SHARE) as reader:
        first, *rest = reader.manifest.conversations
        reader.manifest = replace(reader.manifest, conversations=[replace(first, id="--evil"), *rest])
        assert share_in.bad_identifiers(reader.manifest) == ["--evil"]
        assert "--evil" not in {s.conversation for s in share_in.sessions_of(reader.manifest, [])}
        plan = build_plan(reader, install.env, request, crate_sha256=sha, encrypted=False)
    assert plan["ok"] is False
    assert [b["code"] for b in plan["blockers"]] == [B_BAD_IDENTIFIER]
