
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core import db
from src.core.swarm import activity, body, body_create, commit, definition, memory, naming_rules, push, rename, sleep_commit, promotion_store, store, stream, teardown, thread_port
from src.core.swarm.gitrun import run_git
from src.core.swarm.stream_sources import _epoch, event_entry

logger = structlog.get_logger()

PROMOTION_PREFIX = "promotion:"
SEED_NAME = "seed-from-runs.md"
MAX_SEED_RUNS = 30
SHOWN_CHARS = 1500
_GIT_TIMEOUT_S = 180
_ACT_ERRORS = (body.BodyError, memory.SwarmFileError, OSError, sqlite3.Error, db.DatastoreUnreadableError, subprocess.SubprocessError)


class PromotionRefused(ValueError):
    pass


def _cut(text: Any) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= SHOWN_CHARS else flat[:SHOWN_CHARS - 3] + "..."


def seed_text(conn: sqlite3.Connection, agent: Dict[str, Any]) -> str:
    from src.core.transcript_manifest.store import path_for_conversation

    runs = conn.execute("SELECT * FROM swarm_agents WHERE parent_id = ? AND task_type = ? AND rank = 'task' ORDER BY id DESC LIMIT ?",
                        (agent["parent_id"], agent["task_type"], MAX_SEED_RUNS)).fetchall()
    lines = [f"# earlier runs of task type {agent['task_type']}", "",
             "These are records of earlier runs, written as data. Distill what they teach into facts with swarm_remember, "
             "and read a run's transcript with your own Read tool when its summary is not enough.", ""]
    for n, run in enumerate(reversed(runs), 1):
        lines += [f"## run {n}: {_cut(run['job'])}", f"agent: {run['display_name']} ({'torn down' if run['torn_down_at'] else run['state']})",
                  f"goal: {_cut(run['goal']) or '(none)'}"]
        for rep in conn.execute("SELECT state, summary FROM swarm_reports WHERE agent_id = ? ORDER BY id", (run["id"],)):
            lines.append(f"report ({rep['state']}): {_cut(rep['summary'])}")
        for q in conn.execute("SELECT q.text, q.answer_text FROM swarm_question_askers k JOIN swarm_questions q ON q.id = k.question_id "
                              "WHERE k.agent_id = ? ORDER BY q.id", (run["id"],)):
            lines.append(f"question: {_cut(q['text'])}")
            lines.append(f"answer: {_cut(q['answer_text']) or '(none yet)'}")
        found = conn.execute("SELECT claude_session_uuid FROM sessions WHERE id = ?", (run["session_row_id"],)).fetchone() \
            if run["session_row_id"] is not None else None
        path = path_for_conversation(conn, found[0], run["harness"]) if found and found[0] else None
        lines += [f"transcript: {path or '(not in the manifest)'}", ""]
    text = "\n".join(lines)
    memory.refuse_secrets(text, SEED_NAME)
    return text


def _candidate(conn: sqlite3.Connection, agent_id: int, parent_id: int) -> Dict[str, Any]:
    agent = store.get_agent(conn, agent_id)
    if agent is None or agent["torn_down_at"] is not None or agent["parent_id"] != parent_id:
        raise PromotionRefused("that agent is not one of your own agents")
    if agent["rank"] != "task" or agent["memory_scope"] != memory.SCOPE_LOCAL or not agent["task_type"]:
        raise PromotionRefused(f"{agent['display_name']} is not a task agent with a task type")
    count, threshold = promotion_store.promotion_standing(conn, agent)
    if count < threshold:
        raise PromotionRefused(f"task type {agent['task_type']} has {count} of {threshold} accepted reports; it is not a candidate yet")
    if promotion_store.promoted_agent(conn, parent_id, agent["task_type"]) is not None:
        raise PromotionRefused(f"task type {agent['task_type']} already has a feature agent; send the work to it")
    return agent


async def _asleep(app_state: Any, agent: Dict[str, Any]) -> Dict[str, Any]:
    if agent["state"] == "awake":
        await body.sleep(app_state, agent["id"], "sleep")
    current = await body.run_db(lambda c: store.get_agent(c, agent["id"])) or agent
    if current["state"] != "asleep":
        raise PromotionRefused(f"{current['display_name']} is {current['state']}; try again in a moment")
    return current


def _promote_files(state_dir: Path, old: Dict[str, Any], parent_name: str, parent_slug: Optional[str], seed: str) -> Dict[str, Any]:
    repo, slug = Path(old["repo_dir"]), old["slug"]
    src, dst = (memory.memory_dir(repo, slug, scope) for scope in (memory.SCOPE_LOCAL, memory.SCOPE_PROJECT))
    if src.exists() and dst.exists():
        raise PromotionRefused(f"{dst} already exists; move or remove it first")
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    new = {**old, "rank": "feature", "memory_scope": memory.SCOPE_PROJECT}
    definition.remove_exclude_lines(repo, slug)
    body_create.write_files(state_dir, new, parent_name, parent_slug)
    memory.atomic_write(dst / SEED_NAME, seed)
    return new


