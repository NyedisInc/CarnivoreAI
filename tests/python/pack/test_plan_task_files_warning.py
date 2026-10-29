
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Tuple

import pytest

pytest.importorskip("fastapi")

from src.api import pack_migrate_env as env_mod  # noqa: E402
from src.core.pack.migrate import apply, plan, task_manager_side  # noqa: E402
from src.core.work import file_refs  # noqa: E402
from src.core.pack.migrate.ops import MAX_LISTED_FILES  # noqa: E402
from src.cplugs.sdk import ports, task_folders  # noqa: E402
from tests.python.pack.test_migrate_two_machines import seed, world  # noqa: E402,F401
from tests.python.pack.test_task_file_paths import FILE_ID, FakeRoot, entry_for, task_folder  # noqa: E402
from tests.python.pack.test_task_manager_side_compat import sql  # noqa: E402

CAPS = (task_manager_side.CAP_TASK_FILES_PLAN,)
Planner = Callable[..., plan.Plan]
PREPARE_PATH = "/federation/pack/migrate/prepare"


@pytest.fixture()
def planner(world) -> Iterator[Tuple[Planner, Any]]:
    a, b, _current, link = world
    uid = seed(a)
    with closing(a.conn()) as conn:
        project = dict(conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone())

    sent: List[Dict[str, Any]] = []

    def recording(request: Any) -> Any:
        async def wrapped(method: str, path: str, **kw: Any) -> Any:
            if path == PREPARE_PATH:
                sent.append(kw.get("json") or {})
            return await request(method, path, **kw)
        return wrapped

    def plan_with(files: List[Dict[str, Any]], caps: Tuple[str, ...] = CAPS, extra_documents: List[List[Dict[str, Any]]] = (),
                  extra_parts: List[str] = ()) -> plan.Plan:
        sql(str(a.state), "DELETE FROM work_messages WHERE parts != ''")
        documents = ([json.dumps({"files": files})] if files else []) + [json.dumps({"files": f}) for f in extra_documents] + list(extra_parts)
        for n, text in enumerate(documents, 9):
            sql(str(a.state), "INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, parts) VALUES (1, 'joe', 'say', 'see', 1, ?, ?)", (n, text))
        return asyncio.run(plan.plan_project(env_mod.source_env(), project, "iid-b", apply.guarded(recording(link(a, b))), target_caps=caps))

    plan_with.sent = sent  # type: ignore[attr-defined]
    yield plan_with, b


def warning(made: plan.Plan) -> Dict[str, Any]:
    return next((c for c in made.checks if c["name"] == "task_files_not_carried"), {})


def elsewhere(n: int = 0, name: str = "shot.png") -> Dict[str, Any]:
    return entry_for(f"/elsewhere/{n}/{FILE_ID}-{name}", name=name)


def test_the_plan_names_the_files_the_other_computer_will_drop(planner) -> None:
    plan_with, _b = planner
    made = plan_with([elsewhere()])
    check = warning(made)
    assert check["files"] == ["shot.png"] and check["files_more"] == 0
    assert check["ok"] is False and check["blocking"] is False and made.view()["can_apply"] is True


def test_equal_names_stay_and_a_long_list_is_capped_with_the_rest_counted(planner) -> None:
    plan_with, _b = planner
    check = warning(plan_with([elsewhere(i, "image.png") for i in range(MAX_LISTED_FILES + 5)]))
    assert check["files"] == ["image.png"] * MAX_LISTED_FILES and check["files_more"] == 5


def test_a_move_with_nothing_to_drop_has_no_warning_and_the_same_fingerprint(planner) -> None:
    plan_with, _b = planner
    judged, unjudged = plan_with([]), plan_with([], caps=())
    assert warning(judged) == {} and judged.fingerprint == unjudged.fingerprint


def test_a_target_that_cannot_judge_gets_no_new_field_and_the_plan_still_works(planner) -> None:
    plan_with, _b = planner
    assert warning(plan_with([elsewhere()], caps=())) == {}


def reachable(tmp_path: Path) -> Tuple[Path, Callable[[], None]]:
    paste = task_folder(tmp_path)
    ports.register(task_folders.ROOT_PORT, FakeRoot(tmp_path / "tm"))
    return paste, lambda: ports.unregister(task_folders.ROOT_PORT)


