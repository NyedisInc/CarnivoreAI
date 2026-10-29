
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.config import settings
from src.core import db
from src.core.crosstalk import peer_create
from src.core.pack.span import memory_mirror
from src.core.pack.trust_carry import store as trust_store
from src.core.swarm import body, body_create, definition, launch, memory

logger = structlog.get_logger()

REMOTE_RANKS = ("feature", "task")


class BodyRefused(RuntimeError):

    def __init__(self, code: str, status: int = 409, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code, self.status, self.detail = code, status, detail or code


class MemoryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(min_length=64, max_length=64)
    text: str = Field(max_length=memory_mirror.MAX_FILE_BYTES)


class BodyPacket(BaseModel):
    """What the home sends to start or restart a remote body. Text only; at most 512 KiB."""

    model_config = ConfigDict(extra="forbid")
    home_agent_id: int = Field(ge=1)
    project_uid: str = Field(min_length=8, max_length=64)
    rank: str = Field(pattern="^(feature|task)$")
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    display_name: str = Field(min_length=1, max_length=200)
    job: str = Field(min_length=1, max_length=2000)
    goal: Optional[str] = Field(default=None, max_length=20000)
    persona: Optional[str] = Field(default=None, max_length=500)
    effort: str = Field(min_length=1, max_length=16)
    effort_reason: Optional[str] = Field(default=None, max_length=1000)
    harness: str = Field(pattern="^(claude|codex)$")
    model: Optional[str] = Field(default=None, max_length=128)
    launch_profile: Optional[str] = Field(default=None, max_length=128)
    naming_family: Optional[str] = Field(default=None, max_length=200)
    character_seed: str = Field(default="0", max_length=64)
    parent_name: Optional[str] = Field(default=None, max_length=200)
    parent_slug: Optional[str] = Field(default=None, max_length=100)
    definition_rev: int = Field(default=0, ge=0)
    account_key: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")
    memory_files: List[MemoryFile] = Field(default_factory=list, max_length=memory_mirror.MAX_FILES)
    worktree_branch: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$")
    adopt_session_uuid: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,64}$")


def remote_state(state_dir: Path, home_install_id: str) -> Path:
    return launch.swarm_dir(state_dir) / "remote" / hashlib.sha256(home_install_id.encode("utf-8")).hexdigest()[:12]


def mirror_dir(state_dir: Path, home_install_id: str, home_agent_id: int) -> Path:
    return remote_state(state_dir, home_install_id) / "mirror" / str(int(home_agent_id))


def _agent(packet: BodyPacket, repo: str) -> Dict[str, Any]:
    return {"id": packet.home_agent_id, "slug": packet.slug, "rank": packet.rank, "display_name": packet.display_name,
            "job": packet.job, "goal": packet.goal, "persona": packet.persona, "effort": packet.effort,
            "effort_reason": packet.effort_reason, "harness": packet.harness, "model": packet.model,
            "launch_profile": packet.launch_profile, "naming_family": packet.naming_family,
            "character_seed": packet.character_seed, "memory_scope": memory.SCOPE_LOCAL, "repo_dir": repo}


def _write_files(state_dir: Path, home_install_id: str, packet: BodyPacket, repo: str) -> List[str]:
    from src.core.swarm import say

    agent = _agent(packet, repo)
    root = Path(repo)
    if not root.is_dir():
        raise BodyRefused("replica_folder_missing", 409)
    mirror = mirror_dir(state_dir, home_install_id, packet.home_agent_id)
    try:
        memory_mirror.write_mirror(mirror, [f.model_dump() for f in packet.memory_files])
    except (ValueError, memory.SwarmFileError) as exc:
        raise BodyRefused("bad_memory_mirror", 422, str(exc)[:200]) from exc
    defn = definition.AgentDefinition(
        slug=packet.slug, description=packet.job[:300], rank=packet.rank, effort=packet.effort,
        memory=memory.SCOPE_LOCAL if packet.rank == "task" else memory.SCOPE_PROJECT,
        brief=body_create.brief_for(agent, packet.parent_name, str(mirror)) + f"\n\n{say.THREAD_LINE}\n",
        display_name=packet.display_name)
    memory.atomic_write(root / ".claude" / "agents" / f"{packet.slug}.md", definition.render_definition(defn))
    memory.atomic_write(root / ".codex" / "agents" / f"{packet.slug}.toml", definition.render_codex_twin(defn))
    definition.add_exclude_lines(root, packet.slug)
    launch.desk_dir(remote_state(state_dir, home_install_id), packet.home_agent_id).mkdir(parents=True, exist_ok=True)
    return launch.swarm_argv(agent, remote_state(state_dir, home_install_id))


