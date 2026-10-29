
import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from src.core.swarm import definition as D
from src.core.swarm import memory as M


def _def(rank="feature", memory="project", **kw):
    return D.AgentDefinition(slug="loki-swap", description='Model "swap" owner', rank=rank,
                             effort="high", memory=memory, brief="# Brief\n\nDo it.\n",
                             display_name="Loki (Swap)", **kw)


@pytest.mark.parametrize("rank,memory", [("alpha", "project"), ("project", "project"),
                                         ("feature", "project"), ("task", "local")])
def test_definition_round_trip(rank, memory):
    d = _def(rank, memory)
    p = D.parse_definition(D.render_definition(d))
    assert (p.name, p.description, p.model, p.effort, p.memory) == (
        "loki-swap", d.description, "opus", "high", memory)
    assert p.brief == "# Brief\n\nDo it."
    assert p.tools == (D.UPPER_TOOLS if rank in D.UPPER_RANKS else None)
    twin = D.parse_codex_twin(D.render_codex_twin(d))
    assert twin["name"] == "loki-swap" and "MEMORY.md" in twin["developer_instructions"]


def test_swarm_json_and_settings_round_trip(tmp_path):
    meta = D.SwarmMeta("loki-swap", "Loki (Swap)", "feature", "odin", "calm", "norse", "s1")
    assert D.parse_swarm_json(D.render_swarm_json(meta)) == meta
    s = D.render_settings(tmp_path / "mem")
    assert json.loads(s)["permissions"] == {"allow": ["mcp__carnivore"], "deny": list(D.FILE_WRITE_TOOLS)}


def test_task_agent_exclude_lines(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    D.add_exclude_lines(tmp_path, "loki-swap")
    D.add_exclude_lines(tmp_path, "loki-swap")
    text = (tmp_path / ".git" / "info" / "exclude").read_text()
    for line in D.exclude_lines("loki-swap"):
        assert text.count(line) == 1
    D.remove_exclude_lines(tmp_path, "loki-swap")
    assert "loki-swap" not in (tmp_path / ".git" / "info" / "exclude").read_text()
    with pytest.raises(M.SwarmFileError):
        D.render_definition(_def("task", "project"))


def test_fact_round_trip_index_and_secret_refusal(tmp_path):
    mem = M.memory_dir(tmp_path, "loki-swap", "local")
    assert mem.parts[-2] == "agent-memory-local"
    M.ensure_layout(mem)
    owner = M.Fact("f_000000000001", "owner rule", "craft", "owner", "2026-10-01", "b1", "m:1")
    agent = M.Fact("f_000000000002", "agent note", "project", "agent", "2026-10-05", "b2")
    for f in (owner, agent):
        M.write_fact(mem, f)
        assert M.parse_fact((mem / "facts" / f"{f.id}.md").read_text()) == f
    (mem / "MEMORY.md").write_text("my own line\n")
    M.write_index(mem, [M.IndexEntry(f.id, f.title, f.scope, f.origin, f.taught_at)
                        for f in (agent, owner)])
    text = (mem / "MEMORY.md").read_text()
    assert text.startswith(M.INDEX_START) and text.endswith("my own line\n")
    assert text.index("owner rule") < text.index("agent note")

    secret = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bD1fH3jL5"
    bad = M.Fact("f_000000000003", "t", "craft", "agent", "2026-10-05", f"token {secret}")
    with pytest.raises(M.SecretRefused) as ei:
        M.write_fact(mem, bad)
    assert secret not in str(ei.value) and "facts/f_000000000003.md body" in str(ei.value)
    assert not (mem / "facts" / "f_000000000003.md").exists()
    with pytest.raises(M.SecretRefused):
        D.render_definition(dataclasses.replace(_def(), brief=secret))


def test_index_overflow():
    entries = [M.IndexEntry(f"f_{i:012x}", f"t{i}", "craft", "agent", f"2026-10-{i % 28 + 1:02d}")
               for i in range(160)]
    block, more = M.render_index_block(entries)
    assert block.count("\n- [") == 151 and more is not None and more.count("- [") == 10