def test_a_file_the_target_can_reach_is_not_warned_about_and_nothing_is_written(planner, tmp_path: Path) -> None:
    plan_with, b = planner
    paste, cleanup = reachable(tmp_path)
    try:
        assert warning(plan_with([entry_for(str(paste))])) == {}
        assert not (b.state / "cplugs" / "huddle" / "files").exists()
    finally:
        cleanup()


def test_the_look_reads_no_file_bytes(planner, tmp_path: Path, monkeypatch) -> None:
    plan_with, _b = planner
    paste, cleanup = reachable(tmp_path)
    touched: List[str] = []
    real_hash, real_chunks = file_refs._hash_of, file_refs._chunks
    monkeypatch.setattr(file_refs, "_hash_of", lambda path: touched.append(path) or real_hash(path))
    monkeypatch.setattr(file_refs, "_chunks", lambda path: touched.append(path) or real_chunks(path))
    try:
        plan_with([entry_for(str(paste))])
    finally:
        cleanup()
    assert touched == []


def test_an_oversized_document_is_skipped_and_never_fails_the_plan(planner) -> None:
    plan_with, _b = planner
    huge = entry_for(f"/elsewhere/{FILE_ID}-big.png", name="x" * (task_manager_side.MAX_PART_CHARS + 1))
    check = warning(plan_with([elsewhere()], extra_documents=[[huge]]))
    assert check["files"] == ["shot.png"] and check["files_unchecked"] == 1
    assert all(len(text) <= task_manager_side.MAX_PART_CHARS for body in plan_with.sent for text in body.get("task_file_parts", []))


def test_only_documents_that_name_files_are_sent(planner) -> None:
    plan_with, _b = planner
    plan_with([elsewhere()], extra_parts=['{"notes": "no files here"}', '{"files": []}'])
    [body] = plan_with.sent[-1:]
    assert len(body["task_file_parts"]) == 1


def test_an_old_receiver_is_never_sent_the_field_and_the_plan_still_succeeds(planner) -> None:
    plan_with, _b = planner
    made = plan_with([elsewhere()], caps=())
    assert "task_file_parts" not in plan_with.sent[-1] and warning(made) == {} and made.view()["can_apply"] is True


def test_a_failure_in_the_target_s_look_says_could_not_check_not_a_failed_plan_or_a_clean_one(planner, monkeypatch) -> None:
    plan_with, _b = planner

    def broken(self: Any, *args: Any, **kw: Any) -> Any:
        raise OSError("disk went away")

    monkeypatch.setattr(file_refs.FileHome, "rewrite_message", broken)
    made = plan_with([elsewhere()])
    check = warning(made)
    assert check["files"] == [] and check["files_check_failed"] is True and "could not be checked" in check["detail"] and made.view()["can_apply"] is True


def test_a_failure_building_the_probe_says_could_not_check_not_a_failed_plan(planner, monkeypatch) -> None:
    plan_with, _b = planner
    monkeypatch.setattr(task_manager_side, "task_file_parts", lambda data: (_ for _ in ()).throw(TypeError("bad rows")))
    made = plan_with([elsewhere()])
    assert "could not be checked" in warning(made)["detail"] and "task_file_parts" not in plan_with.sent[-1] and made.view()["can_apply"] is True


def test_a_very_deeply_nested_document_is_could_not_check_not_a_failed_plan(planner) -> None:
    plan_with, _b = planner
    deep = "[" * 20000 + "]" * 20000
    made = plan_with([elsewhere()], extra_parts=[deep])
    check = warning(made)
    assert check["files"] == ["shot.png"] and check["files_check_failed"] is True and "could not be checked" in check["detail"] and made.view()["can_apply"] is True


def test_documents_left_out_alone_still_show_the_note(planner) -> None:
    plan_with, _b = planner
    huge = entry_for(f"/elsewhere/{FILE_ID}-big.png", name="x" * (task_manager_side.MAX_PART_CHARS + 1))
    check = warning(plan_with([], extra_documents=[[huge]]))
    assert check["files"] == [] and check["files_unchecked"] == 1 and "could not be checked" in check["detail"]


def test_a_clean_check_shows_nothing(planner) -> None:
    plan_with, _b = planner
    assert warning(plan_with([])) == {}
