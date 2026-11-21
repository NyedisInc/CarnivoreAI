
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from src.plugins.host import identity, sideload, sideload_routes
from src.plugins.runtime import sandbox

SHIPPED = frozenset({"huddle", "unread"})
KEY_A, KEY_B = "5F52A0A0A0A0A0A0", "9C11B1B1B1B1B1B1"


def _register(state: Path, name: str, catalog_id: str, **kw: object) -> identity.InstallRecord:
    return identity.register_install(state, name, catalog_id, SHIPPED, **kw)


def _code(state: Path, name: str, catalog_id: str, **kw: object) -> Optional[str]:
    try:
        _register(state, name, catalog_id, **kw)
    except identity.InstallRefused as exc:
        return exc.code
    return None


@pytest.mark.parametrize("name,catalog_id,sideload_flag,code", [
    ("clock", "acme/clock", False, None),
    ("clock", "ACME/clock", False, "id_invalid"),
    ("cafe", "acme/café", False, "id_invalid"),
    ("clock", "acme.io/clock", False, "id_invalid"),
    ("clock", "ac_me/clock", False, "id_invalid"),
    ("clock", "a/clock", False, "id_invalid"),
    ("clock", "clock", False, "id_invalid"),
    ("clock", "local/other", True, "id_invalid"),
    ("clock", "local/clock", False, "id_local_only"),
    ("clock", "acme/clock", True, "id_local_only"),
    ("clock", "local/clock", True, None),
    ("clock", "plugins/clock", False, "publisher_reserved"),
    ("clock", "huddle/clock", False, "publisher_reserved"),
    ("clock", "carnivore/clock", False, None),
])
def test_id_grammar_and_namespace(tmp_path: Path, name: str, catalog_id: str, sideload_flag: bool, code: Optional[str]) -> None:
    assert _code(tmp_path, name, catalog_id, sideload=sideload_flag) == code
    assert (identity.lookup(tmp_path, name) is not None) == (code is None)


def test_a_sideload_cannot_take_a_name_a_catalog_install_holds(tmp_path: Path) -> None:
    held = _register(tmp_path, "clock", "acme/clock", publisher_key_id=KEY_A)
    with pytest.raises(identity.InstallRefused) as caught:
        _register(tmp_path, "clock", "local/clock", sideload=True, source="/src/clock")
    assert caught.value.code == "name_taken" and "acme/clock" in str(caught.value) and "rename yours" in str(caught.value)
    assert identity.lookup(tmp_path, "clock").uuid == held.uuid


def test_reinstall_with_the_same_publisher_key_gets_its_data_back(tmp_path: Path) -> None:
    first = _register(tmp_path, "clock", "acme/clock", publisher_key_id=KEY_A)
    assert _register(tmp_path, "clock", "acme/clock", publisher_key_id=KEY_A).uuid == first.uuid


def test_reinstall_with_a_different_publisher_key_gets_a_fresh_uuid(tmp_path: Path) -> None:
    first = _register(tmp_path, "clock", "acme/clock", publisher_key_id=KEY_A)
    old_data = identity.data_dir(tmp_path, first.uuid)
    (old_data / "files").mkdir(parents=True)
    (old_data / "files" / "note.txt").write_text("kept")
    second = _register(tmp_path, "clock", "acme/clock", publisher_key_id=KEY_B)
    assert second.uuid != first.uuid and second.publisher_key_id == KEY_B
    assert identity.lookup(tmp_path, "clock").uuid == second.uuid
    assert (old_data / "files" / "note.txt").read_text() == "kept"


def test_a_row_from_before_the_rule_inherits_once_and_is_stamped(tmp_path: Path) -> None:
    uuid_hex = "b" * 32
    ledger = tmp_path / "cplugs" / identity.LEDGER_FILE
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"version": 1, "installs": {"clock": {"uuid": uuid_hex, "catalog_id": "acme/clock"}}}))
    assert _register(tmp_path, "clock", "acme/clock", publisher_key_id=KEY_A).uuid == uuid_hex
    assert identity.lookup(tmp_path, "clock").publisher_key_id == KEY_A
    assert _register(tmp_path, "clock", "acme/clock", publisher_key_id=KEY_B).uuid != uuid_hex


def test_a_sideload_inherits_only_from_the_same_source_realpath(tmp_path: Path) -> None:
    first = _register(tmp_path, "clock", "local/clock", sideload=True, source="/work/clock")
    assert _register(tmp_path, "clock", "local/clock", sideload=True, source="/work/clock").uuid == first.uuid
    assert _register(tmp_path, "clock", "local/clock", sideload=True, source="/elsewhere/clock").uuid != first.uuid


