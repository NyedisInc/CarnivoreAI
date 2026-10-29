
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from unittest import mock

from src.cplugs.crate import policy as P
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import ExportRequest, build_plan
from src.cplugs.crate.publish import age_readme, sha_sidecar
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from tests.python.cplugs.crate.crate_world import env_for, make_world
from tests.python.cplugs.crate import golden_extras as X
from tests.python.crate_format import golden_read as G
from tests.python.inventory.world import UUID_A

GOLDEN_EPOCH = 1792267200
INSTALL_ID = "00000000-0000-4000-8000-000000000001"
MACHINE_LABEL = "golden-builder"
APP_VERSION = "golden-v1"
KEY_HINT = "the golden test key is derived from a public seed in tests/python/crate_format/golden_read.py"
SUMS = "SHA256SUMS"
EXPECTED = "expected"


class GoldenRefused(Exception):
    pass


@dataclass(frozen=True)
class Fixture:

    name: str
    scope: str
    variant: str
    codec: Optional[str]
    encrypt: bool
    hex8: str

    def bundle_id(self) -> str:
        prefix = "share" if self.variant == P.SHARE else "crate"
        return f"{prefix}-20261017T200000Z-{self.scope}-{self.hex8}"


FIXTURES = (
    Fixture("session-own.crate", "session", P.OWN, "lzma", False, "601d0001"),
    Fixture("project-own.crate", "project", P.OWN, "zstd", False, "601d0002"),
    Fixture("project-share.crate", "project", P.SHARE, "zstd", False, "601d0003"),
    Fixture("session-own.crate.age", "session", P.OWN, None, True, "601d0004"),
)


def required_vocabulary() -> Dict[str, List[str]]:
    consts = cf.constants
    entries = {key.split("/", 1)[1] for key, rule in P.POLICY.items() if key.startswith("entry/") and rule.own == P.CARRY}
    entries.add(cs.STORE_THEME_DOTFILE)
    return {"roles": sorted(consts.ROLES), "homes": sorted(consts.HOME_KINDS), "member_kinds": sorted(G.WRITER_KINDS),
            "encodings": sorted(G.ENCODINGS), "entry_stores": sorted(entries), "lines_sources": sorted(consts.LINES_SOURCES),
            "codecs": sorted(set(G.CODEC_OF_SUFFIX.values())), "variants": sorted(consts.VARIANTS)}


