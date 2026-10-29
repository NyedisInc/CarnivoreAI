
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.db import db_path_for
from src.core.inventory import file_claims, registry
from src.core.inventory.registry_side import side_db_path
from src.cplugs.crate import policy as P
from src.cplugs.crate.plan import build_plan
from src.cplugs.sdk import crate_sources as cs
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request, session_request

ACTIONS = {P.CARRY, P.EXCLUDE, P.DERIVED, P.OPTIONAL}
CLAUDE_ROLES = ("transcript", P.FOLDER_CONVERSATION, "set_aside_transcript", "conflict_copy", "archived_copy",
                "file_history", "todo", "plan", "session_env", "debug", "pid_registry", "history_lines")
CODEX_ROLES = ("codex_rollout", "shell_snapshot", "index_lines")
ENTRY_STORES = (cs.UNREAD_STORE, cs.CONFIG_STORE, cs.RENAME_STORE, cs.CLAUDE_JSON_STORE, cs.PREFERENCES, cs.JOURNAL,
                cs.PINNED_THEMES_FILE)
SECRET_LOOKALIKES = {("cloude.db", "message_bodies", "secret_finding_count"): "a count of findings, never a value"}
_SECRET_NAME = re.compile(r"token|secret|password|nonce|api_key|credential", re.I)


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> SimpleNamespace:
    return make_world(tmp_path_factory.mktemp("crate-policy"))


def _keys_for_store(store: str) -> list:
    return [k for k in P.POLICY if k.split("/", 1)[0] == store]


def test_every_store_label_has_a_row() -> None:
    labels = {v for k, v in vars(file_claims).items() if k.startswith("STORE_")} | {cs.STORE_VAULT}
    for label in sorted(labels):
        assert _keys_for_store(label), f"no crate policy row for store {label}"
    for role in CLAUDE_ROLES:
        assert f"claude/{role}" in P.POLICY, role
    for role in CODEX_ROLES:
        assert f"codex/{role}" in P.POLICY, role
    for store in ENTRY_STORES:
        assert f"entry/{store}" in P.POLICY, store
    for store in [cs.MAIN_STORE, *cs.SIDE_DBS]:
        assert f"rows/{store}" in P.POLICY, store


def test_every_row_decides_both_variants() -> None:
    for key, rule in P.POLICY.items():
        assert rule.own in ACTIONS and rule.share in ACTIONS and rule.reason, key


def test_the_vault_row_is_optional_for_an_own_crate_only() -> None:
    rule = P.POLICY[f"{cs.STORE_VAULT}/*"]
    assert rule.own == P.OPTIONAL and rule.share == P.EXCLUDE


def test_never_carried_stores_stay_out() -> None:
    for key in ("claude/session_env", "claude/debug", "claude/pid_registry", "codex/shell_snapshot"):
        assert P.POLICY[key].own == P.EXCLUDE and P.POLICY[key].share == P.EXCLUDE, key


@pytest.mark.parametrize("scope", ["project", "session"])
def test_the_world_resolves_with_no_blocked_decision(world: SimpleNamespace, scope: str) -> None:
    request = project_request(world) if scope == "project" else session_request()
    plan = build_plan(env_for(world), request)
    assert not [b for b in plan.blockers if b["code"] == "no_crate_policy"], plan.blockers
    assert plan.ok, plan.blockers


