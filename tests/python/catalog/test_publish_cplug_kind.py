
from __future__ import annotations

import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from src.core import message_model_secrets
from src.core.catalog import publish_prepare_kinds as kinds
from src.plugins.host import install_gates
from src.plugins.sdk import api_contract

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "cplugs" / "warezsmoke"
sys.path.insert(0, str(ROOT / "hosted" / "catalog" / "api"))
sys.path.insert(0, str(ROOT / "hosted" / "catalog_index" / "tools"))
import validate_kinds  # noqa: E402
from validate_upload import UploadRefused  # noqa: E402
from index_builder import cplugs as index_cplugs  # noqa: E402
from index_builder.kind_errors import KindRefused  # noqa: E402


def _v2_toml(
    *,
    plugin_id: str = "warezsmoke",
    version: str = "1.0.0",
    api_version: int = 1,
    views_block: str = "",
) -> str:
    return (
        'schema = 2\n'
        f'id = {json.dumps(plugin_id)}\n'
        'name = "Warez Smoke"\n'
        f'version = {json.dumps(version)}\n'
        'kind = "plugin"\n'
        'description = "Smoke test plugin."\n'
        'author = "harbor"\n'
        'license = "MIT"\n'
        f'api_version = {api_version}\n\n'
        '[run]\n'
        'cmd = ["python3", "warezsmoke_main.py"]\n'
        'mode = "rpc"\n\n'
        '[[mcp.tools]]\n'
        f'name = "{plugin_id}_ping"\n'
        'description = "Ping."\n'
        'gate = "read"\n'
        'inputSchema = { type = "object", properties = {} }\n'
        f'{views_block}'
    )