def missing_vocabulary(seen: Dict[str, List[str]], required: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {axis: sorted(set(values) - set(seen.get(axis, ()))) for axis, values in required.items()
            if set(values) - set(seen.get(axis, ()))}


def builder_needles() -> List[str]:
    host = socket.gethostname()
    return sorted({str(Path.home()), getpass.getuser(), host, host[:-len(".local")] if host.endswith(".local") else host})


def _export_all(world_root: Path, staging: Path) -> None:
    world_root.mkdir()
    w = make_world(world_root)
    share_home = world_root / "home-golden"
    share_home.mkdir()
    X.add_golden_extras(w, str(share_home))
    env = env_for(w)
    with mock.patch.object(cs, "install_identity", lambda *, state_dir: (INSTALL_ID, MACHINE_LABEL)), \
            mock.patch.object(cs, "app_version", lambda: APP_VERSION), \
            mock.patch.object(Path, "home", staticmethod(lambda: share_home)):
        for fx in FIXTURES:
            target = w.root1 if fx.scope == "project" else UUID_A
            request = ExportRequest(fx.scope, target, fx.variant, encrypt=fx.encrypt,
                                    recipients=(G.test_recipient(),) if fx.encrypt else ())
            plan = build_plan(env, request)
            if not plan.ok:
                raise GoldenRefused(f"{fx.name}: the plan is blocked: {plan.blockers}")
            result = run_export(env, plan, JobHandle(fx.name), codec=fx.codec, created_epoch=GOLDEN_EPOCH,
                                bundle_id=fx.bundle_id())
            shutil.copyfile(result.path, staging / fx.name)


def _case_problems(staging: Path) -> List[str]:
    problems, token = [], X.placeholder_token().encode()
    for fx in FIXTURES:
        path = staging / fx.name
        text = b"\n".join(data for _name, data in G.member_texts(path))
        if X.SECRET_VALUE.encode() in text:
            problems.append(f"{fx.name}: the secret column value was carried")
        kept = [token in text, X.IMAGE_DATA.encode() in text]
        if fx.scope == "project" and kept != [fx.variant == P.OWN] * 2:
            problems.append(f"{fx.name}: the token or image is wrong for a {fx.variant} crate")
        with cf.open_crate(path, G.identity_for(path)) as reader:
            if fx.variant == P.SHARE:
                red = reader.manifest.as_json().get("redaction") or {}
                if not ((red.get("findings") or {}).get("github_token") and red.get("images_stripped")
                        and red.get("home_scrubbed")):
                    problems.append(f"{fx.name}: the redaction block misses the token, the image or the home")
                continue
            tables = reader.tables()
            if "token_hash" not in tables["carnivore.db"]["work_item_waits"].omitted_columns:
                problems.append(f"{fx.name}: work_item_waits.token_hash is not listed as left out")
            if X.EMPTY_TABLE in tables.get("carnivore.db", {}) or any(X.EMPTY_TABLE in m.name for m in reader.members()):
                problems.append(f"{fx.name}: the empty table has a record or a part")
            if fx.scope == "project" and b'"files[].path"' not in reader.read_member(cf.constants.M_PATHS):
                problems.append(f"{fx.name}: paths.jsonl lists no json path value")
    return problems


def _write_text_files(staging: Path) -> Dict[str, List[str]]:
    crates = [staging / fx.name for fx in FIXTURES]
    problems = _case_problems(staging)
    if problems:
        raise GoldenRefused(f"the golden cases are not all in the fixtures: {problems}")
    for path in crates:
        sha = G.sha256_file(path)
        (staging / f"{path.name}.sha256").write_bytes(sha_sidecar(sha, path.name))
        if path.name.endswith(".age"):
            (staging / f"{path.name}.README.txt").write_bytes(age_readme(path.name, [G.test_recipient()], KEY_HINT))
    (staging / EXPECTED).mkdir()
    for path in crates:
        (staging / EXPECTED / f"{path.name}.json").write_text(_pretty(G.listing(path)))
    seen, required = G.coverage(crates), required_vocabulary()
    missing = missing_vocabulary(seen, required)
    if missing:
        raise GoldenRefused(f"the fixtures miss part of the v1 vocabulary: {missing}")
    (staging / EXPECTED / "coverage.json").write_text(_pretty({"seen": seen, "required": required}))
    (staging / "README.md").write_text(_readme())
    _write_sums(staging)
    return seen


def _pretty(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sums_text(folder: Path) -> str:
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.name != SUMS)
    return "".join(f"{G.sha256_file(p)}  {p.relative_to(folder).as_posix()}\n" for p in files)


def _write_sums(folder: Path) -> None:
    (folder / SUMS).write_text(sums_text(folder))


def _readme() -> str:
    names = "\n".join(f"- `{fx.name}`: {fx.scope}, {fx.variant}, codec {fx.codec or 'default'}"
                      f"{', encrypted to the test recipient' if fx.encrypt else ''}" for fx in FIXTURES)
    return (
        "# crate v1 golden fixtures\n\n"
        "Never regenerate, never edit, never delete. A new minor version gets its own folder (`v1.1/`).\n"
        "`tests/python/crate_format/test_golden_v1.py` pins the sha256 of `SHA256SUMS`, so an edited fixture fails.\n\n"
        "Written once by:\n\n"
        "    venv/bin/python3 -m tests.python.cplugs.crate.golden_build --write tests/fixtures/crate/v1\n\n"
        "The world is the inventory test world (`tests/python/inventory/world_build.py`) plus\n"
        "`tests/python/cplugs/crate/golden_extras.py`, built in a fresh temporary folder, with the clock\n"
        f"({GOLDEN_EPOCH}), install id, machine label, app version and bundle ids injected.\n\n"
        "The test key is not committed: the identity is X25519 secret = sha256 of the seed in\n"
        "`tests/python/crate_format/golden_read.py`, bech32 encoded by `crate_crypto.keys.encode_identity`.\n\n"
        f"{names}\n\n"
        "Beside each crate: `<file>.sha256`; beside the encrypted one, its README sidecar.\n"
        "`expected/<file>.json` is what each crate lists; `expected/coverage.json` the vocabulary they use.\n"
    )


def build(out: Path) -> Dict[str, List[str]]:
    if out.exists():
        raise GoldenRefused(f"{out} already exists: fixtures are written once")
    needles = builder_needles()
    with tempfile.TemporaryDirectory(prefix="crate-golden-") as tmp:
        root = Path(tmp).resolve()
        staging = root / "staging"
        staging.mkdir()
        _export_all(root / "world", staging)
        seen = _write_text_files(staging)
        files = sorted(p for p in staging.rglob("*") if p.is_file())
        hits = G.identity_hits(files, needles)
        if hits:
            raise GoldenRefused(f"a fixture names the building machine: {sorted(set(hits))[:5]}")
        shutil.copytree(staging, out)
    return seen


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tests.python.cplugs.crate.golden_build")
    parser.add_argument("--write", required=True, help="the new fixture folder, such as tests/fixtures/crate/v1")
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
