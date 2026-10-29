
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

import pytest

from src.config.mcp import McpConfig
from src.core.mcp import agent_tool_switches, instructions, tools
from src.core.mcp.caller import AgentCaller

pytestmark = pytest.mark.real_agent_tool_switches

JOBS = json.loads((Path(__file__).resolve().parents[3] / "scripts" / "mcp" / "discovery_jobs.json").read_text())["jobs"]
TOP = 5
NAME_WEIGHT = 3
K1, B = 1.2, 0.75
STOP = frozenset({"a", "an", "the", "of", "to", "on", "in", "for", "and", "or", "my", "me", "this", "that", "is", "it", "from", "with", "by", "as", "at", "be"})
PANE = AgentCaller("ses_a", "carnivore_a", "ses_a")
EXTERNAL_WRITE = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="laptop", scope="write")


def words(text: str) -> List[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w not in STOP:
            out.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def corpus(caller: AgentCaller) -> Dict[str, List[str]]:
    guide = instructions.guide(caller)
    lines = [ln for ln in guide.splitlines() if ln.strip()]
    docs: Dict[str, List[str]] = {}
    for d in tools.tool_definitions(caller):
        name = d["name"]
        mentioned = [ln for ln in lines if re.search(rf"(?<![a-z_]){re.escape(name)}(?![a-z_])", ln)]
        docs[name] = words(name.replace("_", " ")) * NAME_WEIGHT + words(d["description"]) + [w for ln in mentioned for w in words(ln)]
    return docs


def rank(docs: Dict[str, List[str]], query: str) -> List[str]:
    n = len(docs)
    avg = sum(len(w) for w in docs.values()) / n
    df = Counter(t for w in docs.values() for t in set(w))
    scored: List[Tuple[float, str]] = []
    for name, ws in docs.items():
        tf = Counter(ws)
        score = 0.0
        for t in set(words(query)):
            if tf[t]:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * (K1 + 1) / (tf[t] + K1 * (1 - B + B * len(ws) / avg))
        scored.append((-score, name))
    return [name for _, name in sorted(scored)]


@pytest.fixture(autouse=True)
def default_switches(monkeypatch):
    monkeypatch.setattr(agent_tool_switches, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=McpConfig())))


def _misses(caller: AgentCaller, only_external: bool = False) -> Dict[str, str]:
    docs = corpus(caller)
    missed = {}
    for job in JOBS:
        if only_external and not job["external"]:
            continue
        if job["expect"] not in docs:
            missed[job["id"]] = f"{job['expect']} is not in this caller's tool list"
            continue
        order = rank(docs, job["query"])
        if job["expect"] not in order[:TOP]:
            missed[job["id"]] = f"{job['expect']} ranked {order.index(job['expect']) + 1}, top {TOP} was {order[:TOP]}"
    return missed


def test_the_default_pane_finds_the_tool_for_every_job():
    assert len(JOBS) >= 15 and not any(t.startswith("huddle_") for t in corpus(PANE))
    assert _misses(PANE) == {}


def test_an_external_write_token_finds_the_tool_for_every_job_that_applies():
    assert _misses(EXTERNAL_WRITE, only_external=True) == {}


def test_the_ranking_can_fail_when_the_tool_is_renamed_and_its_description_blanked():
    docs = corpus(PANE)
    for job in JOBS:
        broken = {n: w for n, w in docs.items() if n != job["expect"]}
        broken["zz_unrelated"] = words("zz unrelated") * NAME_WEIGHT
        assert job["expect"] in rank(docs, job["query"])[:TOP], job["id"]
        assert job["expect"] not in rank(broken, job["query"])[:TOP], job["id"]
        assert "zz_unrelated" not in rank(broken, job["query"])[:1], job["id"]


def test_blanking_only_the_description_lowers_at_least_one_jobs_rank():
    docs = corpus(PANE)
    dropped = 0
    for job in JOBS:
        name = job["expect"]
        stripped = dict(docs)
        stripped[name] = words(name.replace("_", " ")) * NAME_WEIGHT
        before, after = rank(docs, job["query"]).index(name), rank(stripped, job["query"]).index(name)
        dropped += after > before
    assert dropped >= 1
