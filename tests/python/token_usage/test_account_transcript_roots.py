
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.claude_config import transcript_roots
from src.core.listing_prefetch import ListingPrefetch, NameReads
from src.core.session_instance_index import InstanceFacts, InstanceIndex
from src.core.session_token_usage import reader
from src.core.session_token_usage.claude_reader import locate_transcript
from src.core.session_token_usage.listing_model_facts import build_model_listing_prefetch
from src.core.transcript_source import locate as sources

EPOCH = 1700000000
SESSIONS = {
    "cloude_globex": ("11111111-aaaa-bbbb-cccc-000000000001", "claude-opus-5"),
    "cloude_work": ("22222222-aaaa-bbbb-cccc-000000000002", "claude-sonnet-5"),
}


def _turn(model: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {"id": "m1", "model": model, "usage": {
            "input_tokens": 10, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "output_tokens": 5}},
    })


@pytest.fixture()
def two_profiles(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    accounts = []
    for account_id, (name, (uuid, model)) in zip(("globex", "nyedis"), SESSIONS.items()):
        profile = tmp_path / "accounts" / account_id
        folder = profile / "projects" / "-tmp-work"
        folder.mkdir(parents=True)
        (folder / f"{uuid}.jsonl").write_text(_turn(model) + "\n")
        accounts.append({"id": account_id, "name": account_id, "provider": "claude",
                         "claude_config_dir": str(profile)})
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider_accounts": {"accounts": accounts}}))
    from src.core.claude_config import profile_roots

    monkeypatch.setattr(profile_roots, "_default_config_path", lambda: config)
    transcript_roots.reset_transcript_roots_cache_for_tests()
    reader.reset_location_caches_for_tests()
    yield {name: "/tmp/work" for name in SESSIONS}
    transcript_roots.reset_transcript_roots_cache_for_tests()


def test_each_managed_account_session_gets_context_and_model(two_profiles):
    index = InstanceIndex(
        {(n, EPOCH): InstanceFacts(claude_session_uuid=u, working_dir="/tmp/work")
         for n, (u, _m) in SESSIONS.items()},
        complete=True,
    )
    prefetch = ListingPrefetch(
        by_name={n: NameReads(identity={"agent_family": "claude"}) for n in SESSIONS}
    )
    facts = build_model_listing_prefetch(
        names=list(SESSIONS),
        status_map={n: {"created_at_epoch": EPOCH} for n in SESSIONS},
        instance_index=index,
        prefetch=prefetch,
    )
    for name, (_uuid, model) in SESSIONS.items():
        assert facts[name].model == model
        assert facts[name].context_used_pct is not None


def test_a_conversation_in_no_root_is_still_absent(two_profiles):
    found = locate_transcript("99999999-aaaa-bbbb-cccc-000000000009", working_dir="/tmp/work")
    assert found.outcome == "absent"


def test_time_machine_locates_a_managed_account_transcript(two_profiles):
    uuid, _model = SESSIONS["cloude_work"]
    found = sources.locate("claude", uuid, "/tmp/work")
    assert found is not None and found.transcript.name == f"{uuid}.jsonl"


def test_roots_put_default_first_and_dedupe_a_symlinked_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    shared = home / ".claude" / "projects"
    shared.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    profile = tmp_path / "accounts" / "linked"
    profile.mkdir(parents=True)
    (profile / "projects").symlink_to(shared)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider_accounts": {"accounts": [
        {"id": "linked", "name": "linked", "provider": "claude", "claude_config_dir": str(profile)}]}}))
    transcript_roots.reset_transcript_roots_cache_for_tests()
    assert transcript_roots.claude_transcript_roots(config) == (shared,)
