
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request


def _listing(folder: Path) -> set:
    return {str(p) for p in folder.rglob("*") if p.is_file()} if folder.is_dir() else set()


def test_an_encrypted_export_round_trips(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    owner_id, owner_rcpt = cf.generate()
    other_id, _ = cf.generate()
    env = env_for(w, keyHint="1Password: crate key")
    temp_before = _listing(Path(tempfile.gettempdir()) / "carnivore-crate-drill")
    seen = []
    original = os.open

    def watching(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            seen.append(str(path))
        return original(path, flags, *args, **kwargs)

    os.open = watching
    try:
        result = run_export(env, build_plan(env, session_request(encrypt=True, recipients=(owner_rcpt,))), JobHandle("e"))
    finally:
        os.open = original
    assert result.encrypted and result.path.name.endswith(".crate.age")
    assert result.path.read_bytes().startswith(cf.constants.AGE_MAGIC)
    assert all(p.endswith((".crate.age.partial", ".sha256.partial", ".README.txt.partial")) for p in seen), seen
    assert _listing(Path(tempfile.gettempdir()) / "carnivore-crate-drill") == temp_before
    assert cf.verify(result.path, "full", expected_sha256=result.sha256, identity=owner_id).ok
    assert cf.verify(result.path, "quick", expected_sha256=result.sha256).ok
    wrong = cf.verify(result.path, "full", expected_sha256=result.sha256, identity=other_id)
    assert wrong.codes == ["wrong_key"]
    readme = Path(f"{result.path}.README.txt").read_text()
    assert owner_rcpt in readme and "1Password: crate key" in readme and readme.count("age1") == 1
    assert sorted(p.name for p in result.path.parent.iterdir()) == sorted(
        [result.path.name, f"{result.path.name}.sha256", f"{result.path.name}.README.txt"])
    with cf.open_crate(result.path, owner_id) as reader:
        assert reader.manifest.bundle_id == result.bundle_id and owner_rcpt not in reader.read_member("crate.json").decode()
