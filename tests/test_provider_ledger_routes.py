
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.auth_routes import router as auth_router
from src.api.routes import router as api_router
from src.config import settings

LEDGER_URL = "/api/v1/provider-ledger"
ACCOUNTS_URL = "/api/v1/provider-ledger/accounts"
SETTINGS_URL = "/api/v1/config/settings"

CLAUDE_BODY = {
    "name": "Max main",
    "provider": "claude",
    "claude_config_dir": "~/.claude",
    "managed": False,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": [], "agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    settings._auth_config_cache = None

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as test_client:
        test_client.config_path = path
        yield test_client
    settings._auth_config_cache = None


def stored_accounts(path: Path) -> list:
    return json.loads(path.read_text()).get("provider_accounts", {}).get("accounts", [])


class TestTheLedgerRead:

    def test_it_answers_the_three_top_level_keys_the_contract_names(self, client):
        answer = client.get(LEDGER_URL)
        assert answer.status_code == 200
        body = answer.json()
        assert set(body) == {"accounts", "total", "loop"}

    def test_an_install_with_no_poller_reports_an_empty_ledger_not_an_error(
        self, client
    ):
        body = client.get(LEDGER_URL).json()
        assert body["accounts"] == []
        assert body["total"] == {"accounts": 0, "windows": []}

    def test_liveness_is_published_separately_from_the_readings(self, client):
        loop = client.get(LEDGER_URL).json()["loop"]
        assert loop["alive"] is False
        assert loop["last_pass_at"] is None


class TestTheAccountsList:

    def test_an_unconfigured_install_lists_nothing(self, client):
        answer = client.get(ACCOUNTS_URL)
        assert answer.status_code == 200
        assert answer.json() == []

    def test_a_stored_account_comes_back_with_its_pointer_and_no_token(self, client):
        client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)

        rows = client.get(ACCOUNTS_URL).json()

        assert len(rows) == 1
        assert rows[0]["id"] == "max-main"
        assert rows[0]["claude_config_dir"] == "~/.claude"
        assert set(rows[0]) == {
            "id",
            "name",
            "short_name",
            "provider",
            "claude_config_dir",
            "codex_home",
            "managed",
            "color",
        }


class TestTheWrite:

    def test_an_upsert_lands_on_disk_and_comes_back_from_the_read(self, client):
        answer = client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)

        assert answer.status_code == 200
        assert answer.json()["id"] == "max-main"
        assert [row["id"] for row in stored_accounts(client.config_path)] == [
            "max-main"
        ]

    def test_a_second_write_to_the_same_id_replaces_rather_than_appends(self, client):
        client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)
        client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "name": "Renamed"}
        )

        rows = client.get(ACCOUNTS_URL).json()
        assert len(rows) == 1
        assert rows[0]["name"] == "Renamed"

    def test_a_body_carrying_an_id_that_disagrees_with_the_path_is_refused(
        self, client
    ):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "id": "somebody-else"}
        )
        assert answer.status_code == 422

    def test_a_body_carrying_the_matching_id_is_accepted(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "id": "max-main"}
        )
        assert answer.status_code == 200


class TestWhatTheWriteRefuses:

    def test_a_token_field_is_refused_by_the_model_itself(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main",
            json={**CLAUDE_BODY, "token": "sk-ant-oat01-NOT-ALLOWED"},
        )
        assert answer.status_code == 422

    def test_and_nothing_was_written_when_it_was_refused(self, client):
        client.put(
            f"{ACCOUNTS_URL}/max-main",
            json={**CLAUDE_BODY, "token": "sk-ant-oat01-NOT-ALLOWED"},
        )
        assert stored_accounts(client.config_path) == []

    def test_an_id_that_is_not_a_lowercase_slug_is_refused(self, client):
        answer = client.put(f"{ACCOUNTS_URL}/Max_Main", json=CLAUDE_BODY)
        assert answer.status_code == 422

    def test_an_empty_name_is_refused(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "name": "   "}
        )
        assert answer.status_code == 422

    def test_a_claude_account_with_no_config_dir_is_refused(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main",
            json={
                "name": "Max main",
                "provider": "claude",
                "claude_config_dir": "",
                "managed": False,
            },
        )
        assert answer.status_code == 422

    def test_an_unknown_provider_is_refused(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/some-account",
            json={"name": "Some account", "provider": "gemini", "managed": False},
        )
        assert answer.status_code == 422


