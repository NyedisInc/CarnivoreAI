
from __future__ import annotations

import os
import time

from src.cplugs.save.vault import follow, restore, units
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


def _age(path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_a_short_conversation_rewritten_to_something_longer_keeps_its_older_point(tmp_path):
    world = World(tmp_path)
    old = jsonl(20, seed=1)
    world.write_conversation(old)
    world.capture()
    good = world.vault.manifests.point_ids(CONV)[0]
    world.transcript().write_bytes(jsonl(60, seed=2))
    _age(world.transcript(), -10)
    assert world.capture().status == "written"
    assert world.vault.manifests.is_kept(CONV, good)
    assert b"".join(restore.read_entry(world.vault.blobs, world.vault.manifests.read(CONV, good).main())) == old


def test_a_plain_append_to_a_short_conversation_is_still_not_a_rewrite(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20, seed=1))
    world.capture()
    first = world.vault.manifests.point_ids(CONV)[0]
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(5, seed=3))
    _age(world.transcript(), -10)
    assert world.capture().status == "written" and not world.vault.manifests.is_kept(CONV, first)


def test_a_last_line_without_a_newline_is_captured_once_the_file_has_been_quiet(tmp_path):
    world = World(tmp_path)
    body = jsonl(20) + b'{"type":"user","text":"the session died mid-li'
    main = world.write_conversation(body, subagents=0, tool_results=0)
    assert world.capture().status == "written"
    point = world.vault.manifests.newest(CONV)
    assert point.main().torn_bytes > 0 and point.main().length < len(body)
    assert follow.needs_capture(units.plan_claude(world.sources, CONV), point) is False
    _age(main, 3600)
    assert follow.needs_capture(units.plan_claude(world.sources, CONV), point) is True
    assert world.capture().status == "written"
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == body
    assert follow.needs_capture(units.plan_claude(world.sources, CONV), newest) is False
    assert world.capture().status == "unchanged"
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, newest, out)
    assert (out / "claude" / newest.main().rel).read_bytes() == body
    assert restore.file_matches(main, newest.main())