def hosted_count() -> int:
    try:
        from src.config import settings as app_settings

        with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
            remote = conn.execute("SELECT COUNT(*) FROM swarm_remote_bodies WHERE torn_down_at IS NULL").fetchone()[0]
            from src.core.swarm import store
            return int(remote) + int(store.live_body_count(conn))
    except (sqlite3.Error, OSError, db.DatastoreUnreadableError):
        return 0


def _project_root(conn: sqlite3.Connection, project_uid: str) -> str:
    row = conn.execute("SELECT root, pack_state FROM projects WHERE uid = ?", (project_uid,)).fetchone()
    if row is None or row[1] == "moved_away":
        raise BodyRefused("project_not_here", 409)
    return str(row[0])


def _relay_env(account_key: Optional[str], home_install_id: str) -> Optional[Dict[str, str]]:
    if not account_key:
        return None
    from src.core.pack.relay import target_side

    path = target_side.relay_profile_dir(account_key, home_install_id)
    return {"CLAUDE_CONFIG_DIR": path} if Path(path).is_dir() else None


async def host(request: Any, home_install_id: str, packet: BodyPacket) -> Dict[str, Any]:
    from src.config import settings as app_settings
    from src.core.pack.machines import config_state, restrictions
    from src.core.swarm import store

    state_dir = app_settings.get_state_dir()
    restr = await asyncio.to_thread(config_state.default().restrictions)
    restrictions.enforce(restr, restrictions.ACTION_HOST_AGENTS, project_uid=packet.project_uid, live_agents=await asyncio.to_thread(hosted_count))

    def read() -> Dict[str, Any]:
        with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
            root = _project_root(conn, packet.project_uid)
            found = conn.execute("SELECT session_row_id, torn_down_at FROM swarm_remote_bodies WHERE home_install_id = ? AND home_agent_id = ?",
                                 (home_install_id, packet.home_agent_id)).fetchone()
            refusal = body.caps_refusal(conn, {"parent_id": None, "project_id": None, "rank": packet.rank})
            return {"root": root, "existing": found, "refusal": refusal}

    seen = await asyncio.to_thread(read)
    live_row = seen["existing"][0] if seen["existing"] and seen["existing"][1] is None else None
    if live_row is None and packet.adopt_session_uuid:
        return await _adopt(request, state_dir, home_install_id, packet)
    if seen["refusal"] and live_row is None:
        raise BodyRefused("host_busy", 503, seen["refusal"])
    repo = seen["root"]
    if packet.worktree_branch and live_row is None:
        from src.core.crosstalk.spawn import _worktree
        try:
            repo = await _worktree(repo, packet.worktree_branch)
        except (ValueError, RuntimeError) as exc:
            raise BodyRefused("worktree_refused", 409, str(exc)[:200]) from exc
        try:
            await body.run_db(lambda c: trust_store.inherit(c, repo, packet.project_uid, projects_dir=str(settings.get_working_dir())))
        except sqlite3.Error as exc:
            logger.warning("pack_trust_inherit_failed", error_type=type(exc).__name__)
    try:
        argv = await asyncio.to_thread(_write_files, state_dir, home_install_id, packet, repo)
    except (body_create.CreateRefused, OSError) as exc:
        raise BodyRefused("files_not_written", 503, f"{type(exc).__name__}") from exc
    except memory.SwarmFileError as exc:
        raise BodyRefused("secret_in_packet", 422, str(exc)[:200]) from exc
    if live_row is not None:
        return await _recreate(request, state_dir, live_row, _relay_env(packet.account_key, home_install_id), argv)
    try:
        made = await peer_create.create_pane(request, target_dir=repo, agent_type=packet.launch_profile or packet.harness,
                                             label=packet.display_name, model=packet.model, extra_args=argv,
                                             extra_env=_relay_env(packet.account_key, home_install_id))
    except peer_create.PeerCreateRefused as exc:
        raise BodyRefused(exc.code, exc.status) from exc

    await asyncio.to_thread(_record, state_dir, home_install_id, packet, made["row_id"])
    made.pop("row_id", None)
    logger.info("swarm_remote_body_hosted", home_agent=packet.home_agent_id, rank=packet.rank)
    return made