class TestTheDelete:

    def test_removing_a_configured_account_empties_the_list(self, client):
        client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)

        answer = client.delete(f"{ACCOUNTS_URL}/max-main")

        assert answer.status_code == 200
        assert client.get(ACCOUNTS_URL).json() == []
        assert stored_accounts(client.config_path) == []

    def test_removing_an_account_that_is_not_there_is_a_404(self, client):
        answer = client.delete(f"{ACCOUNTS_URL}/never-configured")
        assert answer.status_code == 404

    def test_it_leaves_the_siblings_alone(self, client):
        client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)
        client.put(
            f"{ACCOUNTS_URL}/codex-main",
            json={
                "name": "Codex main",
                "provider": "codex",
                "codex_home": "~/.codex",
                "managed": False,
            },
        )

        client.delete(f"{ACCOUNTS_URL}/max-main")

        assert [row["id"] for row in client.get(ACCOUNTS_URL).json()] == ["codex-main"]


class TestTheWriteInvalidatesTheParsedConfigCache:

    def test_the_settings_summary_sees_an_account_added_after_it_was_read(
        self, client
    ):
        before = client.get(SETTINGS_URL).json()
        assert before["provider_accounts"]["accounts"] == []

        client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)

        after = client.get(SETTINGS_URL).json()
        assert [a["id"] for a in after["provider_accounts"]["accounts"]] == ["max-main"]

    def test_and_a_delete_clears_it_too(self, client):
        client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)
        primed = client.get(SETTINGS_URL).json()
        assert len(primed["provider_accounts"]["accounts"]) == 1

        client.delete(f"{ACCOUNTS_URL}/max-main")

        after = client.get(SETTINGS_URL).json()
        assert after["provider_accounts"]["accounts"] == []