def test_removing_a_row_blocks(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(P.POLICY, "claude/transcript")
    plan = build_plan(env_for(world), session_request())
    assert any(b["code"] == "no_crate_policy" and "claude/transcript" in b["detail"] for b in plan.blockers)


def test_every_gap_store_is_listed_in_a_project_plan(world: SimpleNamespace) -> None:
    plan = build_plan(env_for(world), project_request(world))
    gaps = {s.store for s in cs.EXCLUDED_STORES if s.kind == cs.GAP}
    assert gaps and gaps == {e["store"] for e in plan.excluded if e["kind"] == "gap"}
    assert all(any(g in w for w in plan.warnings) for g in gaps)


def test_secret_looking_columns_are_secret_or_explained(world: SimpleNamespace) -> None:
    found = []
    for claim in registry.book().claims:
        path = db_path_for(world.state) if claim.store == cs.MAIN_STORE else side_db_path(world.state, claim.store)
        with closing(sqlite3.connect(path)) as conn:
            columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{claim.table}")')]
        for column in columns:
            if _SECRET_NAME.search(column) and column not in claim.secret:
                found.append((claim.store, claim.table, column))
    assert set(found) <= set(SECRET_LOOKALIKES), sorted(set(found) - set(SECRET_LOOKALIKES))
    assert all(SECRET_LOOKALIKES.values())


def test_the_secret_check_can_fail(world: SimpleNamespace) -> None:
    claim = next(c for c in registry.book().claims if c.store == cs.MAIN_STORE and c.table == "work_item_waits")
    assert "token_hash" in claim.secret
    assert _SECRET_NAME.search("token_hash")


def test_a_file_inside_a_conversation_folder_takes_its_role() -> None:
    assert P.file_role(None, "subagents/agent-1.jsonl") == "subagent"
    assert P.file_role(None, "tool-results/r.txt") == "tool_result"
    assert P.file_role(None, "other/x.bin") == "conversation_file"
    assert P.file_role("file_history", "a/b") == "file_history"
    assert P.line_mode("conflict_copy", "c 2.jsonl") and not P.line_mode("conflict_copy", "c 2")
    assert P.line_mode("set_aside_transcript", "c.jsonl.bak") and not P.line_mode("todo", "c.json")


def test_projects_paths_classify_by_the_layout_rule(tmp_path: Path) -> None:
    home = tmp_path / "h"
    homes = P.HomesView((str(home.resolve()),), str((tmp_path / "x").resolve()), str((tmp_path / "s").resolve()))
    def art(rel: str, kind: str = "file", store: str = "claude") -> cs.Artifact:
        path = str(home / rel)
        return cs.Artifact(store=store, kind=kind, what=path, count=1, locator={"path": path})
    (home / "projects").mkdir(parents=True)
    assert P.classify(art("projects/-a/c1.jsonl"), homes) == ("claude/transcript", "transcript")
    assert P.classify(art("projects/-a/c1", "dir"), homes) == (f"claude/{P.FOLDER_CONVERSATION}", None)
    assert P.classify(art("projects/-a/c1.jsonl.old"), homes)[0] == "claude/set_aside_transcript"
    assert P.classify(art("projects/-a/c1 2.jsonl"), homes)[0] == "claude/conflict_copy"
    assert P.classify(art("projects/_hold/-a/c1.jsonl"), homes)[0] == "claude/archived_copy"
    assert P.classify(art("plans/my-plan.md"), homes)[0] == "claude/plan"
    assert P.classify(art("weird/x"), homes)[0] == "claude/unknown"
    assert P.decide(art("weird/x"), "own", homes).action == P.BLOCKED


def test_a_home_folder_linked_to_its_nosync_twin_keeps_its_role(tmp_path: Path) -> None:
    home = tmp_path / "h"
    for name in ("file-history", "sessions", "session-env"):
        (home / f"{name}.nosync").mkdir(parents=True)
        (home / name).symlink_to(f"{name}.nosync")
    (home / "file-history" / "c1").mkdir()
    (home / "sessions" / "19021.json").write_text("{}")
    (home / "session-env" / "c1").mkdir()
    homes = P.HomesView((str(home.resolve()),), str((tmp_path / "x").resolve()), str((tmp_path / "s").resolve()))
    def art(rel: str, kind: str) -> cs.Artifact:
        path = str(home / rel)
        return cs.Artifact(store="claude", kind=kind, what=path, count=1, locator={"path": path})
    assert homes.place(str(home / "file-history" / "c1" / "a@v1")) == (P.HOME_CLAUDE, 0, "file-history/c1/a@v1")
    assert P.classify(art("file-history/c1", "dir"), homes) == ("claude/file_history", P.R_FILE_HISTORY)
    assert P.decide(art("file-history/c1", "dir"), "own", homes).action == P.CARRY
    assert P.decide(art("file-history/c1", "dir"), "share", homes).action == P.EXCLUDE
    assert P.decide(art("sessions/19021.json", "file"), "own", homes).action == P.EXCLUDE
    assert P.decide(art("session-env/c1", "dir"), "own", homes).action == P.EXCLUDE
