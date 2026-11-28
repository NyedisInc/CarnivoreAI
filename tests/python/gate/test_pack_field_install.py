
from __future__ import annotations

import io
import tarfile
from pathlib import Path


from scripts.gate import field_installs as fi
from src.core.skills.digest import digest_directory
from src.plugins.host import install_gates

ROOT_DIR = "CarnivoreAI-Catalog-abc123"
TOML_CLOCK = (
    'schema = 2\n'
    'id = "clock"\n'
    'name = "Clock"\n'
    'version = "1.0.0"\n'
    'kind = "plugin"\n'
    'description = "Tells the time."\n'
    'author = "harbor"\n'
    'license = "MIT"\n'
    'min_app_version = "1.16.6"\n\n'
    '[run]\n'
    'cmd = ["python3", "clock_main.py"]\n'
    'mode = "rpc"\n\n'
    '[permissions]\n'
    'write = ["notify"]\n\n'
    '[permissions.reasons]\n'
    'notify = "tells you once when the hour turns"\n\n'
    '[ui]\n'
    'topics = ["tick"]\n\n'
    '[ui.page]\n'
    'menu = "face"\n'
    'main = "face"\n\n'
    '[[ui.views]]\n'
    'name = "face"\n'
    'surfaces = ["panel"]\n'
    'files = ["index.html"]\n\n'
    '[[mcp.tools]]\n'
    'name = "clock_now"\n'
    'description = "The time."\n'
    'gate = "read"\n'
    'inputSchema = { type = "object", properties = {}, additionalProperties = false }\n'
)
MAIN = b'"""clock."""\nfrom cplug_sdk import Plugin\n\nplugin = Plugin()\n'


def _v2_folder(tmp: Path) -> Path:
    folder = tmp / "pkg"
    (folder / "views" / "face").mkdir(parents=True)
    (folder / "carnivore.toml").write_text(TOML_CLOCK, encoding="utf-8")
    (folder / "clock_main.py").write_bytes(MAIN)
    (folder / "views" / "face" / "index.html").write_text("<p>face</p>\n", encoding="utf-8")
    return folder


def test_v2_page_plugin_passes_current_install_gate_and_enforces_floor(tmp_path: Path) -> None:
    folder = _v2_folder(tmp_path)
    facts = install_gates.evaluate("harbor/clock", folder).facts
    assert facts["id"] == "clock" and [t["name"] for t in facts["tools"]] == ["clock_now"]
    refusal, _note = fi.floor_check("1.16.6", fi.FIELD_FLOOR, upcoming=False)
    assert "1.16.6" in refusal
    assert fi.floor_check("1.16.6", "1.16.7", upcoming=False) == ("", "")


def test_field_floor_tag_refuses_v2_only_tarball(tmp_path: Path) -> None:
    folder = _v2_folder(tmp_path)
    core = fi.export_core(f"v{fi.FIELD_FLOOR}", tmp_path / "core")
    tarball = tmp_path / "x.tgz"
    with tarfile.open(tarball, "w:gz") as tar:
        for base in ("plugins/harbor/clock", "cplugs/harbor/clock"):
            for f in sorted(folder.rglob("*")):
                if not f.is_file():
                    continue
                rel = f.relative_to(folder).as_posix()
                info = tarfile.TarInfo(f"{ROOT_DIR}/{base}/{rel}")
                body = f.read_bytes()
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
    job = {
        "id": "harbor/clock",
        "kind": "cplug",
        "name": "clock",
        "publisher": "harbor",
        "v": "1.0.0",
        "src_path": "plugins/harbor/clock",
        "repo": "x/y",
        "commit": "abc123",
        "digest": digest_directory(folder)[0],
        "key_id": "",
    }
    (res,) = fi.run_cell(f"v{fi.FIELD_FLOOR}", core, [job], {"harbor/clock": str(tarball)})
    assert not res["ok"] and res["step"] == "stage" and "cplug.json" in res["detail"], res