class TestTheManagedProfileAndTheColour:

    def test_a_colour_round_trips_to_disk_and_back(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "color": "#8b5cf6"}
        )
        assert answer.status_code == 200
        assert answer.json()["color"] == "#8b5cf6"
        assert stored_accounts(client.config_path)[0]["color"] == "#8b5cf6"

    def test_an_uppercase_colour_is_refused_rather_than_lowercased(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "color": "#8B5CF6"}
        )
        assert answer.status_code == 422
        assert answer.json()["detail"]["code"] == "invalid_account"

    def test_a_refused_colour_writes_nothing(self, client):
        client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "color": "not-a-colour"}
        )
        assert stored_accounts(client.config_path) == []

    def test_a_row_written_with_no_colour_stores_null(self, client):
        answer = client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)
        assert answer.json()["color"] is None

    def test_an_ordinary_row_is_not_managed(self, client):
        answer = client.put(f"{ACCOUNTS_URL}/max-main", json=CLAUDE_BODY)
        assert answer.json()["managed"] is False

    def test_a_managed_row_is_stored_with_its_absolute_profile_path(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        answer = client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": True},
        )
        assert answer.status_code == 200
        expected = str(tmp_path / ".carnivore/accounts/claude1")
        assert answer.json()["claude_config_dir"] == expected
        assert stored_accounts(client.config_path)[0]["claude_config_dir"] == expected

    def test_saving_a_managed_row_creates_its_directory_at_0700(
        self, client, tmp_path, monkeypatch
    ):
        import stat as stat_module

        monkeypatch.setenv("HOME", str(tmp_path))
        client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": True},
        )
        made = tmp_path / ".carnivore/accounts/claude1"
        assert made.is_dir()
        assert stat_module.S_IMODE(made.stat().st_mode) == 0o700

    def test_a_managed_codex_row_points_its_codex_home_at_the_profile(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        answer = client.put(
            f"{ACCOUNTS_URL}/codex1",
            json={"name": "Codex 1", "provider": "codex", "managed": True},
        )
        assert answer.json()["codex_home"] == str(
            tmp_path / ".carnivore/accounts/codex1"
        )

    def test_a_directory_that_cannot_be_made_is_a_409_and_stores_nothing(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".carnivore").write_text("not a directory")
        answer = client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": True},
        )
        assert answer.status_code == 409
        assert answer.json()["detail"]["code"] == "managed_dir_unavailable"
        assert stored_accounts(client.config_path) == []

    def test_an_unmanaged_row_keeps_the_path_the_user_typed(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        answer = client.put(
            f"{ACCOUNTS_URL}/work",
            json={
                "name": "Work",
                "provider": "claude",
                "claude_config_dir": "~/.claude-work",
                "managed": False,
            },
        )
        assert answer.json()["claude_config_dir"] == "~/.claude-work"
        assert not (tmp_path / ".carnivore").exists()


class TestAManagedRowCannotBeDemotedBySilence:

    def test_a_body_that_states_no_managed_flag_is_refused(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main",
            json={
                "name": "Max main",
                "provider": "claude",
                "claude_config_dir": "~/.claude",
            },
        )
        assert answer.status_code == 422

    def test_the_refused_body_stored_nothing(self, client):
        client.put(
            f"{ACCOUNTS_URL}/max-main",
            json={"name": "Max main", "provider": "claude"},
        )
        assert stored_accounts(client.config_path) == []

    def test_a_managed_row_survives_a_write_that_states_no_pointer(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": True},
        )

        answer = client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": False},
        )

        assert answer.status_code == 422
        assert answer.json()["detail"]["code"] == "pointer_required"

    def test_the_refused_demotion_left_the_row_exactly_as_it_was(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": True},
        )
        client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": False},
        )

        stored = stored_accounts(client.config_path)[0]
        assert stored["managed"] is True
        assert stored["claude_config_dir"] == str(
            tmp_path / ".carnivore/accounts/claude1"
        )

    def test_a_demotion_that_states_where_the_row_now_points_is_allowed(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": True},
        )

        answer = client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={
                "name": "Claude 1",
                "provider": "claude",
                "managed": False,
                "claude_config_dir": "~/.claude-work",
            },
        )

        assert answer.status_code == 200
        assert answer.json()["managed"] is False
        assert answer.json()["claude_config_dir"] == "~/.claude-work"

    def test_an_unmanaged_row_may_still_be_written_with_no_pointer(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/plain",
            json={"name": "Plain", "provider": "claude", "managed": False},
        )
        assert answer.status_code == 200
        assert answer.json()["claude_config_dir"] == "~/.claude"

    def test_a_managed_row_may_be_rewritten_managed_with_no_pointer(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={"name": "Claude 1", "provider": "claude", "managed": True},
        )

        answer = client.put(
            f"{ACCOUNTS_URL}/claude1",
            json={
                "name": "Claude 1",
                "provider": "claude",
                "managed": True,
                "color": "#8b5cf6",
            },
        )
        assert answer.status_code == 200
        assert answer.json()["color"] == "#8b5cf6"


class TestTheShortName:

    def test_a_short_name_round_trips_trimmed(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "short_name": "  mm  "}
        )
        assert answer.status_code == 200
        assert answer.json()["short_name"] == "mm"
        assert stored_accounts(client.config_path)[0]["short_name"] == "mm"

    def test_an_edit_that_never_names_it_keeps_it(self, client):
        client.put(f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "short_name": "mm"})
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main",
            json={**CLAUDE_BODY, "name": "renamed", "color": "#8b5cf6"},
        )
        assert answer.status_code == 200
        row = stored_accounts(client.config_path)[0]
        assert (row["name"], row["short_name"]) == ("renamed", "mm")

    def test_an_empty_string_clears_it(self, client):
        client.put(f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "short_name": "mm"})
        for blank in ("", "   "):
            client.put(f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "short_name": "mm"})
            answer = client.put(
                f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "short_name": blank}
            )
            assert answer.status_code == 200
            assert answer.json()["short_name"] is None
            assert not stored_accounts(client.config_path)[0].get("short_name")

    def test_an_over_long_short_name_is_refused(self, client):
        answer = client.put(
            f"{ACCOUNTS_URL}/max-main", json={**CLAUDE_BODY, "short_name": "x" * 33}
        )
        assert answer.status_code == 422


def test_account_or_404_names_the_id_and_returns_the_match() -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException

    from src.api.provider_ledger_routes import _account_or_404

    rows = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    assert _account_or_404(rows, "b") is rows[1]
    with pytest.raises(HTTPException) as caught:
        _account_or_404(rows, "zzz")
    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "not_found"
    assert "zzz" in caught.value.detail["detail"]