def _record(state_dir: Path, home_install_id: str, packet: BodyPacket, row_id: int) -> None:
    with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
        with conn:
            conn.execute("INSERT OR REPLACE INTO swarm_remote_bodies (session_row_id, home_install_id, home_agent_id, project_uid, "
                         "rank, slug, definition_rev, mirror_dir, created_at, torn_down_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
                         "strftime('%Y-%m-%dT%H:%M:%SZ','now'), NULL)",
                         (row_id, home_install_id, packet.home_agent_id, packet.project_uid, packet.rank, packet.slug,
                          packet.definition_rev, str(mirror_dir(state_dir, home_install_id, packet.home_agent_id))))


def _adoptable(state_dir: Path, session_uuid: str) -> Dict[str, Any]:
    with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, session_uuid, working_dir, archived_at, host_key, COALESCE(title, claude_title, tmux_name) AS label "
                           "FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
        if row is None or row["archived_at"] or (row["host_key"] or "local") != "local" or not row["working_dir"]:
            raise BodyRefused("adopt_refused", 409, "no such local session")
        taken = conn.execute("SELECT 1 FROM swarm_agents WHERE session_row_id = ? UNION ALL SELECT 1 FROM swarm_remote_bodies "
                             "WHERE session_row_id = ? AND torn_down_at IS NULL", (row["id"], row["id"])).fetchone()
        if taken:
            raise BodyRefused("adopt_refused", 409, "that session is already an agent's body")
        return dict(row)


async def _adopt(request: Any, state_dir: Path, home_install_id: str, packet: BodyPacket) -> Dict[str, Any]:
    from src.core.swarm import project_promote

    session = await asyncio.to_thread(_adoptable, state_dir, str(packet.adopt_session_uuid))
    try:
        argv = await asyncio.to_thread(_write_files, state_dir, home_install_id, packet, session["working_dir"])
    except (body_create.CreateRefused, OSError) as exc:
        raise BodyRefused("files_not_written", 503, f"{type(exc).__name__}") from exc
    except memory.SwarmFileError as exc:
        raise BodyRefused("secret_in_packet", 422, str(exc)[:200]) from exc
    try:
        await project_promote.stop_if_running(request.app.state, session)
    except project_promote.PromoteRefused as exc:
        raise BodyRefused("adopt_refused", 409, str(exc)[:200]) from exc
    await asyncio.to_thread(_record, state_dir, home_install_id, packet, session["id"])
    logger.info("swarm_remote_body_adopted", home_agent=packet.home_agent_id, row_id=session["id"])
    return await _recreate(request, state_dir, session["id"], _relay_env(packet.account_key, home_install_id), argv)


async def _recreate(request: Any, state_dir: Path, row_id: int, extra_env: Optional[Dict[str, str]] = None,
                    argv: Optional[List[str]] = None) -> Dict[str, Any]:
    from src.api.recreate_action import recreate_by_uuid
    from src.core.crosstalk import directory

    manager = request.app.state.session_manager
    info = await body.run_db(lambda c: c.execute("SELECT session_uuid, agent_type FROM sessions WHERE id = ?", (row_id,)).fetchone())
    if info is None or not info["session_uuid"]:
        raise BodyRefused("session_row_gone", 409)
    answer = await recreate_by_uuid(str(info["session_uuid"]), info["agent_type"] or "claude", get_manager=lambda: manager, fresh=False, extra_env=extra_env, fresh_if_transcript_absent=True,
                                    swarm_args=argv)
    if answer.status != "started":
        raise BodyRefused("recreate_refused", 409, answer.detail or "")
    now = await manager.get_session_info(answer.session_id)
    if now is None or now.session_row_id != row_id:
        raise BodyRefused("created_session_not_listed", 503)
    return {"id": answer.session_id, "tmux_name": now.tmux_session, "working_dir": now.session.working_dir,
            "epoch": now.session.tmux_created_epoch, "session_uuid": str(info["session_uuid"])}
