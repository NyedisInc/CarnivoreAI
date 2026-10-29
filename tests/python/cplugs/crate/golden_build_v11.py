
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from unittest import mock

from src.cplugs.crate import policy as P
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import ExportRequest, build_plan
from src.cplugs.crate.publish import sha_sidecar
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_sources as cs
from tests.python.cplugs.crate import golden_extras as X
from tests.python.cplugs.crate.crate_world import env_for, make_world
from tests.python.cplugs.crate.golden_build import (
    APP_VERSION, EXPECTED, GOLDEN_EPOCH, INSTALL_ID, MACHINE_LABEL, SUMS, GoldenRefused, Fixture, _pretty, _write_sums,
    builder_needles,
)
from tests.python.cplugs.crate.test_plugin_data import BOARDS, DRAFTS, SLUG_MINE, SLUG_THEIRS, board, use
from tests.python.crate_format import golden_read as G
from tests.python.inventory.world import UUID_A

FIXTURES = (
    Fixture("project-own.crate", "project", P.OWN, "zstd", False, "611d0001"),
    Fixture("session-own.crate", "session", P.OWN, "lzma", False, "611d0002"),
)
PROJECT_TREE = {"README.md": b"# golden app\n", "src/app.py": b"print('golden')\n", "notes/empty.txt": b""}


def _prepare_world(world_root: Path) -> object:
    world_root.mkdir()
    w = make_world(world_root)
    share_home = world_root / "home-golden"
    share_home.mkdir()
    X.add_golden_extras(w, str(share_home))
    root = Path(w.root1)
    for rel, data in PROJECT_TREE.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    os.symlink("src/app.py", root / "latest")
    boards = world_root / "boards-root"
    board(boards, SLUG_MINE, w.item_p)
    board(boards, SLUG_THEIRS, w.item_d)
    drafts = Path(w.state) / "cplugs" / "synth" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / f"{SLUG_MINE}.json").write_text('{"rev": 1}')
    w.boards_root, w.share_home = boards, share_home
    use(w, [BOARDS, DRAFTS])
    return w


def _export_all(world_root: Path, staging: Path) -> None:
    w = _prepare_world(world_root)
    env = env_for(w)
    with mock.patch.object(cs, "install_identity", lambda *, state_dir: (INSTALL_ID, MACHINE_LABEL)), \
            mock.patch.object(cs, "app_version", lambda: APP_VERSION), \
            mock.patch.object(Path, "home", staticmethod(lambda: w.share_home)):
        for fx in FIXTURES:
            target = w.root1 if fx.scope == "project" else UUID_A
            request = ExportRequest(fx.scope, target, fx.variant, include_project_files=fx.scope == "project")
            plan = build_plan(env, request)
            if not plan.ok:
                raise GoldenRefused(f"{fx.name}: the plan is blocked: {plan.blockers}")
            result = run_export(env, plan, JobHandle(fx.name), codec=fx.codec, created_epoch=GOLDEN_EPOCH,
                                bundle_id=fx.bundle_id())
            shutil.copyfile(result.path, staging / fx.name)


def _check_v11_vocabulary(staging: Path) -> Dict[str, List[str]]:
    seen = G.coverage([staging / fx.name for fx in FIXTURES])
    homes = set(seen["homes"])
    if "project" not in homes or not any(h.startswith("plugin-") for h in homes):
        raise GoldenRefused(f"the v1.1 fixtures lack the project home or a plugin home: {sorted(homes)}")
    if not {"project_file", "plugin_file"} <= set(seen["roles"]):
        raise GoldenRefused(f"the v1.1 fixtures lack a new role: {seen['roles']}")
    return seen


def build(out: Path) -> Dict[str, List[str]]:
    if out.exists():
        raise GoldenRefused(f"{out} already exists: fixtures are written once")
    needles = builder_needles()
    with tempfile.TemporaryDirectory(prefix="crate-golden11-") as tmp:
        root = Path(tmp).resolve()
        staging = root / "staging"
        staging.mkdir()
        _export_all(root / "world", staging)
        seen = _check_v11_vocabulary(staging)
        crates = [staging / fx.name for fx in FIXTURES]
        (staging / EXPECTED).mkdir()
        for path in crates:
            (staging / f"{path.name}.sha256").write_bytes(sha_sidecar(G.sha256_file(path), path.name))
            (staging / EXPECTED / f"{path.name}.json").write_text(_pretty(G.listing(path)))
        (staging / EXPECTED / "coverage.json").write_text(_pretty({"seen": seen}))
        (staging / "README.md").write_text(_readme())
        _write_sums(staging)
        hits = G.identity_hits(sorted(p for p in staging.rglob("*") if p.is_file()), needles)
        if hits:
            raise GoldenRefused(f"a fixture names the building machine: {sorted(set(hits))[:5]}")
        shutil.copytree(staging, out)
    return seen


def _readme() -> str:
    names = "\n".join(f"- `{fx.name}`: {fx.scope}, {fx.variant}, codec {fx.codec}" for fx in FIXTURES)
    return (
        "# crate v1.1 golden fixtures\n\n"
        "Never regenerate, never edit, never delete. `tests/python/crate_import/test_s0_seams.py` pins the sha256 of\n"
        "`SHA256SUMS`, so an edited fixture fails. v1.1 added the `project` home, plugin homes, three roles, one member and one\n"
        "manifest key (`docs/crate-format.md`, section 11).\n\n"
        "Written once by:\n\n"
        "    venv/bin/python3 -m tests.python.cplugs.crate.golden_build_v11 --write tests/fixtures/crate/v1.1\n\n"
        "The world is the v1 golden world (`golden_build.py`) plus a project folder of files and a synthetic plugin `synth`\n"
        f"that keeps boards and drafts, with the clock ({GOLDEN_EPOCH}), install id, machine label, app version and bundle\n"
        "ids injected.\n\n"
        f"{names}\n\n"
        "Beside each crate: `<file>.sha256`. `expected/<file>.json` is what each crate lists; `expected/coverage.json` the vocabulary.\n"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tests.python.cplugs.crate.golden_build_v11")
    parser.add_argument("--write", required=True, help="the new fixture folder, tests/fixtures/crate/v1.1")
    args = parser.parse_args(argv)
    try:
        build(Path(args.write))
    except GoldenRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.write}; SHA256SUMS sha256 {hashlib.sha256((Path(args.write) / SUMS).read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
