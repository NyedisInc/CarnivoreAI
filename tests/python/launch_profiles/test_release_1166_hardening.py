
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.account_switch import relay_candidates
from src.core.launch_profiles.agent_resume import valid_resume_id
from src.core.session_output.waits import _match_tail
from src.models.provider_ledger import AccountUsage


def test_resume_id_never_starts_with_a_dash():
    assert valid_resume_id("ses-1") == "ses-1"
    assert valid_resume_id("--dangerously-skip-permissions") is None and valid_resume_id("-x") is None


def test_wait_needle_cannot_match_inside_a_starred_span():
    secret = "SECRETVALUE123"
    clean = lambda t: t.replace(secret, "*" * len(secret))  # noqa: E731
    assert _match_tail(f"key {secret}\n", "SECRETVALUE", clean) is None
    assert _match_tail(f"key {secret}\n", "key", clean) == "key " + "*" * len(secret)


def test_future_fetched_at_does_not_keep_a_relayed_login_fresh():
    now = datetime.now(timezone.utc)
    row = AccountUsage(id="r", name="r", provider="claude", credential_state="ok", relayed=True,
                       fetched_at=now + timedelta(days=30), synced_at=now - timedelta(hours=1),
                       relay_expires_at=now + timedelta(hours=1))
    assert not relay_candidates.usable(row, now)
    assert relay_candidates.usable(row.model_copy(update={"synced_at": now}), now)
