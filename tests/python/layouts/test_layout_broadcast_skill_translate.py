from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.core.layouts.skill_translate import translate
from tests.test_layout_broadcast import API, FakeBackend, _layout, env  # noqa: F401


def _skill(root, rel: str, name: str) -> None:
    d = root / rel / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n")


def _info(row_id: int, sid: str, family, wd) -> Any:
    return SimpleNamespace(session_row_id=row_id, session=SimpleNamespace(id=sid, working_dir=str(wd)),
                           activity_status="idle", startup_gate="ready", agent_family=family,
                           tmux_session=None)


def test_translate_unit_rules():
    names = frozenset({"zzprog"})
    assert translate("/zzprog a $b", "codex", names) == "$zzprog a $b"
    assert translate("$zzprog", "claude", names) == "/zzprog"
    assert translate("/zzprog", "claude", names) == "/zzprog"
    assert translate("/clear", "codex", names) == "/clear"
    assert translate("/zzprog", None, names) == "/zzprog"
    assert translate("run /zzprog", "codex", names) == "run /zzprog"
    assert translate("$zzprogx", "claude", names) == "$zzprogx"


def test_broadcast_translates_per_family(env, tmp_path):
    client, _, _, sessions, live = env
    rows = [r for r, _ in sessions[:4]]
    layout = _layout(client, *rows)
    wd = []
    for i in range(4):
        d = tmp_path / f"w{i}"
        d.mkdir()
        _skill(d, ".claude/skills", "zzprog")
        _skill(d, ".agents/skills", "zzprog")
        wd.append(d)
    fams = ["claude", "codex", None, "mystery"]
    ids = ["s0", "s1", "s2", "s3"]
    live["backends"] = {i: FakeBackend() for i in ids}
    live["infos"] = [_info(r, i, f, d) for r, i, f, d in zip(rows, ids, fams, wd)]
    uuid = layout["layout_uuid"]
    for text in ("/zzprog now", "$zzprog now", "/clear", "plain /zzprog"):
        for b in live["backends"].values():
            b.sent.clear()
        res = client.post(f"{API}/{uuid}/broadcast", json={"text": text})
        assert res.status_code == 200, res.text
        sent = [live["backends"][i].sent[0] for i in ids]
        if text.endswith("now"):
            assert sent == ["/zzprog now", "$zzprog now", text, text], (text, sent)
        else:
            assert sent == [text] * 4
