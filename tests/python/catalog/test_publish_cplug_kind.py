
import json
import base64
import io
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from src.core.catalog import publish_prepare_kinds as kinds

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "cplugs" / "warezsmoke"
sys.path.insert(0, str(ROOT / "hosted" / "catalog" / "api"))
sys.path.insert(0, str(ROOT / "hosted" / "catalog_index" / "tools"))
import validate_kinds  # noqa: E402
from validate_upload import UploadRefused  # noqa: E402
from index_builder import cplugs as index_cplugs  # noqa: E402
from index_builder.kind_errors import KindRefused  # noqa: E402
from src.cplugs.host import install_gates
from src.core import message_model_secrets


def _copy(tmp_path: Path, **sidecar_edits) -> Path:
    dest = tmp_path / "warezsmoke"
    shutil.copytree(FIXTURE, dest)
    path = dest / "carnivore.json"
    doc = json.loads(path.read_text())
    doc.update(id="local/warezsmoke", tier="local")
    for key, value in sidecar_edits.items():
        doc.pop(key, None) if value is None else doc.__setitem__(key, value)
    path.write_text(json.dumps(doc))
    return dest


def test_fixture_prepares_as_cplug_and_the_hosted_validator_accepts_it(tmp_path: Path) -> None:
    src = _copy(tmp_path)
    before = (src / "carnivore.json").read_bytes()
    prepared = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor")
    assert prepared.kind == "cplug" and prepared.name == "warezsmoke" and prepared.refusals == []
    members = dict(prepared.members)
    sidecar = json.loads(members["carnivore.json"])
    assert (sidecar["id"], sidecar["tier"], sidecar["default_enabled"]) == ("harbor/warezsmoke", "catalog", False)
    assert (src / "carnivore.json").read_bytes() == before
    body = {"kind": "cplug", "name": prepared.name, "version": "1.0.0", "files": [
        {"path": p, "content_base64": __import__("base64").b64encode(c).decode()} for p, c in prepared.members]}
    kind, handle, name, _version, _members, _text = validate_kinds.validate_any(body, "harbor")
    assert (kind, handle, name) == ("cplug", "harbor", "warezsmoke")


def _codes(prepared) -> list:
    return [r.code for r in prepared.refusals]


def test_contract_violations_refuse(tmp_path: Path) -> None:
    hyphen = _copy(tmp_path / "a")
    cj = json.loads((hyphen / "cplug.json").read_text())
    cj["id"] = "warez-smoke"
    (hyphen / "cplug.json").write_text(json.dumps(cj))
    assert _codes(kinds.prepare_kind("cplug", str(hyphen), "1.0.0", "harbor"))
    assert kinds.prepare_kind("cplug", str(_copy(tmp_path / "b", runtime=None)), "1.0.0", "harbor").refusals
    assert kinds.prepare_kind("cplug", str(_copy(tmp_path / "c", data=None)), "1.0.0", "harbor").refusals
    assert kinds.prepare_kind("cplug", str(_copy(tmp_path / "d", network_hosts=None)), "1.0.0", "harbor").refusals
    assert kinds.prepare_kind("cplug", str(_copy(tmp_path / "e")), "1.0.0", "").refusals


def test_prepare_refuses_when_the_manifests_differ_from_the_version_being_published(tmp_path: Path) -> None:
    prepared = kinds.prepare_kind("cplug", str(_copy(tmp_path)), "2.0.0", "harbor")
    assert prepared.refusals and "version 2.0.0" in prepared.refusals[0].detail


def test_a_cplug_with_an_image_is_refused_locally(tmp_path: Path) -> None:
    src = _copy(tmp_path)
    (src / "icon.png").write_bytes(b"PK\x03\x04")
    assert kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor").refusals