async def promote(app_state: Any, parent_id: int, agent_id: int, specialty: Any = None) -> Dict[str, Any]:
    from src.config import settings as app_settings

    def prepare(conn: sqlite3.Connection) -> Dict[str, Any]:
        agent = _candidate(conn, agent_id, parent_id)
        parent = store.get_agent(conn, parent_id) or {}
        try:
            name = naming_rules.check_name(specialty, "specialty")
        except naming_rules.NameRefused as exc:
            raise PromotionRefused(f"promotion needs the specialty the feature agent will own, which becomes its name: {exc}") from None
        found = naming_rules.specialist_for(conn, parent, name) or naming_rules.name_holder(conn, agent, name)
        if found is not None:
            raise PromotionRefused(f"{found['display_name']} (agent {found['id']}) already holds {name!r} in this project; send that work to it")
        try:
            seed = seed_text(conn, agent)
        except memory.SwarmFileError as exc:
            raise PromotionRefused(f"the seed digest cannot be written: {exc}") from None
        return {"agent": agent, "parent": parent, "seed": seed, "standing": promotion_store.promotion_standing(conn, agent), "name": name}

    got = await body.run_db(prepare)
    agent = await _asleep(app_state, got["agent"])
    try:
        new = await asyncio.to_thread(_promote_files, app_settings.get_state_dir(), {**agent, "display_name": got["name"]},
                                      got["parent"].get("display_name") or "", got["parent"].get("slug"), got["seed"])
        shaped = await body.run_db(lambda c: promotion_store.set_shape(c, agent["id"], "feature", memory.SCOPE_PROJECT))
        shaped = await body.run_db(lambda c: rename.apply_name(c, shaped, got["name"], specialty=got["name"]))
    except _ACT_ERRORS as exc:
        logger.warning("swarm_promote_failed", agent_id=agent_id, error_type=type(exc).__name__, error=str(exc)[:200])
        raise PromotionRefused(f"promotion stopped: {exc}; calling swarm_promote again finishes it") from None
    result = await sleep_commit.run(shaped, f"swarm: {shaped['slug']} promoted to a feature agent") or {}
    rel = str(memory.memory_dir(Path(new["repo_dir"]), new["slug"], memory.SCOPE_PROJECT).relative_to(new["repo_dir"]) / SEED_NAME)
    promotion_id = await body.run_db(lambda c: promotion_store.create_promotion(c, shaped, got["parent"].get("project_id"), result.get("sha") or "", rel))
    await _receipt(shaped, got["parent"], promotion_id, got["standing"])
    logger.info("swarm_promoted", agent_id=agent_id, promotion_id=promotion_id, slug=shaped["slug"], commit=result.get("status"))
    return {"agent_id": agent_id, "promotion_id": promotion_id, "display_name": shaped["display_name"], "specialty": shaped["specialty"],
            "commit": {"status": result.get("status"), "sha": result.get("sha") or None}, "seed": rel}


