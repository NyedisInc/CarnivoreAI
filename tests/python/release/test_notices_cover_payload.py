
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PAYLOAD = ROOT / "macOS" / "payload"
SPEC = importlib.util.spec_from_file_location("gen_notices", PAYLOAD / "gen_notices.py")
gn = importlib.util.module_from_spec(SPEC)
sys.modules["gen_notices"] = gn
SPEC.loader.exec_module(gn)

MACHO = bytes.fromhex("cffaedfe") + b"\0" * 12
PINS = {"python": {"version": "3.12.15", "build": "20261009"}, "tmux": {"version": "3.7c"}}
RECIPE = {
    "binary_rules": [{"glob": "bin/tmux", "component": "tmux"}],
    "components": [{"id": "tmux", "name": "tmux", "version": "{tmux.version}", "license": "ISC", "used_in": "bin/tmux",
                    "text_file": "tmux-ISC.txt"}],
}


def fixture_tree(root: Path, *, license_text: bool = True, stray_binary: bool = False) -> Path:
    tree = root / "payload-arm64"
    sp = gn.site_packages(tree)
    (tree / "bin").mkdir(parents=True)
    (tree / "bin" / "tmux").write_bytes(MACHO)
    (sp / "foo").mkdir(parents=True)
    (sp / "foo" / "_x.so").write_bytes(MACHO)
    dist = sp / "foo-1.0.dist-info"
    (dist / "licenses").mkdir(parents=True)
    (dist / "METADATA").write_text("Metadata-Version: 2.4\nName: foo\nVersion: 1.0\nLicense-Expression: MIT\nLicense-File: LICENSE\n\nbody\n")
    (dist / "RECORD").write_text("foo/_x.so,sha256=x,1\nfoo-1.0.dist-info/METADATA,,\n")
    if license_text:
        (dist / "licenses" / "LICENSE").write_text("MIT License. Permission is hereby granted, free of charge.")
    if stray_binary:
        (tree / "python" / "lib").mkdir(parents=True, exist_ok=True)
        (tree / "python" / "lib" / "libstray.dylib").write_bytes(MACHO)
    return tree


def build(tree: Path, lock: str):
    return gn.build_notices(trees=[tree], recipe=RECIPE, lock_text=lock, pins=PINS)


def test_fixture_covered(tmp_path: Path) -> None:
    entries = build(fixture_tree(tmp_path), "foo==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\n")
    names = {e.name: e for e in entries}
    assert names["foo"].license == "MIT" and "Permission is hereby granted" in names["foo"].text
    assert names["tmux"].license == "ISC" and names["tmux"].version == "3.7c"


def test_fixture_lock_entry_without_notice_fails(tmp_path: Path) -> None:
    with pytest.raises(gn.NoticeError, match="bar==2.0 is not installed"):
        build(fixture_tree(tmp_path), "foo==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\nbar==2.0 \\\n    --hash=sha256:" + "b" * 64 + "\n")


def test_fixture_binary_without_notice_fails(tmp_path: Path) -> None:
    with pytest.raises(gn.NoticeError, match="libstray.dylib: no notice covers"):
        build(fixture_tree(tmp_path, stray_binary=True), "foo==1.0 \\\n")


def test_fixture_wheel_without_license_text_fails(tmp_path: Path) -> None:
    with pytest.raises(gn.NoticeError, match="no license name or text"):
        build(fixture_tree(tmp_path, license_text=False), "foo==1.0 \\\n")


def test_marker_false_for_macos_is_not_required() -> None:
    lock = "colorama==0.4.6 ; sys_platform == 'win32' \\\nfoo==1.0 ; python_full_version < '3.14' \\\n"
    assert gn.parse_lock(lock) == [("foo", "1.0")]


def real_trees() -> tuple[Path, Path]:
    out = Path(os.environ.get("CARNIVORE_PAYLOAD_OUT") or Path(os.environ.get("CARNIVORE_PAYLOAD_CACHE", Path.home() / ".cache" / "carnivore-payload")) / "out")
    trees = (out / "payload-arm64", out / "payload-x86_64")
    missing = [t for t in trees if not t.is_dir()]
    assert not missing, f"payload trees missing: {missing}; run macOS/payload/build-payload.sh arm64 and x86_64 first"
    return trees


