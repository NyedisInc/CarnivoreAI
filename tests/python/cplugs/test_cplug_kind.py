
from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.live_install_roots import HARNESS_CPLUG, TRASH_DIR_NAME, LiveInstallRoots
from src.core.skills import kinds
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem, InstallTarget
from src.core.skills.records import SIDECAR_NAME
from src.core.skills.updates import SCRIPTS_PRESENT, auto_update_eligible
from src.cplugs.host.adoption import BUILTIN_SOURCE
from src.cplugs.runtime.integrity import tree_digest
from tests.helpers.catalog_app import StateOnlySettings, catalog_app, ledger_rows
from tests.test_skill_updates import BODY_SHA, row as skill_row, version as new_version

BUILTIN_ID = "nyedis/huddle"
CATALOG_ID = "acme/clock"


def _cplug_row(item_id: str, install_id: str, source: str) -> InstalledItem:
    return skill_row(
        install_id=install_id, item_id=item_id, kind=kinds.KIND_CPLUG, publisher=item_id.split("/")[0],
        name="cplug-" + item_id.split("/")[1], source_index_url=source, publisher_key_id=source,
        project_path=GLOBAL_PROJECT_PATH, auto_update=False,
    )


def test_the_tables_answer_for_cplug():
    assert kinds.manifest_name("cplug") == "cplug.json"
    assert kinds.archive_folder("cplug") == "cplugs"
    assert kinds.scopes_for("cplug") == ("global",)
    assert not kinds.scope_supported("cplug", "project")


def test_a_cplug_never_auto_updates_and_a_skill_does():
    skill = skill_row()
    assert auto_update_eligible(skill, new_version(), BODY_SHA, verified=True, scripts_present=False).ok is True
    cplug = dataclasses.replace(skill, kind=kinds.KIND_CPLUG)
    answer = auto_update_eligible(cplug, new_version(), BODY_SHA, verified=True, scripts_present=False)
    assert (answer.ok, answer.reason) == (False, SCRIPTS_PRESENT)


def test_the_tree_digest_ignores_the_sidecar_and_moves_on_one_byte(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "main.py").write_bytes(b"print(1)\n")
    plain = tree_digest(code)
    (code / SIDECAR_NAME).write_text('{"installed_at": "2026-10-21"}')
    assert tree_digest(code) == plain
    (code / SIDECAR_NAME).write_text('{"installed_at": "2030-01-01"}')
    assert tree_digest(code) == plain
    (code / "main.py").write_bytes(b"print(2)\n")
    assert tree_digest(code) != plain


def test_builtin_rows_are_guarded_and_catalog_rows_are_not(tmp_path: Path):
    state = tmp_path / "state"
    served = tmp_path / "served"
    served.mkdir()
    with catalog_app(
        tmp_path, served, trust_root=None,
        roots_factory=lambda settings: LiveInstallRoots(settings_reader=settings),
    ) as app:
        roots = app.services.install_roots
        (target,) = roots.targets_for(kinds.KIND_CPLUG, SCOPE_GLOBAL, None)
        assert target.harness == HARNESS_CPLUG and target.leaf_dir == state / "cplug-code"
        from src.api.catalog_loadout_rules import ensure_cplug_root

        ensure_cplug_root(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=app.services))))
        folder = target.leaf_dir / "clock"
        folder.mkdir()
        (folder / "main.py").write_text("x = 1\n")

        builtin = _cplug_row(BUILTIN_ID, "b" * 32, BUILTIN_SOURCE)
        catalog = _cplug_row(CATALOG_ID, "c" * 32, "https://example.invalid/index.json")
        with app.services.catalog.ledger() as ledger:
            ledger.insert(builtin)
            ledger.insert(catalog, [InstallTarget(catalog.install_id, HARNESS_CPLUG, str(folder))])
            from src.api.catalog_views import ledger_rows_by_item
            from src.core.skills.auto_update import candidate_rows

            assert set(ledger_rows_by_item(ledger.list())) == {BUILTIN_ID, CATALOG_ID}
        assert candidate_rows(app.services) == []

        client = app.client
        for verb, url, body in (
            ("delete", f"/catalog/installed/{builtin.install_id}", None),
            ("post", f"/catalog/installed/{builtin.install_id}/update", {"expected_revision": 1}),
            ("patch", f"/catalog/installed/{builtin.install_id}", {"auto_update": False, "expected_revision": 1}),
        ):
            reply = client.request(verb.upper(), url, json=body) if body else client.request(verb.upper(), url)
            assert reply.status_code == 409, (verb, reply.text)
            assert reply.json()["detail"]["code"] == "builtin_cplug", (verb, reply.text)

        on = client.patch(f"/catalog/installed/{catalog.install_id}", json={"auto_update": True, "expected_revision": 1})
        assert (on.status_code, on.json()["detail"]["code"]) == (409, "cplug_never_auto_updates")
        off = client.patch(f"/catalog/installed/{catalog.install_id}", json={"auto_update": False, "expected_revision": 1})
        assert off.status_code == 200, off.text
        gone = client.delete(f"/catalog/installed/{catalog.install_id}")
        assert gone.status_code == 200, gone.text
        assert not folder.exists()
        assert any((state / TRASH_DIR_NAME).iterdir())
        assert [r.item_id for r in ledger_rows(app)] == [BUILTIN_ID]


