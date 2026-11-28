from __future__ import annotations

import asyncio
import re
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from src.core.computers.runtime import LazyPack
from src.core.pack.machines import capabilities as caps, operating, settings_doc
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.meshdata import gossip, status, wire
from test_mesh_settings import Net, machines, net  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


def _counts(store: Any) -> Tuple[int, int]:
    with closing(store._connect()) as conn:  # noqa: SLF001
        return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0], conn.execute("SELECT COUNT(*) FROM floors").fetchone()[0]


def _fill(n: Net, name: str) -> Tuple[str, Tuple[int, int]]:
    n.write(name, auto_distribute=True)
    store = n.stores[name]
    store.put_own("status", n.iid[name], status.build(name, "1", [], 1), n.signing[name])
    store.drop("status", n.iid[name])
    return store.store_id(), _counts(store)


def _joined(tmp_path: Path, n: Net, held: List[Any]) -> Tuple[Any, LazyPack, Any]:
    rt = machines(tmp_path, n, "b")
    rt.custody.held_lists = lambda: held[0]  # type: ignore[method-assign]
    return rt, LazyPack(lambda: SimpleNamespace(runtime=rt)), settings_doc.default_doc(n.iid["a"])


def test_only_a_leave_or_a_join_of_another_pack_wipes(net, tmp_path):  # noqa: F811
    n = net("a", "b", "c")
    held: List[Any] = [(n.lst(), None)]
    rt, pack, doc_a = _joined(tmp_path, n, held)
    store_id, counts = _fill(n, "b")
    assert counts[0] >= 1 and counts[1] >= 1
    pack.adopt(doc_a)
    assert (n.stores["b"].store_id(), _counts(n.stores["b"])) == (store_id, counts) and operating.CURRENT
    held[0] = None
    pack.adopt(doc_a)
    assert (n.stores["b"].store_id(), _counts(n.stores["b"])) == (store_id, counts)
    pack.adopt(settings_doc.default_doc(n.iid["c"]))
    assert _counts(n.stores["b"]) == (0, 0) and n.stores["b"].store_id() != store_id and operating.CURRENT == {}
    held[0] = (n.lst(), None)
    _fill(n, "b")
    rt.custody.adopt(doc_a)
    pack.clear_roster()
    assert _counts(n.stores["b"]) == (0, 0)


def test_a_successor_that_left_and_leads_a_new_pack_wipes(net, tmp_path):  # noqa: F811
    n = net("a", "b", "x")
    lst = n.lst()
    successor_list = RosterV2(**{**lst.model_dump(), "alpha": n.iid["b"], "home": n.iid["a"]})
    rt, pack, _doc = _joined(tmp_path, n, [(successor_list, None)])
    rt.custody.adopt(settings_doc.default_doc(n.iid["b"]))
    store_id, counts = _fill(n, "x")
    n.use("b")
    n.stores["b"].put_own("status", n.iid["b"], status.build("b", "1", [], 1), n.signing["b"])
    assert counts[0] >= 1
    pack.adopt(settings_doc.default_doc(n.iid["b"]))
    assert _counts(n.stores["b"]) == (0, 0)


def test_the_switch_off_never_wipes_and_never_reads_the_held_list(net, tmp_path, monkeypatch):  # noqa: F811
    n = net("a", "b", "c")
    rt, pack, doc_a = _joined(tmp_path, n, [None])
    store_id, counts = _fill(n, "b")

    def boom() -> None:
        raise AssertionError("held_lists read with the switch off")

    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    rt.custody.held_lists = boom  # type: ignore[method-assign]
    pack.adopt(settings_doc.default_doc(n.iid["c"]))
    pack.clear_roster()
    assert (n.stores["b"].store_id(), _counts(n.stores["b"])) == (store_id, counts)


def test_only_a_leave_and_a_join_call_the_wipe_so_takeover_hand_over_and_reissue_never_do():
    callers: Dict[str, List[str]] = {}
    for path in (ROOT / "src").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text.startswith(("def ", "#", '"""')):
                for token in re.findall(r"[\w.]*\b(?:clear_roster|_forget_mesh_data)\(", text):
                    callers.setdefault(path.relative_to(ROOT).as_posix(), []).append(token.lstrip(".")[:-1])
    assert set(callers) == {"src/core/computers/forget.py", "src/core/computers/runtime.py", "src/core/pack/machines/settings_custody.py"}, callers
    assert callers["src/core/computers/forget.py"] == ["pack.clear_roster"]
    assert callers["src/core/computers/runtime.py"] == ["runtime.custody.clear_roster"]
    assert sorted(callers["src/core/pack/machines/settings_custody.py"]) == ["self._forget_mesh_data", "self.clear_roster", "self.state.clear_roster"]


def test_a_pass_that_read_its_list_before_a_clear_writes_nothing_after_it(net):  # noqa: F811
    n = net("a", "b")
    store, lst, old = n.stores["b"], n.lst(), n.forged("a", "auto_distribute", True)
    calls: List[int] = []

    class Client:

        async def request(self, method: str, path: str, json: Any = None, **_kw: Any) -> Any:
            return SimpleNamespace(status_code=200, json=lambda: {"status": "ok", "records": old})

    def held_list() -> RosterV2:
        if not calls:
            store.clear()
        calls.append(1)
        return lst

    async def step(service: Any, current: Any) -> None:
        service.store.put_many("ops", [("auto_distribute", True, None)], service.signing, current, gen=service.pass_gen)

    def service(clears: bool) -> gossip.Gossip:
        calls.clear()
        if not clears:
            calls.append(1)
        return gossip.Gossip(store, links_getter=lambda: None, signing=n.signing["b"], held_list=held_list, label=lambda: "b", app_version="1.0", own_iid=n.iid["b"],
                             members=lambda _l: [(n.iid["a"], Client())])

    gossip.STEPS[:] = [step]
    asyncio.run(service(True).pass_once())
    assert _counts(store) == (0, 0)
    asyncio.run(service(False).pass_once())
    with closing(store._connect()) as conn:  # noqa: SLF001
        kinds = {r[0] for r in conn.execute("SELECT kind FROM records").fetchall()}
    assert {status.KIND, "ops"} <= kinds


def test_the_operating_write_and_a_sync_request_that_read_their_list_before_a_clear_write_nothing(net):  # noqa: F811
    n = net("a", "b")
    n.use("b")
    store = n.stores["b"]
    n.active.held_list = lambda: (store.clear(), n.lst())[1]
    assert operating.write_own({"auto_distribute": True}) == 0 and _counts(store) == (0, 0)
    n.active.held_list = n.lst
    assert operating.write_own({"auto_distribute": True}) == 1
    body = {"v": wire.WIRE_VERSION, "digest": "x", "buckets": 1, "bucket": 0, "records": n.forged("a", "auto_distribute", True)}
    stale = store.generation
    store.clear()
    assert wire.handle_sync(store, body, n.iid["a"], n.lst(), n.now, gen=stale)[1] == 0
    assert _counts(store) == (0, 0)
    assert wire.handle_sync(store, body, n.iid["a"], n.lst(), n.now, gen=store.generation)[1] == 1
