
from __future__ import annotations

import os
import time

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import retention
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


def _grow(world: World, lines: int, seed: int, bump: int) -> None:
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(lines, seed=seed))
    os.utime(world.transcript(), (time.time() + bump, time.time() + bump))


def test_several_captures_of_a_conversation_leave_one_point(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(60))
    reasons = ["follow", "kill", "sleep", "follow", "restart"]
    for i, reason in enumerate(reasons):
        _grow(world, 3, i, i)
        assert world.capture(reason=reason).status == "written"
    assert len(world.vault.manifests.point_ids(CONV)) == 1
    assert world.capture(reason="follow").status == "unchanged"
    assert len(world.vault.manifests.point_ids(CONV)) == 1


def test_a_shortened_conversation_keeps_its_older_point_and_a_pin_stays(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(60))
    world.capture()
    old = world.vault.manifests.point_ids(CONV)[-1]
    main.write_bytes(jsonl(10, seed=9))
    os.utime(main, (time.time() + 5, time.time() + 5))
    assert world.capture().status == "written"
    store = world.vault.manifests
    assert store.point_ids(CONV)[0] == old and store.is_kept(CONV, old) and len(store.point_ids(CONV)) == 2
    _grow(world, 3, 1, 10)
    assert world.capture().status == "written"
    assert len(store.point_ids(CONV)) == 2 and old in store.point_ids(CONV)
    newest = store.point_ids(CONV)[-1]
    store.set_pinned(CONV, newest, True)
    _grow(world, 3, 2, 20)
    assert world.capture().status == "written"
    assert newest in store.point_ids(CONV) and len(store.point_ids(CONV)) == 3


def test_the_first_pass_trims_an_old_vault_to_the_newest_plus_protected(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(60))
    world.grow_history(12)
    store = world.vault.manifests
    ids = store.point_ids(CONV)
    store.set_pinned(CONV, ids[3], True)
    store.set_kept(CONV, ids[5])
    retention.assess(world.vault, cap_bytes=1 << 40)
    assert store.point_ids(CONV) == [ids[3], ids[5], ids[-1]]
    again = retention.assess(world.vault, cap_bytes=1 << 40)
    assert store.point_ids(CONV) == [ids[3], ids[5], ids[-1]] and again["points"] == 3


def test_a_plugin_folder_unit_still_keeps_its_history_up_to_ten(tmp_path):
    world = World(tmp_path)
    boards = tmp_path / "boards"
    boards.mkdir()
    for i in range(K.MAX_POINTS_PER_UNIT + 3):
        (boards / "board.json").write_text('{"round": %d}' % i)
        assert world.vault.capture_folder("reviewboard.boards", boards).status == "written"
    assert len(world.vault.manifests.point_ids("reviewboard.boards")) == K.MAX_POINTS_PER_UNIT + 3
    retention.assess(world.vault, cap_bytes=1 << 40)
    assert len(world.vault.manifests.point_ids("reviewboard.boards")) == K.MAX_POINTS_PER_UNIT