def _copy_v2(tmp_path: Path, **toml_kw) -> Path:
    dest = tmp_path / "warezsmoke"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "carnivore.toml").write_text(_v2_toml(**toml_kw), encoding="utf-8")
    (dest / "warezsmoke_main.py").write_text((FIXTURE / "warezsmoke_main.py").read_text(encoding="utf-8"), encoding="utf-8")
    (dest / "README.md").write_text((FIXTURE / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def _copy_v1(tmp_path: Path, **sidecar_edits) -> Path:
    dest = tmp_path / "warezsmoke_v1"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "cplug.json").write_text(
        json.dumps({
            "schema": 1,
            "id": "warezsmoke",
            "name": "warez smoke",
            "description": "Smoke test plugin.",
            "version": "1.0.0",
            "entry": "warezsmoke_main.py",
            "tools": [],
            "permissions": {"app": ["notify"]},
            "default_enabled": False,
        }),
        encoding="utf-8",
    )
    doc = {
        "kind": "cplug",
        "id": "local/warezsmoke",
        "name": "warez smoke",
        "description": "Smoke test plugin.",
        "version": "1.0.0",
        "api_version": 1,
        "min_app_version": "1.12.20",
        "author": "harbor",
        "license": "MIT",
        "tier": "local",
        "scope": ["global"],
        "icon": "plug",
        "default_enabled": False,
        "runtime": {"kind": "process", "language": "python", "entry": "warezsmoke_main.py"},
        "network_hosts": [],
        "permissions": [{"name": "notify", "reason": "smoke notify"}],
        "owns": {},
        "data": [],
    }
    for key, value in sidecar_edits.items():
        doc.pop(key, None) if value is None else doc.__setitem__(key, value)
    (dest / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")
    (dest / "warezsmoke_main.py").write_text((FIXTURE / "warezsmoke_main.py").read_text(encoding="utf-8"), encoding="utf-8")
    (dest / "README.md").write_text((FIXTURE / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def test_fixture_prepares_as_cplug_and_the_hosted_validator_accepts_v2_fixture(tmp_path: Path) -> None:
    src = _copy_v2(tmp_path)
    before = (src / "carnivore.toml").read_bytes()
    prepared = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor")
    assert prepared.kind == "cplug" and prepared.name == "warezsmoke" and prepared.refusals == []
    members = dict(prepared.members)
    assert "carnivore.toml" in members and "warezsmoke_main.py" in members
    assert (src / "carnivore.toml").read_bytes() == before

    v2_members = {p.relative_to(FIXTURE).as_posix(): p.read_bytes() for p in sorted(FIXTURE.rglob("*")) if p.is_file()}
    body = {"kind": "cplug", "name": "warezsmoke", "version": "1.0.0", "files": [
        {"path": p, "content_base64": base64.b64encode(c).decode()} for p, c in v2_members.items()]}
    kind, handle, name, _version, _members, _text = validate_kinds.validate_any(body, "harbor")
    assert (kind, handle, name) == ("cplug", "harbor", "warezsmoke")


def _codes(prepared) -> list:
    return [r.code for r in prepared.refusals]


def test_contract_violations_refuse(tmp_path: Path) -> None:
    assert kinds.prepare_kind("cplug", str(_copy_v2(tmp_path / "a", plugin_id="warez-smoke")), "1.0.0", "harbor").refusals
    assert kinds.prepare_kind("cplug", str(_copy_v2(tmp_path / "e")), "1.0.0", "").refusals
    bad_json = tmp_path / "bad_json"
    bad_json.mkdir()
    (bad_json / "carnivore.json").write_text(json.dumps({"schema": 2, "id": "bad", "name": "Bad", "version": "1.0.0", "kind": "plugin", "description": "d", "author": "a", "data": "not-a-list"}))
    assert kinds.prepare_kind("cplug", str(bad_json), "1.0.0", "harbor").refusals


def test_prepare_refuses_when_the_manifests_differ_from_the_version_being_published(tmp_path: Path) -> None:
    prepared = kinds.prepare_kind("cplug", str(_copy_v2(tmp_path)), "2.0.0", "harbor")
    assert prepared.refusals and "version 2.0.0" in prepared.refusals[0].detail


def test_a_cplug_with_an_image_is_refused_locally(tmp_path: Path) -> None:
    src = _copy_v2(tmp_path)
    (src / "icon.png").write_bytes(b"PK\x03\x04")
    assert kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor").refusals


def test_a_cplug_carrying_another_kinds_manifest_is_refused_locally(tmp_path: Path) -> None:
    from src.plugins.sdk import cplug_validate

    assert kinds.CPLUG_OTHER_KIND_MANIFESTS == cplug_validate.OTHER_KIND_MANIFESTS
    for i, rel in enumerate(sorted(kinds.CPLUG_OTHER_KIND_MANIFESTS)):
        src = _copy_v2(tmp_path / str(i))
        (src / rel.replace("skill.md", "SKILL.md")).parent.mkdir(parents=True, exist_ok=True)
        (src / rel.replace("skill.md", "SKILL.md")).write_text("{}" if rel.endswith(".json") else "x")
        refusals = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor").refusals
        assert any("another kind's manifest" in r.detail for r in refusals), rel
    assert not kinds.prepare_kind("cplug", str(_copy_v2(tmp_path / "ok")), "1.0.0", "harbor").refusals


def test_a_plugin_folder_still_prepares_as_plugin(tmp_path: Path) -> None:
    plugin = tmp_path / "p"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "p", "version": "1.0.0"}))
    prepared = kinds.prepare_kind("plugin", str(plugin), "1.0.0")
    assert prepared.kind == "plugin" and prepared.refusals == []


def test_own_cplug_locations_come_from_sideload_sources(tmp_path: Path) -> None:
    src = _copy_v2(tmp_path)
    (loc,) = kinds.own_cplug_locations({"warezsmoke": {"source": str(src)}, "gone": {"source": str(tmp_path / "nope")}})
    assert (loc["location_id"], loc["kind"], loc["path"]) == ("cplug:warezsmoke", "cplug", str(src))


def _view_folder_v2(tmp_path: Path, *, extra_files: list[str] | None = None) -> Path:
    files = ["index.html", "app.js", *(extra_files or [])]
    views_block = (
        '\n[[ui.views]]\n'
        'name = "game"\n'
        'surfaces = ["panel"]\n'
        f'files = {json.dumps(files)}\n'
    )
    folder = _copy_v2(tmp_path, views_block=views_block)
    (folder / "views" / "game").mkdir(parents=True)
    (folder / "views" / "game" / "index.html").write_text("<p>game</p>")
    (folder / "views" / "game" / "app.js").write_text("export default 1\n")
    return folder


def _view_folder_v1(tmp_path: Path) -> Path:
    folder = _copy_v1(tmp_path)
    manifest = json.loads((folder / "cplug.json").read_text())
    manifest["views"] = [{"name": "game", "surfaces": ["panel"], "files": ["index.html", "app.js"]}]
    (folder / "cplug.json").write_text(json.dumps(manifest))
    (folder / "views" / "game").mkdir(parents=True)
    (folder / "views" / "game" / "index.html").write_text("<p>game</p>")
    (folder / "views" / "game" / "app.js").write_text("export default 1\n")
    return folder


def _members(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _check_v2_surfaces(folder: Path) -> None:
    prepared = kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor")
    assert not prepared.refusals, prepared.refusals
    assert len(install_gates.check_files(folder)) == len(prepared.members)


def test_declared_views_pass_all_admission_surfaces_without_unrestricted_trust(tmp_path: Path) -> None:
    folder = _view_folder_v2(tmp_path / "v2")
    _check_v2_surfaces(folder)
    (folder / "views" / "game" / "other.js").write_text("alert(1)")
    assert kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    v2_members = _members(folder)
    v2_body = {"kind": "cplug", "name": "warezsmoke", "version": "1.0.0", "files": [
        {"path": p, "content_base64": base64.b64encode(data).decode()} for p, data in v2_members.items()]}
    with pytest.raises(UploadRefused, match="other.js"):
        validate_kinds.validate_any(v2_body, "harbor")

    v1_folder = _view_folder_v1(tmp_path / "v1")
    (v1_folder / "views" / "game" / "other.js").write_text("alert(1)")
    members = _members(v1_folder)
    members["carnivore.json"] = json.dumps({**json.loads(members["carnivore.json"]), "id": "harbor/warezsmoke", "tier": "catalog"}).encode()
    with pytest.raises(KindRefused, match="other.js"):
        index_cplugs.validate_cplug("warezsmoke", members, handle="harbor")


def test_exact_file_and_bundle_caps_on_admission_surfaces(tmp_path: Path) -> None:
    folder = _view_folder_v2(tmp_path / "v2")
    app_js = folder / "views" / "game" / "app.js"
    app_js.write_bytes(b"a" * install_gates.MAX_FILE_BYTES)
    _check_v2_surfaces(folder)
    app_js.write_bytes(b"a" * (install_gates.MAX_FILE_BYTES + 1))
    assert kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.check_files(folder)
    assert caught.value.code == install_gates.TOO_LARGE

    app_js.write_bytes(b"a" * install_gates.MAX_FILE_BYTES)
    filler = folder / "filler.txt"
    filler.write_bytes(b"")
    filler.write_bytes(b"b" * (install_gates.MAX_TOTAL_BYTES - sum(len(v) for v in _members(folder).values())))
    assert sum(len(v) for v in _members(folder).values()) == install_gates.MAX_TOTAL_BYTES
    assert len(install_gates.check_files(folder)) == len(_members(folder))
    assert not kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    filler.write_bytes(filler.read_bytes() + b"b")
    assert any(r.code == "body_too_large" for r in kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals)
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.check_files(folder)
    assert caught.value.code == install_gates.TOO_LARGE


def test_declared_png_zip_polyglot_is_refused_at_every_admission_surface(tmp_path: Path) -> None:
    folder = _view_folder_v2(tmp_path / "v2", extra_files=["atlas.png"])
    data = io.BytesIO(b"\x89PNG\r\n\x1a\n")
    with zipfile.ZipFile(data, "a") as archive:
        archive.writestr("hidden.py", "print('hidden')")
    (folder / "views" / "game" / "atlas.png").write_bytes(data.getvalue())
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.check_files(folder)
    assert caught.value.code == install_gates.NOT_SAFE
    assert kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals

    v2_folder = _view_folder_v2(tmp_path / "v2_hosted", extra_files=["atlas.png"])
    (v2_folder / "views" / "game" / "atlas.png").write_bytes(data.getvalue())
    v2_members = _members(v2_folder)
    v2_body = {"kind": "cplug", "name": "warezsmoke", "version": "1.0.0", "files": [
        {"path": p, "content_base64": base64.b64encode(raw).decode()} for p, raw in v2_members.items()]}
    with pytest.raises(UploadRefused, match="atlas.png"):
        validate_kinds.validate_any(v2_body, "harbor")

    v1_folder = _view_folder_v1(tmp_path / "v1")
    manifest_path = v1_folder / "cplug.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["views"][0]["files"].append("atlas.png")
    manifest_path.write_text(json.dumps(manifest))
    (v1_folder / "views" / "game" / "atlas.png").write_bytes(data.getvalue())
    members = _members(v1_folder)
    members["carnivore.json"] = json.dumps({**json.loads(members["carnivore.json"]), "id": "harbor/warezsmoke", "tier": "catalog"}).encode()
    with pytest.raises(KindRefused, match="atlas.png"):
        index_cplugs.validate_cplug("warezsmoke", members, handle="harbor")


def test_source_scan_keeps_vendor_tokens_but_ignores_generic_function_call(tmp_path: Path) -> None:
    folder = _view_folder_v2(tmp_path)
    source = "key=atlas.Q7vN2mK9xP4rL6tY8wB0cD3eF5gH1j(\"sprites\");\n"
    assert {f.detector for f in message_model_secrets.scan_text(source)} == {"high_entropy_assignment"}
    app_js = folder / "views" / "game" / "app.js"
    app_js.write_text(source)
    assert not kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    fake_vendor_key = "ghp_" + "R7kQ2mVx9TbnLcJ6wZaHy8FdSpU3gEoNrKq1"
    app_js.write_text(source + f"const credential = '{fake_vendor_key}';\n")
    refusals = kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    assert any("github_token" in r.detail and r.path == "views/game/app.js" for r in refusals)
    app_js.write_text(source)
    (folder / "data.json").write_text(json.dumps({"key": "".join(['Q7vN2mK9', 'xP4rL6tY', '8wB0cD3e', 'F5gH1j'])}))
    refusals = kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    assert any("high_entropy_assignment" in r.detail and r.path == "data.json" for r in refusals)


def test_publish_refuses_an_unserved_api_version_with_the_install_code(tmp_path: Path) -> None:
    unserved = max(api_contract.SERVED_API_VERSIONS) + 1
    prepared = kinds.prepare_kind("cplug", str(_copy_v2(tmp_path, api_version=unserved)), "1.0.0", "harbor")
    assert install_gates.API_VERSION_UNSUPPORTED in _codes(prepared)
    assert kinds.prepare_kind("cplug", str(_copy_v2(tmp_path / "ok", api_version=1)), "1.0.0", "harbor").refusals == []


def test_typescript_template_parity_and_node_modules_refusal(tmp_path: Path) -> None:
    from src.plugins.cli import checker, templates

    ts_dir = tmp_path / "tsplug"
    templates.scaffold(ts_dir, "tsplug", "typescript", "harbor")
    assert (ts_dir / "package.json").is_file()

    chk = checker.check_folder(ts_dir)
    assert chk.ok, chk.errors

    prepared = kinds.prepare_kind("cplug", str(ts_dir), "0.1.0", "harbor")
    assert prepared.refusals == [], prepared.refusals
    assert any(path == "package.json" for path, _ in prepared.members)

    body = {
        "kind": "cplug",
        "name": "tsplug",
        "version": "0.1.0",
        "files": [{"path": p, "content_base64": base64.b64encode(c).decode()} for p, c in prepared.members],
    }
    kind, handle, name, version, _members, _text = validate_kinds.validate_any(body, "harbor")
    assert (kind, handle, name, version) == ("cplug", "harbor", "tsplug", "0.1.0")

    facts = install_gates.evaluate("harbor/tsplug", ts_dir).facts
    assert facts["id"] == "tsplug"
    assert index_cplugs.validate_cplug("tsplug", dict(prepared.members), handle="harbor")

    (ts_dir / "node_modules" / "evil").mkdir(parents=True)
    (ts_dir / "node_modules" / "evil" / "index.json").write_text("{}", encoding="utf-8")
    with pytest.raises(install_gates.CplugGateRefusal) as caught_gate:
        install_gates.check_files(ts_dir)
    assert caught_gate.value.code == install_gates.NOT_SAFE

    bad_body = {
        "kind": "cplug",
        "name": "tsplug",
        "version": "0.1.0",
        "files": [*body["files"], {"path": "node_modules/evil/index.json", "content_base64": base64.b64encode(b"{}").decode()}],
    }
    with pytest.raises(UploadRefused) as caught_upload:
        validate_kinds.validate_any(bad_body, "harbor")
    assert (caught_upload.value.status, caught_upload.value.code) == (409, "cplug_not_safe")

    v1_dir = _copy_v1(tmp_path / "v1pkg")
    (v1_dir / "package.json").write_text("{}", encoding="utf-8")
    with pytest.raises(install_gates.CplugGateRefusal) as caught_v1:
        install_gates.check_files(v1_dir)
    assert caught_v1.value.code == install_gates.NOT_SAFE