def test_real_payload_every_binary_and_wheel_has_a_notice() -> None:
    arm, x86 = real_trees()
    recipe = json.loads(gn.RECIPE.read_text())
    lock = gn.LOCK.read_text()
    entries = gn.build_notices(trees=[arm, x86], recipe=recipe, lock_text=lock, pins=gn.pins_for("arm64"))
    text = gn.render(entries, recipe)
    lines = {m.group(1) for m in re.finditer(r"^== (.+)$", text, re.M)}
    for e in entries:
        assert e.license.strip() and len(e.text.strip()) > 40, e.name
    for name, ver in gn.parse_lock(lock):
        assert any(l.startswith(f"{name} {ver} |") for l in lines), f"{name}=={ver} has no notice line"
    js = f"console.log(JSON.stringify(require({json.dumps(str(ROOT / 'macOS/scripts/payload-manifest.js'))}).buildManifest({json.dumps(str(arm.parent))})))"
    manifest = json.loads(subprocess.run(["node", "-e", js], check=True, capture_output=True, text=True).stdout)
    owner_names = {norm for norm in (gn.norm(n) for n, _ in gn.parse_lock(lock))}
    for arch, tree in (("arm64", arm), ("x86_64", x86)):
        owners = gn.record_owners(tree)
        assert manifest["trees"][arch]["binaries"], arch
        for b in manifest["trees"][arch]["binaries"]:
            owner = gn.binary_owner(b["path"], owners, recipe["binary_rules"])
            assert owner is not None, f"{arch}/{b['path']} has no notice"
            assert owner[1] in owner_names | {c["id"] for c in recipe["components"]}, f"{arch}/{b['path']} -> {owner}"
    with pytest.raises(gn.NoticeError, match="zzz-not-installed==1.0"):
        gn.build_notices(trees=[arm], recipe=recipe, lock_text=lock + "\nzzz-not-installed==1.0 \\\n", pins=gn.pins_for("arm64"))


def test_recipe_is_pinned_to_the_build_script() -> None:
    script = (PAYLOAD / "build-payload.sh").read_text()
    pin = lambda var: re.search(rf'readonly {var}="([^"]+)"', script).group(1)  # noqa: E731
    pinned = json.loads(gn.RECIPE.read_text())["pinned_for"]
    assert pinned == {"pbs_build": pin("PBS_TAG"), "python": pin("PY_VER"), "tmux": pin("TMUX_TAG").lstrip("v")}




def web_pkg(root: Path, name: str, *, license_file: bool = True) -> dict:
    d = root / "node_modules" / name
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"name": name, "version": "2.0.0", "license": "MIT" if license_file else "Apache-2.0"}))
    if license_file:
        (d / "LICENSE").write_text("MIT License. Permission is hereby granted, free of charge, to any person.")
    return {"name": name, "version": "2.0.0", "dir": str(d)}


def test_web_package_with_license_gets_a_notice(tmp_path: Path) -> None:
    (e,) = gn.web_entries([web_pkg(tmp_path, "widgetlib")])
    assert (e.kind, e.name, e.license) == ("web", "widgetlib", "MIT") and "Permission is hereby granted" in e.text


def test_web_package_without_license_text_fails(tmp_path: Path) -> None:
    pkg = web_pkg(tmp_path, "nolic", license_file=False)
    with pytest.raises(gn.NoticeError, match="nolic 2.0.0: no license name or license file"):
        gn.web_entries([pkg])


def test_build_notices_reports_a_web_package_with_no_notice(tmp_path: Path) -> None:
    client = tmp_path / "client"
    (client / "vendor").mkdir(parents=True)
    (client / "fonts").mkdir()
    with pytest.raises(gn.NoticeError, match="ghost 2.0.0"):
        gn.build_notices(trees=[fixture_tree(tmp_path)], recipe=RECIPE, lock_text="foo==1.0 \\\n", pins=PINS, client_dir=client,
                         web_packages=[web_pkg(tmp_path / "w", "ghost", license_file=False)])


