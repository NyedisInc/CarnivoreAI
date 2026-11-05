
from __future__ import annotations

from types import SimpleNamespace

from src.core.launch_profiles import share
from src.config.launch_profiles import LaunchProfile
from tests.python.launch_profiles.test_launch_profiles_routes import env, profile  # noqa: F401

PREVIEW = "/api/v1/launch-profiles/import/preview"
IMPORT = "/api/v1/launch-profiles/import"


def _document(body: dict) -> dict:
    return {"format": share.SHARE_FORMAT, "profile": body}


def test_replacing_the_default_with_skip_all_is_shown_and_bound(env: SimpleNamespace) -> None:  # noqa: F811
    doc = _document(profile("claude-main", permissions="skip_all"))
    preview = env.client.post(PREVIEW, json={"document": doc}).json()
    assert {"kind": "permissions", "value": "skip_all", "text": "--dangerously-skip-permissions",
            "was": "harness_default", "was_text": "", "tone": "danger"} in preview["parts"]
    assert {"kind": "default", "value": "kept", "text": "claude-main"} in preview["parts"]

    bare = share.profile_digest(LaunchProfile.model_validate(doc["profile"]))
    assert preview["sha256"] != bare
    refused = env.client.post(IMPORT, json={"document": doc, "confirm_sha256": bare, "replace": True})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "digest_mismatch"
    ok = env.client.post(IMPORT, json={"document": doc, "confirm_sha256": preview["sha256"], "replace": True})
    assert ok.status_code == 200, ok.text


def test_a_pinned_account_is_shown(env: SimpleNamespace) -> None:  # noqa: F811
    doc = _document(profile("claude-pinned", account={"mode": "pinned", "account_id": "acct-7"}))
    preview = env.client.post(PREVIEW, json={"document": doc}).json()
    assert {"kind": "account", "value": "pinned", "text": "acct-7"} in preview["parts"]