def _plugin(folder: Path, plugin_id: str = "devclock") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cplug.json").write_text(json.dumps({"schema": 1, "id": plugin_id, "name": "Dev Clock", "description": "Tells the time.", "version": "1.0.0",
                                                   "entry": "main.py", "tools": [], "permissions": {"app": ["notify"]}}))
    (folder / "main.py").write_text("print('tick')\n")


def test_a_sideload_lands_as_local_whatever_its_manifest_declares(tmp_path: Path) -> None:
    state, src = tmp_path / "state", tmp_path / "src" / "devclock"
    _plugin(src, "acme/devclock")
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload_routes.name_of(src, None)
    assert caught.value.code == "source_missing"
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload_routes._sync_blocking(state, src, "devclock")
    assert caught.value.code == "manifest_invalid" and identity.lookup(state, "devclock") is None
    _plugin(src, "devclock")
    assert sideload_routes._sync_blocking(state, src, None)["name"] == "devclock"
    record = identity.lookup(state, "devclock")
    assert record.catalog_id == "local/devclock" and record.source == str(src)


def test_a_symlink_in_a_source_folder_is_refused(tmp_path: Path) -> None:
    src, outside = tmp_path / "src" / "devclock", tmp_path / "secret.txt"
    _plugin(src)
    outside.write_text("secret")
    (src / "leak.txt").symlink_to(outside)
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload.stage(tmp_path / "state", "devclock", src)
    assert caught.value.code in {"source_unsafe", "manifest_invalid"}
    link = tmp_path / "link"
    link.symlink_to(src)
    with pytest.raises(sideload.SideloadRefused):
        sideload.stage(tmp_path / "state", "devclock", link)


def _layout(root: Path) -> sandbox.Layout:
    interp = sandbox.find_interpreter()
    runtime_dir, code = root / "rt", root / "code"
    data = root / "cplugs" / ("c" * 32)
    for folder in (runtime_dir, code, data / "files"):
        folder.mkdir(parents=True)
    return sandbox.Layout(interp, sandbox.stdlib_root(interp), runtime_dir, code, data)


def test_no_host_file_is_left_in_a_data_folder(tmp_path: Path) -> None:
    root = Path(os.path.realpath(tmp_path))
    try:
        layout = _layout(root)
    except sandbox.SandboxUnavailable:
        pytest.skip("no framework Python here")
    (layout.data_dir / "profile.sb").write_text("old")
    written = sandbox.write_profile(layout)
    assert written == root / "cplugs" / "profiles" / ("c" * 32 + ".sb") and written.read_text() == sandbox.render_profile(layout)
    assert sorted(p.name for p in layout.data_dir.iterdir()) == ["files"]
    sandbox.remove_profile(layout.data_dir)
    assert not written.exists()
    sandbox.remove_profile(layout.data_dir)


def test_profiles_is_a_host_word_and_not_a_removed_plugin(tmp_path: Path) -> None:
    assert _code(tmp_path, "profiles", "acme/profiles") == "name_reserved"


WRITE_SCRIPT = (
    "import json,sys\n"
    "out={}\n"
    "for key,path in (('profile',sys.argv[1]),('state',sys.argv[2]),('ledger',sys.argv[3])):\n"
    " try:\n  open(path,'w').write('pwned'); out[key]=True\n"
    " except OSError:\n  out[key]=False\n"
    "try:\n open(sys.argv[4]+'/ok','w').write('x'); out['files']=True\n"
    "except OSError:\n out['files']=False\n"
    "print(json.dumps(out))\n"
)


def test_a_sandboxed_sidecar_cannot_write_its_profile_state_or_install_record(tmp_path: Path) -> None:
    root = Path(os.path.realpath(tmp_path))
    try:
        layout = _layout(root)
    except sandbox.SandboxUnavailable:
        pytest.skip("no framework Python here")
    if not sandbox.probe().ok:
        pytest.skip("sandbox-exec is not usable here")
    profile = sandbox.write_profile(layout)
    state_json, ledger = root / "cplugs" / "state.json", root / "cplugs" / identity.LEDGER_FILE
    state_json.write_text("{}")
    ledger.write_text("{}")
    argv = ["/usr/bin/sandbox-exec", "-f", str(profile), str(layout.interpreter), "-I", "-B", "-c", WRITE_SCRIPT,
            str(profile), str(state_json), str(ledger), str(layout.files_dir)]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=sandbox.allow_env(layout), check=False)
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert seen == {"profile": False, "state": False, "ledger": False, "files": True}, (seen, done.stderr[-300:])
    assert state_json.read_text() == "{}" and ledger.read_text() == "{}" and profile.read_text() == sandbox.render_profile(layout)