def test_a_cplug_carrying_another_kinds_manifest_is_refused_locally(tmp_path: Path) -> None:
    import validate_cplug  # noqa: E402

    assert kinds.CPLUG_OTHER_KIND_MANIFESTS == validate_cplug.OTHER_KIND_MANIFESTS
    for i, rel in enumerate(sorted(kinds.CPLUG_OTHER_KIND_MANIFESTS)):
        src = _copy(tmp_path / str(i))
        (src / rel.replace("skill.md", "SKILL.md")).parent.mkdir(parents=True, exist_ok=True)
        (src / rel.replace("skill.md", "SKILL.md")).write_text("{}" if rel.endswith(".json") else "x")
        refusals = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor").refusals
        assert any("another kind's manifest" in r.detail for r in refusals), rel
    assert not kinds.prepare_kind("cplug", str(_copy(tmp_path / "ok")), "1.0.0", "harbor").refusals


def test_a_plugin_folder_still_prepares_as_plugin(tmp_path: Path) -> None:
    plugin = tmp_path / "p"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "p", "version": "1.0.0"}))
    prepared = kinds.prepare_kind("plugin", str(plugin), "1.0.0")
    assert prepared.kind == "plugin" and prepared.refusals == []


def test_own_cplug_locations_come_from_sideload_sources(tmp_path: Path) -> None:
    src = _copy(tmp_path)
    (loc,) = kinds.own_cplug_locations({"warezsmoke": {"source": str(src)}, "gone": {"source": str(tmp_path / "nope")}})
    assert (loc["location_id"], loc["kind"], loc["path"]) == ("cplug:warezsmoke", "cplug", str(src))


def _view_folder(tmp_path: Path) -> Path:
    folder = _copy(tmp_path)
    manifest = json.loads((folder / "cplug.json").read_text())
    manifest["views"] = [{"name": "game", "surfaces": ["panel"], "files": ["index.html", "app.js"]}]
    (folder / "cplug.json").write_text(json.dumps(manifest))
    (folder / "views" / "game").mkdir(parents=True)
    (folder / "views" / "game" / "index.html").write_text("<p>game</p>")
    (folder / "views" / "game" / "app.js").write_text("export default 1\n")
    return folder


