
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rol_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rol_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.catalog_install_support import discovery_listing
from src.core.live_install_roots import LiveInstallRoots
from src.core.skills.install_types import (
    CHOICE_INSTALL_AS,
    CHOICE_REPLACE,
    NAME_TAKEN,
)
from tests.helpers.catalog_app import catalog_app
from tests.helpers.catalog_surface import (
    build_skill,
    fixture_trust_root,
    item_for,
    keypairs,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.test_ports_conformance import StubSettingsReader
from tests.test_skill_installer import FakeInstallRoots

PUBLISHER = "alex"
NAME = "sme"
ITEM_ID = f"{PUBLISHER}/{NAME}"
GLOBAL = {"item_id": ITEM_ID, "scope": "global"}


@pytest.fixture
def live_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    return home


def live_roots(tmp_path) -> LiveInstallRoots:
    return LiveInstallRoots(
        settings_reader=StubSettingsReader(
            pins=tmp_path / "p.json", cap=1, state=tmp_path / "state"
        )
    )




def test_the_live_adapter_reads_both_codex_roots(tmp_path, live_home):
    (live_home / ".codex" / "skills" / "from-codex-home").mkdir(parents=True)
    (live_home / ".codex" / "skills" / ".system" / "from-system").mkdir(
        parents=True
    )

    names = live_roots(tmp_path).read_only_listing("codex")

    assert names == (".system", "from-codex-home", "from-system")


def test_the_live_adapter_has_no_read_only_root_for_claude(tmp_path, live_home):
    (live_home / ".claude" / "skills" / "mine").mkdir(parents=True)

    assert live_roots(tmp_path).read_only_listing("claude") == ()


def test_the_live_adapter_reports_an_absent_root_as_empty(tmp_path, live_home):
    roots = live_roots(tmp_path)

    assert roots.read_only_listing("codex") == ()
    assert not (live_home / ".agents").exists()


def test_the_live_adapter_never_reads_through_a_symlinked_root(
    tmp_path, live_home
):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / NAME).mkdir(parents=True)
    (live_home / ".agents").mkdir()
    (live_home / ".agents" / "skills").symlink_to(elsewhere)

    assert live_roots(tmp_path).read_only_listing("codex") == ()


def test_the_live_adapter_refuses_an_unknown_harness(tmp_path, live_home):
    with pytest.raises(ValueError):
        live_roots(tmp_path).read_only_listing("gemini")




def test_the_fake_answers_the_same_shape(tmp_path):
    roots = FakeInstallRoots(tmp_path)
    roots.make_roots()
    (roots.agents_skills() / "from-agents").mkdir(parents=True)
    (roots.codex_system() / "from-system").mkdir(parents=True)

    assert roots.read_only_listing("codex") == ("from-agents", "from-system")
    assert roots.read_only_listing("claude") == ()


def test_the_planner_input_merges_both_harnesses(tmp_path):
    roots = FakeInstallRoots(tmp_path)
    roots.make_roots()
    (roots.agents_skills() / "mine").mkdir(parents=True)

    assert discovery_listing(roots) == ("mine",)




@pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)
def test_a_name_in_a_read_only_root_offers_install_as_and_never_replace(
    tmp_path, keys_and_served
):
    trust, served = keys_and_served

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        (app.roots.agents_skills() / NAME).mkdir(parents=True)
        response = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert len(app.staging_entries()) == 1

    assert response.status_code == 409, response.text
    body = response.json()["detail"]
    assert body["code"] == NAME_TAKEN
    assert body["plan_token"]
    actions = [choice["choice"] for choice in body["choices"]]
    assert actions == [CHOICE_INSTALL_AS]
    assert CHOICE_REPLACE not in actions


@pytest.fixture
def keys_and_served(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    index_kp, publisher_kp, _stranger = keypairs(tmp_path / "keys")
    package = build_skill(tmp_path, publisher=PUBLISHER, name=NAME)
    serve_archive(served, package.tar_bytes)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(package, publisher=PUBLISHER, name=NAME)],
        serial=1,
    )
    return fixture_trust_root(index_kp, publisher_kp), served