def vendor_recipe(**over) -> dict:
    comp = {"name": "liba", "version": "1.0", "license": "MIT", "files": ["lib/a.js"], "text_file": "vendor/xterm-5.3.0.txt"} | over
    return {"components": [comp]}


def vendor_client(root: Path, *files: str) -> Path:
    for f in files:
        (root / "client" / "vendor" / f).parent.mkdir(parents=True, exist_ok=True)
        (root / "client" / "vendor" / f).write_text("x")
    return root / "client"


def test_vendored_file_with_no_component_fails(tmp_path: Path) -> None:
    with pytest.raises(gn.NoticeError, match=r"client/vendor/lib/b.js: no vendored.json component"):
        gn.vendored_entries(vendor_client(tmp_path, "lib/a.js", "lib/b.js"), vendor_recipe())


def test_vendored_library_without_license_text_fails(tmp_path: Path) -> None:
    with pytest.raises(gn.NoticeError, match="vendored liba 1.0: no license name or license text"):
        gn.vendored_entries(vendor_client(tmp_path, "lib/a.js"), vendor_recipe(text_file="vendor/missing.txt"))
    with pytest.raises(gn.NoticeError, match="vendored liba 1.0: no license name or license text"):
        gn.vendored_entries(vendor_client(tmp_path, "lib/a.js"), vendor_recipe(text_file=None))


def test_vendored_library_covered(tmp_path: Path) -> None:
    (e,) = gn.vendored_entries(vendor_client(tmp_path, "lib/a.js"), vendor_recipe())
    assert e.kind == "vendored" and e.license == "MIT" and "xterm.js authors" in e.text


def test_font_folder_without_license_fails(tmp_path: Path) -> None:
    (tmp_path / "client" / "fonts" / "mystery").mkdir(parents=True)
    (tmp_path / "client" / "fonts" / "mystery" / "f.woff2").write_bytes(b"x")
    with pytest.raises(gn.NoticeError, match="client/fonts/mystery: no recognizable license"):
        gn.font_entries(tmp_path / "client")


def test_real_browser_side_code_has_notices(tmp_path: Path) -> None:
    pkgs = gn.web_bundle_packages(ROOT / "web")
    names = {p["name"] for p in pkgs}
    assert {"svelte", "echarts", "zrender", "bits-ui"} <= names, names
    entries = gn.web_entries(pkgs) + gn.vendored_entries(ROOT / "client", json.loads(gn.VENDORED.read_text())) + gn.font_entries(ROOT / "client")
    text = gn.render(entries, json.loads(gn.RECIPE.read_text()))
    lines = {m.group(1) for m in re.finditer(r"^== (.+)$", text, re.M)}
    for p in pkgs:
        assert any(l.startswith(f"{p['name']} {p['version']} |") for l in lines), f"bundled {p['name']} {p['version']} has no notice line"
    for e in entries:
        assert e.license.strip() and len(e.text.strip()) > 40, e.name
    ghost = tmp_path / "ghost"
    ghost.mkdir()
    (ghost / "package.json").write_text(json.dumps({"name": "ghost-pkg", "version": "9.9.9"}))
    with pytest.raises(gn.NoticeError, match="ghost-pkg 9.9.9"):
        gn.web_entries(pkgs + [{"name": "ghost-pkg", "version": "9.9.9", "dir": str(ghost)}])


def test_vendored_recipe_matches_the_version_files() -> None:
    comps = {c["name"]: c["version"] for c in json.loads(gn.VENDORED.read_text())["components"]}
    xterm_md = (ROOT / "client/vendor/xterm/VERSION.md").read_text()
    for m in re.finditer(r"^\| \S+ \| (xterm\S*) \| (\S+) \|", xterm_md, re.M):
        assert comps.get(m.group(1)) == m.group(2), m.group(0)
    cm_md = (ROOT / "client/vendor/codemirror/VERSION.md").read_text()
    for m in re.finditer(r"^\| (@\S+) \| (\d+\.\d+\.\d+)", cm_md, re.M):
        assert comps.get(m.group(1)) == m.group(2), m.group(0)