def test_a_project_scope_cplug_target_is_refused(tmp_path: Path):
    roots = LiveInstallRoots(settings_reader=StateOnlySettings(tmp_path))
    with pytest.raises(ValueError):
        roots.targets_for(kinds.KIND_CPLUG, "project", str(tmp_path))


def _route_fixture(monkeypatch, *, scripts: int):
    from src.api import catalog_install_routes as routes

    item = SimpleNamespace(id="acme/clock", kind=kinds.KIND_CPLUG, publisher="acme", name="clock")
    version = SimpleNamespace(scripts=scripts)
    calls: list = []

    async def snap(_request):
        return None

    async def scope(_request, _body):
        return SCOPE_GLOBAL, None

    monkeypatch.setattr(routes, "_snapshot", snap)
    monkeypatch.setattr(routes, "resolve_item", lambda _snapshot, _id: (item, version))
    monkeypatch.setattr(routes, "scope_arguments", scope)
    monkeypatch.setattr(routes, "refuse_unsupported_scope", lambda _item, _scope: None)
    monkeypatch.setattr(routes, "ensure_cplug_root", lambda _request: calls.append("root"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace())))
    body = SimpleNamespace(item_id="acme/clock", scope="global", consent=None, one_click=False)
    return routes, request, body, calls


@pytest.mark.asyncio
async def test_a_cplug_with_scripts_is_refused_before_anything_is_fetched(monkeypatch):
    from fastapi import HTTPException
    from src.api.catalog_install_support import fetch_and_stage_with

    item = SimpleNamespace(id="acme/clock", kind=kinds.KIND_CPLUG)
    with pytest.raises(HTTPException) as err:
        await fetch_and_stage_with(SimpleNamespace(), item, SimpleNamespace(scripts=2), allow_scripts=True)
    assert err.value.status_code == 409 and err.value.detail["code"] == "scripts_not_supported"


@pytest.mark.asyncio
async def test_install_refuses_cplug_scripts_with_the_clear_code_not_a_consent_request(monkeypatch):
    from fastapi import HTTPException

    routes, request, body, calls = _route_fixture(monkeypatch, scripts=3)
    with pytest.raises(HTTPException) as err:
        await routes.run_install(request, body)
    assert err.value.detail["code"] == "scripts_not_supported"
    assert calls == ["root"]


@pytest.mark.asyncio
async def test_preview_and_install_make_the_cplug_root_before_the_planner_runs(monkeypatch):
    class Stop(Exception):
        pass

    async def stage(*_a, **_k):
        raise Stop

    routes, request, body, calls = _route_fixture(monkeypatch, scripts=0)
    monkeypatch.setattr(routes, "fetch_and_stage", stage)
    with pytest.raises(Stop):
        await routes.preview_install(request, body)
    assert calls == ["root"]
    calls.clear()
    monkeypatch.setattr(routes, "carries_scripts", lambda _v: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        await routes.run_install(request, body)
    assert calls == ["root"]


def test_a_symlink_or_special_file_named_like_the_sidecar_is_refused_not_skipped(tmp_path: Path):
    import os
    from src.cplugs.runtime.integrity import IntegrityError

    link_root = tmp_path / "a"
    link_root.mkdir()
    (link_root / "main.py").write_bytes(b"1\n")
    os.symlink("main.py", link_root / SIDECAR_NAME)
    with pytest.raises(IntegrityError):
        tree_digest(link_root)
    fifo_root = tmp_path / "b"
    fifo_root.mkdir()
    os.mkfifo(fifo_root / SIDECAR_NAME)
    with pytest.raises(IntegrityError):
        tree_digest(fifo_root)
