
from __future__ import annotations

import dataclasses
from pathlib import Path

from src.core.claude_transcript_correlate import slugify_project_dir
from src.cplugs.crate import share as S
from src.cplugs.crate import share_out as SO
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request
from tests.python.inventory.world import CONV_A


def test_finish_scrubs_enc_folders_and_paths_from_warnings_and_reasons(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    env = env_for(w)
    own = run_export(env, build_plan(env, session_request()), JobHandle("own"))
    with cf.open_crate(own.path) as reader:
        manifest = reader.manifest
    plan = build_plan(env, session_request(variant="share"))
    enc = slugify_project_dir(w.root1)
    other = str(Path(w.root1).parent / "ClientCo-secret-folder")
    warnings = [f"vault_file: projects/{enc}/{CONV_A}/tool-results/x.txt of conversation {CONV_A} is no longer on disk",
                f"outside_scope: {other} holds a session of this project", f"plain: the folder {enc} moved",
                f"cwd: {w.root1} is the working folder"]
    manifest = dataclasses.replace(manifest, warnings=warnings,
                                   excluded=[{"kind": "policy", "store": "x", "reason": f"under {w.root1}"}])
    done = SO.finish(manifest, plan, S.ShareStats(), [])
    text = " ".join(done.warnings) + " ".join(str(e["reason"]) for e in done.excluded)
    assert enc not in text and str(w.root1) not in text and other not in text and "ClientCo" not in text
    assert done.warnings[0].startswith(f"vault_file: projects/_shared/{CONV_A}/tool-results/x.txt")
    assert SO.PATH_PLACEHOLDER in done.warnings[1] and SO.PATH_PLACEHOLDER in done.warnings[3]


def test_a_sentence_without_paths_is_kept() -> None:
    plan = type("P", (), {"files": [], "conversations": [], "subject": {}, "request": type("R", (), {"target": "u"})})
    assert SO.share_sentence("rows_changed: 3 of 4/5 rows", plan, "crate.json") == "rows_changed: 3 of 4/5 rows"
    assert SO.share_sentence(None, plan, "crate.json") is None