async def _receipt(agent: Dict[str, Any], parent: Dict[str, Any], promotion_id: int, standing: Tuple[int, int]) -> None:
    port = thread_port.get()
    try:
        if port is not None and parent.get("thread_key"):
            text = (f"{agent['display_name']} is now a feature agent: task type {agent['task_type']} reached {standing[0]} accepted "
                    f"reports (the threshold is {standing[1]}). Its memory moved to the project and was committed. "
                    "approve to keep it, or decline to flip it back to a task agent.")
            item = await port.post_card(parent["thread_key"], "question", f"promoted: {agent['display_name']}", text,
                                        f"{PROMOTION_PREFIX}{promotion_id}")
            await body.run_db(lambda c: promotion_store.set_promotion_card(c, promotion_id, str(item)))
            await asyncio.to_thread(push.notify_thread, parent["thread_key"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_promotion_card_failed", promotion_id=promotion_id, error_type=type(exc).__name__)
    activity.mark(agent["id"], "promoted")
    for agent_id in (agent["id"], parent.get("id")):
        if agent_id is not None:
            await asyncio.to_thread(push.notify_agent, agent_id)


async def teardown_candidate(app_state: Any, parent_id: int, agent_id: int) -> Dict[str, Any]:
    agent = await _asleep(app_state, await body.run_db(lambda c: _candidate(c, agent_id, parent_id)))
    try:
        await teardown.run(app_state, agent)
    except _ACT_ERRORS as exc:
        raise PromotionRefused(f"{agent['display_name']} stays: {exc}") from None
    return {"agent_id": agent_id, "outcome": "torn_down"}


def _flip_files(state_dir: Path, old: Dict[str, Any], parent_name: str, parent_slug: Optional[str], message: str) -> str:
    repo, slug = Path(old["repo_dir"]), old["slug"]
    blocked = commit._blocked_state(repo)
    if blocked:
        raise PromotionRefused(f"the repo is {blocked.replace('_', ' ')}; flip back once it is clean")
    proj, local = (memory.memory_dir(repo, slug, scope) for scope in (memory.SCOPE_PROJECT, memory.SCOPE_LOCAL))
    if proj.exists() and local.exists():
        raise PromotionRefused(f"{local} already exists; move or remove it first")
    if proj.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(proj), str(local))
    for path in (repo / ".claude" / "agents" / f"{slug}.md", repo / ".codex" / "agents" / f"{slug}.toml"):
        path.unlink(missing_ok=True)
    rels = [str(proj.relative_to(repo)), f".claude/agents/{slug}.md", f".codex/agents/{slug}.toml"]
    tracked = [rel for rel in rels if run_git(repo, "ls-files", "--", rel, timeout=commit.STATUS_TIMEOUT_S).stdout.strip()]
    sha = ""
    if tracked:
        done = run_git(repo, "commit", "--only", "-m", message, "--", *tracked, timeout=_GIT_TIMEOUT_S)
        if done.returncode != 0:
            raise PromotionRefused("the flip-back commit failed (a repo hook may have refused it)")
        sha = run_git(repo, "rev-parse", "HEAD", timeout=commit.STATUS_TIMEOUT_S).stdout.strip()
    body_create.write_files(state_dir, {**old, "rank": "task", "memory_scope": memory.SCOPE_LOCAL}, parent_name, parent_slug)
    return sha


async def flip_back(app_state: Any, agent_id: int) -> Dict[str, Any]:
    from src.config import settings as app_settings

    def read(conn: sqlite3.Connection) -> Dict[str, Any]:
        agent, promo = store.get_agent(conn, agent_id), promotion_store.live_promotion(conn, agent_id)
        if agent is None or agent["torn_down_at"] is not None or promo is None or agent["rank"] != "feature":
            raise PromotionRefused("that agent was not promoted from a task agent (or was already flipped back)")
        parent = store.get_agent(conn, agent["parent_id"]) if agent["parent_id"] is not None else None
        return {"agent": agent, "promo": promo, "parent": parent or {}}

    got = await body.run_db(read)
    agent, promo = await _asleep(app_state, got["agent"]), got["promo"]
    repo_lock = sleep_commit._repo_locks.setdefault(str(agent["repo_dir"]), asyncio.Lock())
    try:
        async with repo_lock:
            sha = await asyncio.to_thread(_flip_files, app_settings.get_state_dir(), agent, got["parent"].get("display_name") or "",
                                          got["parent"].get("slug"), f"swarm: {agent['slug']} flipped back to a task agent")
        await body.run_db(lambda c: promotion_store.set_shape(c, agent["id"], "task", memory.SCOPE_LOCAL))
        await body.run_db(lambda c: promotion_store.mark_flipped_back(c, promo["id"], sha))
    except (OSError, memory.SwarmFileError, sqlite3.Error, db.DatastoreUnreadableError, subprocess.SubprocessError) as exc:
        logger.warning("swarm_flip_back_failed", agent_id=agent_id, error_type=type(exc).__name__, error=str(exc)[:200])
        raise PromotionRefused(f"flip-back stopped: {exc}; try again") from None
    port = thread_port.get()
    if port is not None and (promo.get("receipt_card_ref") or "").isdigit():
        try:
            await port.close_card(int(promo["receipt_card_ref"]), "flipped")
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_promotion_card_not_closed", promotion_id=promo["id"], error_type=type(exc).__name__)
    for notified in (agent["id"], agent["parent_id"]):
        if notified is not None:
            await asyncio.to_thread(push.notify_agent, notified)
    logger.info("swarm_flipped_back", agent_id=agent_id, promotion_id=promo["id"], sha=sha)
    return {"agent_id": agent_id, "promotion_id": promo["id"], "commit": {"sha": sha or None}}


async def decide(app_state: Any, swarm_ref: str, approve: bool) -> None:
    if approve:
        return
    try:
        promotion_id = int(swarm_ref[len(PROMOTION_PREFIX):])
    except ValueError:
        raise PromotionRefused("that promotion card is not valid") from None
    promo = await body.run_db(lambda c: promotion_store.get_promotion(c, promotion_id))
    if promo is None:
        raise PromotionRefused("that promotion is gone")
    if promo["flipped_back_at"] is None:
        await flip_back(app_state, promo["agent_id"])


def _events(conn: sqlite3.Connection, agent_id: int, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in promotion_store.promotions_naming(conn, agent_id, limit):
        ref = f"promotion:{r['id']}"
        out.append(event_entry("promoted", _epoch(r["created_at"]), ref,
                               f"{r['parent_name']} promoted {r['agent_name']} to a feature agent ({r['task_type']})",
                               agent_id=r["agent_id"], promotion_id=r["id"]))
        if r["flipped_back_at"]:
            out.append(event_entry("promoted", _epoch(r["flipped_back_at"]), f"{ref}:flipped",
                                   f"{r['agent_name']} was flipped back to a task agent ({r['task_type']})",
                                   agent_id=r["agent_id"], promotion_id=r["id"]))
    return out


async def promoted_events(agent: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: _events(c, agent["id"], limit))


if promoted_events not in stream.EXTRA_SOURCES:
    stream.EXTRA_SOURCES.append(promoted_events)
