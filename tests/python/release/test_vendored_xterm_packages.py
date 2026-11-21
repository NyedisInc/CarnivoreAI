
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
VENDOR = ROOT / "client" / "vendor" / "xterm"
FILES = ["xterm.css", "xterm.js", "xterm-addon-fit.js", "xterm-addon-webgl.js", "xterm-addon-unicode11.js", "xterm-addon-search.js",
         "xterm-addon-web-links.js"]
GLOBALS = {
    "xterm-addon-fit.js": "FitAddon",
    "xterm-addon-webgl.js": "WebglAddon",
    "xterm-addon-unicode11.js": "Unicode11Addon",
    "xterm-addon-search.js": "SearchAddon",
    "xterm-addon-web-links.js": "WebLinksAddon",
}


def _sha(name: str) -> str:
    return hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()


def _version_md_rows() -> dict[str, tuple[str, str]]:
    text = (VENDOR / "VERSION.md").read_text()
    rows = {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(r"^\| (\S+) \| (\S+) \| (\S+) \|", text, re.M) if m.group(1) in FILES}
    return rows


def test_version_md_names_only_maintained_packages() -> None:
    rows = _version_md_rows()
    assert sorted(rows) == sorted(FILES), "VERSION.md must record all seven files"
    deprecated = {f: pkg for f, (pkg, _v) in rows.items() if not pkg.startswith("@xterm/")}
    assert deprecated == {}, f"deprecated bare xterm packages recorded: {deprecated}"


def test_fetch_script_downloads_only_from_the_maintained_packages() -> None:
    script = (ROOT / "scripts" / "xterm-vendor" / "fetch.sh").read_text()
    urls = re.findall(r"https://cdn\.jsdelivr\.net/npm/(\S+?)@", script)
    assert len(urls) == 7
    assert all(u.startswith("@xterm/") for u in urls), urls


@pytest.mark.parametrize("name", FILES)
def test_recorded_hashes_match_the_files_on_disk(name: str) -> None:
    script = (ROOT / "scripts" / "xterm-vendor" / "fetch.sh").read_text()
    md = (VENDOR / "VERSION.md").read_text()
    sha = _sha(name)
    assert re.search(rf"^{re.escape(name)}\|\S+\|{sha}$", script, re.M), f"fetch.sh does not pin {name} at {sha}"
    assert f"{sha}  {name}" in md, f"VERSION.md does not record {name} at {sha}"


@pytest.mark.parametrize("name,global_name", sorted(GLOBALS.items()))
def test_each_addon_still_defines_the_global_the_client_reads(name: str, global_name: str) -> None:
    assert global_name in (VENDOR / name).read_text(), f"{name} no longer defines {global_name}"


def test_notices_name_the_maintained_packages_and_versions() -> None:
    comps = json.loads((ROOT / "macOS" / "payload" / "notices" / "vendored.json").read_text())["components"]
    by_file = {f: (c["name"], c["version"]) for c in comps for f in c["files"] if f.startswith("xterm/")}
    rows = _version_md_rows()
    for name in FILES:
        assert by_file.get(f"xterm/{name}") == rows[name], f"{name}: notices {by_file.get(f'xterm/{name}')} vs VERSION.md {rows[name]}"


def test_the_check_can_go_red_on_a_deprecated_name() -> None:
    assert not "xterm-addon-fit".startswith("@xterm/") and not "xterm".startswith("@xterm/")
