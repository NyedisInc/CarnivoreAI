
from __future__ import annotations

import io
import json
from pathlib import Path

from src.cplugs.host import runtime
from src.cplugs.huddle.cli import move_files_to_root as cli
from tests.python.cplugs.huddle.test_task_manager_task_files import (  # noqa: F401
    BASE, PAGE, add, app, client, no_config, paste, plugin_folder, reply, stored_parts)


def work_db(app) -> Path:
    return runtime.host_for(app).storage("huddle").db_path


def tree(folder: Path) -> dict:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def setup_old_files(client, app):
    a = add(client, "12", "Watch what Alex changed")
    b = add(client, "all", "groceries")
    f = paste(client, a)
    reply(client, a, [f["id"]])
    g = paste(client, b, "list.txt", b"milk")
    reply(client, b, [g["id"]])
    art = client.post(f"{BASE}/items/{a}/artifacts", json={"title": "Layout", "html": PAGE}).json()["message"]
    paste(client, a, "abandoned.txt", b"never sent")
    return a, b, f, art


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "tm"
    root.mkdir()
    (root / ".boards-root").write_text("")
    return root


def run(*args: str):
    out = io.StringIO()
    code = cli.main(list(args), out)
    return code, out.getvalue()


def test_the_dry_run_plans_and_writes_nothing(client, app, tmp_path: Path):
    a, b, f, art = setup_old_files(client, app)
    root = make_root(tmp_path)
    db = work_db(app)
    before_root, before_db = tree(root), db.read_bytes()
    code, text = run("--work-db", str(db), "--root", str(root))
    assert code == 0, text
    assert f"item {a} -> project-12/watch-what-alex-changed-{a}/ : 1 pastes, 1 artifacts" in text
    assert f"item {b} -> no-project/groceries-{b}/ : 1 pastes" in text
    assert "total: 3 files" in text and "3 messages rewritten" in text and "dry run" in text
    assert tree(root) == before_root and db.read_bytes() == before_db


def test_apply_moves_rewrites_backs_up_and_still_serves(client, app, tmp_path: Path):
    a, b, f, art = setup_old_files(client, app)
    root = make_root(tmp_path)
    db = work_db(app)
    code, text = run("--work-db", str(db), "--root", str(root), "--apply")
    assert code == 0, text
    assert list(db.parent.glob("carnivore.db.pre-move-files-*"))
    pasted = root / "project-12" / f"watch-what-alex-changed-{a}" / "pastes" / f"{f['id']}-shot.txt"
    assert pasted.read_bytes() == b"hello" and not (plugin_folder(app) / "files" / str(a) / pasted.name).exists()
    page = root / "project-12" / f"watch-what-alex-changed-{a}" / "artifacts"
    assert [p.read_text() for p in page.glob("*-artifact.html")] == [PAGE]
    assert stored_parts(app, art["id"])["files"][0]["path"].startswith(str(page))
    with runtime.host_for(app).storage("huddle").connect(False) as conn:
        paths = [e["path"] for r in conn.execute("SELECT parts FROM work_messages WHERE parts LIKE '{\"files\"%'")
                 for e in json.loads(r["parts"])["files"]]
    assert paths and all(Path(p).is_absolute() and Path(p).exists() for p in paths)
    assert client.get(f"{BASE}/items/{a}/files/{f['id']}").content == b"hello"
    assert len(list((plugin_folder(app) / "files" / str(a)).glob("*-abandoned.txt"))) == 1
    again, text = run("--work-db", str(db), "--root", str(root))
    assert again == 0 and "total: 0 files" in text


def test_a_root_without_the_marker_is_refused(client, app, tmp_path: Path):
    setup_old_files(client, app)
    bare = tmp_path / "bare"
    bare.mkdir()
    code, text = run("--work-db", str(work_db(app)), "--root", str(bare), "--apply")
    assert code == 1 and "marker" in text and not any(bare.iterdir())
    code, _ = run("--work-db", str(work_db(app)), "--root", "relative/path")
    assert code == 1
    code, text = run("--work-db", str(tmp_path / "copy.db"), "--root", str(make_root(tmp_path)), "--plugin-folder",
                     str(plugin_folder(app)), "--apply")
    assert code == 1 and "dry run on a copy" in text


def test_a_stamped_folder_of_another_store_is_planned_around_and_never_written_into(client, app, tmp_path: Path):
    from src.cplugs.sdk import task_folders

    a, b, f, art = setup_old_files(client, app)
    root = make_root(tmp_path)
    theirs = task_folders.ensure_task(root, a, "12", "Carnivore", "Watch what Alex changed", store_id="0f0f0f0f0f0f0f0f")
    code, text = run("--work-db", str(work_db(app)), "--root", str(root), "--apply")
    assert code == 0, text
    own = theirs.with_name(f"{theirs.name}-00000000")
    assert (own / "pastes" / f"{f['id']}-shot.txt").exists() and not any((theirs / "pastes").glob("*-shot.txt"))
    assert task_folders.task_store_of(own) is None and task_folders.task_store_of(theirs) == "0f0f0f0f0f0f0f0f"


def test_the_moved_files_go_into_the_tasks_own_stamped_folder(client, app, tmp_path: Path):
    from contextlib import closing

    from src.cplugs.huddle import store_identity
    from src.cplugs.sdk import task_folders

    a, b, f, art = setup_old_files(client, app)
    root = make_root(tmp_path)
    with closing(runtime.host_for(app).storage("huddle").connect(True)) as conn, conn:
        mine = store_identity.ensure(conn)
    stamped = task_folders.ensure_task(root, a, "12", "Carnivore", "Watch what Alex changed", store_id=mine)
    code, text = run("--work-db", str(work_db(app)), "--root", str(root))
    assert code == 0 and f"item {a} -> {stamped.relative_to(root)}/" in text, text
    code, text = run("--work-db", str(work_db(app)), "--root", str(root), "--apply")
    assert code == 0, text
    assert (stamped / "pastes" / f"{f['id']}-shot.txt").exists() and len(task_folders.tasks_for(root, a)) == 1
