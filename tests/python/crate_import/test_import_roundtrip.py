
from __future__ import annotations

import json
from collections import Counter
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Set, Tuple

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_import import ledger
from src.core.crate_import.keyrules import LIST_KEY, REF, rule_for
from src.core.crate_import.model import ImportRequest
from src.core.db import connect, db_path_for
from src.core.inventory.locations import Locations
from src.core.project_move.paths import PathMapping
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import ExportRequest, build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk.crate_sources import PaneListing
from tests.python.crate_import.install import Install
from tests.python.crate_import.test_import_plan import plan_of, target
from tests.python.crate_import.test_import_relocated import export_with_paths
from tests.python.crate_import.test_import_same_path import run
from tests.python.crate_import.test_import_work_side import target_install
from tests.python.inventory.world import UUID_A, UUID_B
from tests.python.session_purge.purge_world import insert

Rows = Dict[Tuple[str, str], List[Dict[str, Any]]]

INVENTORY_LABEL = {"carnivore.db": "cloude.db"}

TRANSFORMED_COLUMNS: Dict[str, Dict[str, str]] = {
    "projects": {"created_at": "7.1 a restored project is stamped now", "updated_at": "7.1", "last_opened_at": "7.1",
                 "source": "7.1 source user (the CHECK is verified)"},
    "sessions": {"claude_session_uuid_source": "7.2 IMPORTED_ROW_CONSTANTS", "legacy_session_id": "6.2 the app id is not carried",
                 "lifecycle_source": "7.2 import", "origin": "7.2 imported", "project_attribution": "7.2",
                 "tmux_created_epoch": "7.2 a NULL tmux identity", "tmux_name": "7.2 wake mints a fresh name"},
    "messaging_messages": {"reason": "7.9 an undelivered message is final", "status": "7.9 failed, never delivered here"},
    "crosstalk_messages": {"receiver_id": "7.10 live ids are not carried", "receiver_uuid": "7.10 the receiver is not imported",
                           "sender_id": "7.10"},
    "work_items": {"created_seq": "7.6 seq restamped", "seq": "7.6 seq restamped", "owner_session_key": "7.6 live owner markers reset"},
    "work_messages": {"seq": "7.6 seq restamped"},
    "work_sends": {"cursor": "7.6 restamped with the list", "target": "7.6 pending sends are final"},
    "work_item_nudges": {"count": "7.6 nudges cleared (K9)"},
    "work_item_triggers": {"fire_at": "7.6 triggers cleared (K9)", "paused": "7.6 nothing is due after an import"},
    "work_card_suggestions": {"by_agent": "7.6 suggestions land final"},
    "automations": {"enabled": "7.9 every automation arrives off", "project_id": "7.9 a project the crate does not carry reads null"},
    "automation_changes": {"seq": "7.9 the target's own change sequence"},
    "runs": {"seq": "7.9 the target's own run sequence"},
    "stats_annotations": {"scope_json": "7.9 the stats key is a hash of the project folder, so it follows the new root"},
}

COLLAPSED_ROWS: Dict[str, Tuple[Callable[[Mapping[str, Any]], bool], str]] = {
    "work_card_events": (lambda row: row.get("detail") != "imported", "7.6 the import adds one `imported` event per item"),
    "work_write_actors": (lambda row: False, "7.6 write actors are keyed by a live session and collapse to the item's creator"),
    "conversation_index": (lambda row: row.get("session_uuid") != "gone-session", "7.5 a row naming a session the crate does not carry is skipped"),
    "run_sessions": (lambda row: row.get("session_uuid") in (UUID_A, UUID_B),
                     "7.9 a row naming a session this crate does not restore is skipped (`run_or_session_not_here`)"),
}

ACCOUNTED_ELSEWHERE: Dict[str, str] = {
    "agent_spawn_links": "6.4 keyed by the app session id (`ses_...`), which an import never carries, so no session owns the row in crate two",
    "mcp_events": "7.5 caller_session_id and caller_tmux are nulled, so crate two cannot select the row by its caller",
    "work_item_lineage": "7.6 state moves are written as card events (`imported`), see COLLAPSED_ROWS",
    "work_inbox": "7.6 an add-box entry that names no carried item is not carried",
}

PATH_COLUMNS = {"working_dir", "raw_path", "root", "files_touched_json", "target"}


