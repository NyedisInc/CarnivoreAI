
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_srm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_srm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

# ruff: noqa: E402
from tests.test_session_token_usage import UUID, _assistant, _claude_corpus
from tests.test_listing_off_the_loop import _FakeBackend, _manager_with, _status_rows
from src.core.listing_prefetch import ListingPrefetch, NameReads
from src.core.session_instance_index import InstanceFacts, InstanceIndex
from src.core.session_token_usage import listing_model_facts as lmf
from src.core.session_token_usage.listing_model_facts import (
    ModelListingFacts,
    build_model_listing_prefetch,
)
from src.core.session_token_usage.model_table import cost_tier_for_model

NAME = "cloude_srm_row"
EPOCH = 1700000000


def _prefetch_with(name: str, agent_family: Optional[str]) -> ListingPrefetch:
    identity = {"agent_family": agent_family} if agent_family is not None else {}
    return ListingPrefetch(by_name={name: NameReads(identity=identity)})


def _index_with(
    name: str, epoch: int, uuid: Optional[str], working_dir: Optional[str]
) -> InstanceIndex:
    return InstanceIndex(
        {(name, epoch): InstanceFacts(claude_session_uuid=uuid, working_dir=working_dir)},
        complete=True,
    )


def test_context_used_pct_inverts_the_readers_headroom_and_keeps_unknown_none():
    assert lmf.context_used_pct(58.5) == 41.5
    assert lmf.context_used_pct(100.0) == 0.0
    assert lmf.context_used_pct(-3.0) == 100.0
    assert lmf.context_used_pct(None) is None




def test_claude_session_reports_model_effort_and_tier(tmp_path, monkeypatch):
    record = _assistant("msg_1", "claude-opus-5", inp=10, cache_creation=0,
                         cache_read=0, out=5)
    record["effort"] = "high"
    corpus = _claude_corpus(tmp_path, [json.dumps(record)])

    real = lmf.read_session_token_usage
    monkeypatch.setattr(
        lmf,
        "read_session_token_usage",
        lambda subject, projects_dir=None, codex_home=None, max_cold_bytes=None: real(
            subject,
            projects_dir=corpus,
            codex_home=codex_home,
            max_cold_bytes=max_cold_bytes,
        ),
    )

    facts = build_model_listing_prefetch(
        names=[NAME],
        status_map={NAME: {"created_at_epoch": EPOCH}},
        instance_index=_index_with(NAME, EPOCH, UUID, "/tmp/project"),
        prefetch=_prefetch_with(NAME, "claude"),
    )

    assert NAME in facts, "a name this pass covered must always be a member"
    entry = facts[NAME]
    assert entry.model == "claude-opus-5"
    assert entry.model_effort == "high"
    assert entry.model_tier == cost_tier_for_model("claude-opus-5")
    assert entry.model_tier == 4
    assert entry.family == "claude"
    assert entry.context_used_pct is not None and 0.0 <= entry.context_used_pct < 1.0


def test_blank_stored_family_resolves_via_agent_type(tmp_path, monkeypatch):
    record = _assistant("msg_1", "claude-opus-5", inp=10, cache_creation=0,
                         cache_read=0, out=5)
    record["effort"] = "high"
    corpus = _claude_corpus(tmp_path, [json.dumps(record)])

    real = lmf.read_session_token_usage
    monkeypatch.setattr(
        lmf,
        "read_session_token_usage",
        lambda subject, projects_dir=None, codex_home=None, max_cold_bytes=None: real(
            subject,
            projects_dir=corpus,
            codex_home=codex_home,
            max_cold_bytes=max_cold_bytes,
        ),
    )

    class _FakeWrapper:
        def __init__(self, wid, family):
            self.id = wid
            self.family = family

    class _FakeAgents:
        def __init__(self, wrappers):
            self.wrappers = wrappers

    class _FakeAuth:
        def __init__(self, wrappers):
            self.agents = _FakeAgents(wrappers)

    from src.config import settings as real_settings

    monkeypatch.setattr(
        type(real_settings),
        "load_auth_config",
        lambda self: _FakeAuth([_FakeWrapper("claude-chrome", "claude")]),
    )

    prefetch = ListingPrefetch(by_name={
        NAME: NameReads(identity={"agent_family": None, "agent_type": "claude-chrome"})
    })
    facts = build_model_listing_prefetch(
        names=[NAME],
        status_map={NAME: {"created_at_epoch": EPOCH}},
        instance_index=_index_with(NAME, EPOCH, UUID, "/tmp/project"),
        prefetch=prefetch,
    )

    assert NAME in facts, "a name this pass covered must always be a member"
    entry = facts[NAME]
    assert entry.family == "claude", (
        "the reader was never dispatched: agent_type did not resolve"
    )
    assert entry.model == "claude-opus-5"
    assert entry.model_effort == "high"
    assert entry.model_tier == cost_tier_for_model("claude-opus-5")


def test_unpriced_model_gives_an_id_but_no_tier(tmp_path, monkeypatch):
    record = _assistant("msg_1", "claude-nova-9", inp=1, cache_creation=0,
                         cache_read=0, out=1)
    corpus = _claude_corpus(tmp_path, [json.dumps(record)])

    real = lmf.read_session_token_usage
    monkeypatch.setattr(
        lmf,
        "read_session_token_usage",
        lambda subject, projects_dir=None, codex_home=None, max_cold_bytes=None: real(
            subject,
            projects_dir=corpus,
            codex_home=codex_home,
            max_cold_bytes=max_cold_bytes,
        ),
    )

    facts = build_model_listing_prefetch(
        names=[NAME],
        status_map={NAME: {"created_at_epoch": EPOCH}},
        instance_index=_index_with(NAME, EPOCH, UUID, "/tmp/project"),
        prefetch=_prefetch_with(NAME, "claude"),
    )

    entry = facts[NAME]
    assert entry.model == "claude-nova-9", "the user's own model choice is still named"
    assert entry.model_tier is None, "a model the price table does not carry has no tier"