def _members(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _check_three_surfaces(folder: Path) -> None:
    prepared = kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor")
    assert not prepared.refusals, prepared.refusals
    members = dict(prepared.members)
    body = {"kind": "cplug", "name": "warezsmoke", "version": "1.0.0", "files": [
        {"path": p, "content_base64": base64.b64encode(data).decode()} for p, data in members.items()]}
    assert validate_kinds.validate_any(body, "harbor")[0] == "cplug"
    assert index_cplugs.validate_cplug("warezsmoke", members, handle="harbor")
    assert len(install_gates.check_files(folder)) == len(members)


def test_declared_views_pass_all_admission_surfaces_without_unrestricted_trust(tmp_path: Path) -> None:
    folder = _view_folder(tmp_path)
    _check_three_surfaces(folder)
    (folder / "views" / "game" / "other.js").write_text("alert(1)")
    assert kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    members = _members(folder)
    members["carnivore.json"] = json.dumps({**json.loads(members["carnivore.json"]), "id": "harbor/warezsmoke", "tier": "catalog"}).encode()
    body = {"kind": "cplug", "name": "warezsmoke", "files": [
        {"path": p, "content_base64": base64.b64encode(data).decode()} for p, data in members.items()]}
    with pytest.raises(UploadRefused, match="other.js"):
        validate_kinds.validate_any(body, "harbor")
    with pytest.raises(KindRefused, match="other.js"):
        index_cplugs.validate_cplug("warezsmoke", members, handle="harbor")


def test_exact_file_and_bundle_caps_on_admission_surfaces(tmp_path: Path) -> None:
    folder = _view_folder(tmp_path)
    app_js = folder / "views" / "game" / "app.js"
    app_js.write_bytes(b"a" * install_gates.MAX_FILE_BYTES)
    _check_three_surfaces(folder)
    app_js.write_bytes(b"a" * (install_gates.MAX_FILE_BYTES + 1))
    assert kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.check_files(folder)
    assert caught.value.code == install_gates.TOO_LARGE
    oversized = _members(folder)
    oversized["carnivore.json"] = json.dumps({**json.loads(oversized["carnivore.json"]), "id": "harbor/warezsmoke", "tier": "catalog"}).encode()
    body = {"kind": "cplug", "name": "warezsmoke", "files": [
        {"path": p, "content_base64": base64.b64encode(data).decode()} for p, data in oversized.items()]}
    with pytest.raises(UploadRefused) as caught:
        validate_kinds.validate_any(body, "harbor")
    assert caught.value.status == 413
    with pytest.raises(KindRefused) as caught:
        index_cplugs.validate_cplug("warezsmoke", oversized, handle="harbor")
    assert caught.value.status == 413
    app_js.write_bytes(b"a" * install_gates.MAX_FILE_BYTES)
    sidecar_path = folder / "carnivore.json"
    sidecar = json.loads(sidecar_path.read_text())
    sidecar.update(id="harbor/warezsmoke", tier="catalog")
    sidecar_path.write_text(json.dumps(sidecar))
    filler = folder / "filler.txt"
    filler.write_bytes(b"")
    filler.write_bytes(b"b" * (install_gates.MAX_TOTAL_BYTES - sum(len(v) for v in _members(folder).values())))
    assert sum(len(v) for v in _members(folder).values()) == install_gates.MAX_TOTAL_BYTES
    assert len(install_gates.check_files(folder)) == len(_members(folder))
    assert any(r.code == "body_too_large" for r in kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals)
    members = _members(folder)
    assert sum(map(len, members.values())) == install_gates.MAX_TOTAL_BYTES
    body = {"kind": "cplug", "name": "warezsmoke", "files": [
        {"path": p, "content_base64": base64.b64encode(data).decode()} for p, data in members.items()]}
    assert validate_kinds.validate_any(body, "harbor")[0] == "cplug"
    assert index_cplugs.validate_cplug("warezsmoke", members, handle="harbor")
    filler.write_bytes(filler.read_bytes() + b"b")
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.check_files(folder)
    assert caught.value.code == install_gates.TOO_LARGE
    too_large = dict(members)
    too_large["filler.txt"] += b"b"
    body["files"] = [{"path": p, "content_base64": base64.b64encode(data).decode()} for p, data in too_large.items()]
    with pytest.raises(UploadRefused) as caught:
        validate_kinds.validate_any(body, "harbor")
    assert caught.value.status == 413
    with pytest.raises(KindRefused) as caught:
        index_cplugs.validate_cplug("warezsmoke", too_large, handle="harbor")
    assert caught.value.status == 413


def test_declared_png_zip_polyglot_is_refused_at_every_admission_surface(tmp_path: Path) -> None:
    folder = _view_folder(tmp_path)
    manifest_path = folder / "cplug.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["views"][0]["files"].append("atlas.png")
    manifest_path.write_text(json.dumps(manifest))
    data = io.BytesIO(b"\x89PNG\r\n\x1a\n")
    with zipfile.ZipFile(data, "a") as archive:
        archive.writestr("hidden.py", "print('hidden')")
    (folder / "views" / "game" / "atlas.png").write_bytes(data.getvalue())
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.check_files(folder)
    assert caught.value.code == install_gates.NOT_SAFE
    assert kinds.prepare_kind("cplug", str(folder), "1.0.0", "harbor").refusals
    members = _members(folder)
    members["carnivore.json"] = json.dumps({**json.loads(members["carnivore.json"]), "id": "harbor/warezsmoke", "tier": "catalog"}).encode()
    body = {"kind": "cplug", "name": "warezsmoke", "files": [
        {"path": p, "content_base64": base64.b64encode(raw).decode()} for p, raw in members.items()]}
    with pytest.raises(UploadRefused, match="atlas.png"):
        validate_kinds.validate_any(body, "harbor")
    with pytest.raises(KindRefused, match="atlas.png"):
        index_cplugs.validate_cplug("warezsmoke", members, handle="harbor")


def test_source_scan_keeps_vendor_tokens_but_ignores_generic_function_call(tmp_path: Path) -> None:
    folder = _view_folder(tmp_path)
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