def _unmapped(value: Any, back: PathMapping) -> Any:
    if isinstance(value, str) and value.startswith(("[", "{")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, dict):
            return {k: _unmapped(v, back) for k, v in parsed.items()}
        return [_unmapped(item, back) for item in parsed]
    if isinstance(value, str):
        return back.apply(value) or value
    return value


def _normalize(rows: Rows, transformed: Mapping[str, Mapping[str, str]], back: PathMapping, id_back: Mapping[str, Mapping[Any, Any]]) -> Rows:
    out: Rows = {}
    for (store, table), table_rows in rows.items():
        keep = COLLAPSED_ROWS.get(table, (lambda row: True, ""))[0]
        dropped = set(transformed.get(table, {}))
        shaped = []
        for row in table_rows:
            if not keep(row):
                continue
            item = {c: v for c, v in row.items() if c not in dropped}
            for column in PATH_COLUMNS & set(item):
                item[column] = _unmapped(item[column], back)
            if "id" in item and table in id_back:
                item["id"] = id_back[table].get(item["id"], item["id"])
            for column in set(item) - {"id"}:
                rule = rule_for(INVENTORY_LABEL.get(store, store), table, column)
                if rule is None or item[column] is None:
                    continue
                if rule.kind == LIST_KEY and str(item[column]).isdigit():
                    item[column] = str(id_back.get("projects", {}).get(int(item[column]), int(item[column])))
                elif rule.kind == REF:
                    target_table, _dot, target_column = (rule.target or "").partition(".")
                    if target_column == "id" and target_table in id_back:
                        item[column] = id_back[target_table].get(item[column], item[column])
            shaped.append(item)
        out[(store, table)] = sorted(shaped, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return out


def compare(rows_a: Rows, rows_b: Rows, transformed: Mapping[str, Mapping[str, str]], back: PathMapping,
            id_back: Mapping[str, Mapping[Any, Any]]) -> List[str]:
    a, b = _normalize(rows_a, transformed, PathMapping.of([]), {}), _normalize(rows_b, transformed, back, id_back)
    return [f"{key[0]}.{key[1]}: {len(a[key])} rows vs {len(b[key])}" for key in sorted(set(a) & set(b)) if a[key] != b[key]]


def crate_facts(path: Path) -> Tuple[Counter, Rows]:
    with cf.open_crate(path) as reader:
        files = Counter((f.role, f.content_sha256) for f in reader.files())
        rows = {(store, table): list(reader.rows(store, table)) for store, by_name in reader.tables().items() for table in by_name}
    return files, rows


def export_installed(install: Install, root: str) -> Path:
    work = install.state / "cplugs" / "crate"
    work.mkdir(parents=True, exist_ok=True)
    locations = Locations(state_dir=install.state, config_path=install.state / "config.json", homes=(install.claude,), codex=install.codex)
    env = CrateEnv(state=install.state, locations=locations, work=work, settings={}, live_panes=lambda: PaneListing(ok=True, panes=()))
    plan = build_export_plan(env, ExportRequest("project", root, "own"))
    assert plan.ok, plan.blockers
    return run_export(env, plan, JobHandle("s8")).path


def busy_target(tmp: Path, crate: SimpleNamespace) -> Install:
    install = target_install(tmp, crate, shift=3)
    with closing(install.db()) as conn:
        for n in range(2):
            insert(conn, "sessions", session_uuid=f"local-{n}", working_dir=str(install.projects / "other-0"), lifecycle="stopped",
                   origin="user", created_at="now", updated_at="now")
        conn.commit()
    return install


def trip(tmp: Path) -> SimpleNamespace:
    crate = export_with_paths(tmp)
    install = busy_target(tmp, crate)
    new = str(install.projects / "moved")
    request = ImportRequest(mode="relocate", new_root=new)
    preview = plan_of(crate, install.env, request)
    receipt = run(crate, install, request=request)
    assert receipt.state in ("done", "done_with_warnings") and receipt.checks["file_mismatch"] == [], receipt.warnings
    real_new = str(Path(new).resolve())
    with closing(connect(db_path_for(install.state), create=False)) as conn:
        entry = ledger.read_entry(conn, receipt.import_id)
    id_back = {key.split(".")[-1]: {int(new_id): int(old) for old, new_id in ids.items()} for key, ids in entry["key_map"].items()}
    second = export_installed(install, real_new)
    files_a, rows_a = crate_facts(crate.path)
    files_b, rows_b = crate_facts(second)
    back = PathMapping.of([(real_new, crate.world.root1)])
    return SimpleNamespace(crate=crate, install=install, preview=preview, receipt=receipt, new=real_new, files_a=files_a, files_b=files_b,
                           rows_a=rows_a, rows_b=rows_b, back=back, id_back=id_back)


@pytest.fixture(scope="module")
def tripped(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    return trip(tmp_path_factory.mktemp("roundtrip").resolve())


def test_every_file_survives_the_trip_byte_for_byte(tripped: SimpleNamespace) -> None:
    only_a = {role for (role, sha) in tripped.files_a if (role, sha) not in tripped.files_b}
    announced = {line["what"].split(":")[1].split(" ")[0] for line in tripped.preview["not_restored"] if line["what"].startswith("files:")}
    assert only_a and only_a <= announced, f"roles lost without a word: {only_a - announced}"
    assert {k for k in tripped.files_b if k not in tripped.files_a} == set(), "the second crate holds no file the first lacked"
    for role in ("transcript", "subagent", "todo", "file_history", "task_file"):
        assert any(r == role for (r, _sha) in tripped.files_b), role


def test_the_receipt_counts_an_orphan_conversation_as_restored(tripped: SimpleNamespace) -> None:
    assert not [n for n in tripped.receipt.not_restored if n["what"].startswith("files:orphan_transcript")]
    assert not [c for c in tripped.receipt.conversations if c["class"] == "not_restored"]


def test_the_busy_world_forces_every_minted_id_to_differ(tripped: SimpleNamespace) -> None:
    for table in ("projects", "sessions", "work_items"):
        assert tripped.id_back[table] and all(new != old for new, old in tripped.id_back[table].items()), table


def test_the_claude_folder_is_the_new_roots_long_spelling(tripped: SimpleNamespace) -> None:
    folder = tripped.install.claude / "projects" / slugify_project_dir(tripped.new)
    assert folder.is_dir() and any(folder.glob("*.jsonl"))
    assert [p.name for p in (tripped.install.claude / "projects").iterdir()] == [folder.name]
    with cf.open_crate(tripped.crate.path) as first:
        assert {f.enc_folder for f in first.files() if f.enc_folder} != {folder.name}, "the first crate recorded the OLD folder name"


def test_every_row_both_crates_carry_agrees_after_the_documented_transformations(tripped: SimpleNamespace) -> None:
    assert compare(tripped.rows_a, tripped.rows_b, TRANSFORMED_COLUMNS, tripped.back, tripped.id_back) == []
    for table, columns in TRANSFORMED_COLUMNS.items():
        assert all(section for section in columns.values()), f"{table} cites no plan section"
    working = {r["working_dir"] for key, rows in tripped.rows_b.items() if key[1] == "sessions" for r in rows}
    assert working == {tripped.new}, "B's crate names the new root"


def test_the_comparison_catches_an_untransformed_column(tripped: SimpleNamespace) -> None:
    for table, column in (("sessions", "tmux_name"), ("work_items", "owner_session_key"), ("projects", "source")):
        trimmed = {t: {c: s for c, s in cols.items() if not (t == table and c == column)} for t, cols in TRANSFORMED_COLUMNS.items()}
        assert compare(tripped.rows_a, tripped.rows_b, trimmed, tripped.back, tripped.id_back), f"{table}.{column} would pass unnoticed"


def test_skipping_the_path_mapping_fails(tripped: SimpleNamespace) -> None:
    identity = PathMapping.of([])
    assert compare(tripped.rows_a, tripped.rows_b, TRANSFORMED_COLUMNS, identity, tripped.id_back), "unmapped paths must differ"


def test_tables_only_the_first_crate_carries_are_announced(tripped: SimpleNamespace) -> None:
    only_a = {f"{store.replace('carnivore.db', 'cloude.db')}.{table}" for (store, table), rows in tripped.rows_a.items()
              if rows and (store, table) not in tripped.rows_b}
    announced = {line["what"] for line in tripped.preview["not_restored"]}
    absent_stores = {w["detail"] for w in tripped.receipt.warnings if w["code"] == "side_store_absent"}
    unannounced = {name for name in only_a if name not in announced and name.split(".")[0] + ".db" not in absent_stores
                   and name.rsplit(".", 1)[0] not in absent_stores and name not in {f"cloude.db.{t}" for t in ACCOUNTED_ELSEWHERE}}
    assert not unannounced, f"tables lost without a word: {sorted(unannounced)}"
    assert all(reason for reason in ACCOUNTED_ELSEWHERE.values())