class _PoisonUsage:

    state = "ok"
    model = "SPY-SHOULD-NEVER-BE-READ"
    effort = "SPY"
    model_cost_tier = 9


def test_a_family_with_no_reader_costs_no_file_read(monkeypatch):
    monkeypatch.setattr(
        lmf, "read_session_token_usage", lambda *_a, **_kw: _PoisonUsage()
    )

    facts = build_model_listing_prefetch(
        names=[NAME],
        status_map={NAME: {"created_at_epoch": EPOCH}},
        instance_index=_index_with(NAME, EPOCH, UUID, "/tmp/project"),
        prefetch=_prefetch_with(NAME, "hermes"),
    )

    entry = facts[NAME]
    assert entry == ModelListingFacts(family="hermes")
    assert entry.model is None
    assert entry.model_effort is None
    assert entry.model_tier is None


def test_no_uuid_costs_no_file_read_either(monkeypatch):
    monkeypatch.setattr(
        lmf, "read_session_token_usage", lambda *_a, **_kw: _PoisonUsage()
    )

    facts = build_model_listing_prefetch(
        names=[NAME],
        status_map={NAME: {"created_at_epoch": EPOCH}},
        instance_index=_index_with(NAME, EPOCH, None, None),
        prefetch=_prefetch_with(NAME, "claude"),
    )

    assert facts[NAME] == ModelListingFacts(family="claude")




def test_absent_transcript_keeps_agent_identity_but_clears_model(
    tmp_path, monkeypatch
):
    name = "cloude_srm_absent"
    manager = _manager_with([("ses_srm_absent", name)])
    monkeypatch.setattr(
        manager, "_build_tmux_status_map", lambda: _status_rows([name])
    )
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: None)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: set())
    monkeypatch.setattr(
        manager,
        "_identity_for_live_name",
        lambda _n: {
            "id": 7,
            "parent_session_id": None,
            "agent_type": "claude",
            "agent_family": "claude",
            "agent_family_source": "launched",
            "project_id": None,
            "project_name": None,
        },
    )
    fresh_uuid = "99999999-8888-7777-6666-555555555555"
    monkeypatch.setattr(
        manager,
        "_instance_index_for_listing",
        lambda **_kw: _index_with(name, EPOCH, fresh_uuid, "/tmp/nowhere"),
    )
    import src.core.session_manager as sm_mod

    monkeypatch.setattr(
        sm_mod.listing_attention,
        "resolve_row_status_live",
        lambda **_kw: ("unknown", "none", None),
    )
    empty_corpus = tmp_path / "empty_corpus"
    empty_corpus.mkdir()
    real = lmf.read_session_token_usage
    monkeypatch.setattr(
        lmf,
        "read_session_token_usage",
        lambda subject, projects_dir=None, codex_home=None, max_cold_bytes=None: real(
            subject,
            projects_dir=empty_corpus,
            codex_home=codex_home,
            max_cold_bytes=max_cold_bytes,
        ),
    )

    infos = asyncio.run(manager.list_session_infos())

    assert len(infos) == 1
    info = infos[0]
    assert info.agent_type == "claude"
    assert info.agent_family == "claude"
    assert info.running_model is None
    assert info.running_model_effort is None
    assert info.running_model_tier is None


def test_a_claude_session_is_decorated_through_the_full_listing_pass(
    tmp_path, monkeypatch
):
    name = "cloude_srm_ok"
    manager = _manager_with([("ses_srm_ok", name)])
    monkeypatch.setattr(
        manager, "_build_tmux_status_map", lambda: _status_rows([name])
    )
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: None)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: set())
    monkeypatch.setattr(
        manager,
        "_identity_for_live_name",
        lambda _n: {
            "id": 8,
            "parent_session_id": None,
            "agent_type": "claude",
            "agent_family": "claude",
            "agent_family_source": "launched",
            "project_id": None,
            "project_name": None,
        },
    )
    monkeypatch.setattr(
        manager,
        "_instance_index_for_listing",
        lambda **_kw: _index_with(name, EPOCH, UUID, "/tmp/project"),
    )
    import src.core.session_manager as sm_mod

    monkeypatch.setattr(
        sm_mod.listing_attention,
        "resolve_row_status_live",
        lambda **_kw: ("unknown", "none", None),
    )
    record = _assistant("msg_1", "claude-sonnet-5", inp=1, cache_creation=0,
                         cache_read=0, out=1)
    corpus = _claude_corpus(tmp_path, [json.dumps(record)])
    real = lmf.read_session_token_usage
    monkeypatch.setattr(
        lmf,
        "read_session_token_usage",
        lambda subject, projects_dir=None, codex_home=None, max_cold_bytes=None: real(
            subject,
            projects_dir=corpus,
            codex_home=codex_home,
            max_cold_bytes=max_cold_bytes,
        ),
    )

    infos = asyncio.run(manager.list_session_infos())

    assert len(infos) == 1
    info = infos[0]
    assert info.agent_family == "claude"
    assert info.running_model == "claude-sonnet-5"
    assert info.running_model_tier == cost_tier_for_model("claude-sonnet-5")
