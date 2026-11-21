
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.computers import add_preview
from src.core.hosts.ssh_exec import SshArgumentError, SshDestination
from src.core.pack.jobs import boot, carry, policy
from src.core.pack.jobs.ssh import conn, readings
from src.core.pack.jobs.ssh.target import ssh_target_for
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.target import SSH_PREFIX
from src.core.pack.jobs.types import JobError, JobRecord
from src.core.pack.machines import can_block
from src.core.pack.reserve import model as reserve_model

log = structlog.get_logger(__name__)

NOT_SET_UP, OFF, KEY_UNCONFIRMED, NO_ANSWER, TAKING_WORK = "not_set_up", "off", "host_key_not_confirmed", "did_not_answer", "taking_work"
NOT_A_JOB_TARGET, HOST_DISABLED = "not_a_job_target", "host_disabled"
STATES = (NOT_SET_UP, OFF, KEY_UNCONFIRMED, NO_ANSWER, TAKING_WORK, NOT_A_JOB_TARGET, HOST_DISABLED)
PROBE_GAP_S = 60.0
_PROBED: Dict[str, float] = {}
FORGET_NAME = "any"
_KEY_FIELDS = re.compile(r"^\S+ (\S+) (\S+)")


class ConfirmHostKey(Exception):

    def __init__(self, shown: Dict[str, Any]) -> None:
        super().__init__("confirm_host_key")
        self.shown = shown


class NotJobTarget(Exception):

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def state_dir() -> Path:
    from src.config import settings

    return Path(settings.get_state_dir())


def job_store(required: bool = True) -> JobStore:
    try:
        return boot.engine().store
    except JobError:
        if required:
            raise
        return JobStore(state_dir())


def refusal(host: Any) -> Optional[Tuple[str, str]]:
    if host.is_local or host.kind != "ssh":
        return "not_ssh", "this is not a computer reached by plain ssh"
    if host.computer_install_id:
        return "paired_computer", "this is a paired computer; its own pack settings decide what it takes"
    if host.remote_carnivore == "running":
        return "runs_carnivore", "carnivore runs there; pair it instead of using it over ssh"
    return None


def candidate(host: Any) -> bool:
    return not host.is_local and host.kind == "ssh" and not host.computer_install_id


def live_jobs(store: JobStore, host_key: str) -> List[JobRecord]:
    mine = SSH_PREFIX + host_key
    return [r for r in store.list_jobs(limit=200, live_only=True) if r.peer_install_id == mine]


def _loads(text: Any) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def view_of(host: Any, row: Optional[Dict[str, Any]], reading: Optional[Dict[str, Any]], live: int) -> Dict[str, Any]:
    row, reading = row or {}, reading or {}
    pinned, takes = bool(row.get("pinned_fp")), bool(row.get("takes_work"))
    blocked = refusal(host)
    reason: Optional[str] = None
    if blocked is not None:
        state, reason = NOT_A_JOB_TARGET, blocked[1]
    elif not host.enabled:
        state, reason = HOST_DISABLED, "this computer is switched off in the hosts list"
    elif not takes:
        state = OFF if pinned else NOT_SET_UP
    elif not pinned:
        state = KEY_UNCONFIRMED
    elif reading.get("usable"):
        state = TAKING_WORK
    else:
        state, reason = NO_ANSWER, reading.get("reason") or readings.NO_ANSWER
    labels = _loads(row.get("labels_json"))
    return {
        "host_key": host.key, "label": host.label, "ssh_target": host.ssh_target, "ssh_port": host.ssh_port, "enabled": bool(host.enabled),
        "state": state, "reason": reason, "takes_work": takes, "pinned": pinned, "fingerprint": row.get("pinned_fp"),
        "labels": labels if isinstance(labels, list) else [], "reserve_config": reserve_model.from_dict(_loads(row.get("reserve_json"))).model_dump(),
        "usable": bool(reading.get("usable")), "can": reading.get("can"), "load": reading.get("load"), "pressure": reading.get("pressure"),
        "reserve": reading.get("reserve"), "taken_at": reading.get("taken_at"), "age_s": reading.get("age_s"), "last_ok": row.get("last_ok"),
        "last_ok_age_s": reading.get("last_ok_age_s"), "last_error": row.get("last_error"), "probed_at": row.get("probed_at"), "live_jobs": live,
    }


async def target_view(store: JobStore, host: Any) -> Dict[str, Any]:
    got = await readings.shared(store).poll_live(host.key)
    live = await asyncio.to_thread(live_jobs, store, host.key)
    return view_of(host, store.ssh_target_get(host.key), got, len(live))


async def all_views(store: JobStore, hosts: List[Any]) -> List[Dict[str, Any]]:
    by_key = {r.host_key: r.to_dict() for r in await readings.shared(store).for_placement()}
    rows = {r["host_key"]: r for r in await asyncio.to_thread(store.ssh_targets_all)}
    live = await asyncio.to_thread(store.list_jobs, limit=200, live_only=True)
    out = []
    for host in (h for h in hosts if candidate(h)):
        count = sum(1 for r in live if r.peer_install_id == SSH_PREFIX + host.key)
        out.append(view_of(host, rows.get(host.key), by_key.get(host.key), count))
    return out


def forget_settings(store: JobStore, host_key: str) -> None:
    store.ssh_target_drop(host_key)
    conn.unpin_key(host_key, state_dir())



async def first_contact_key(host: Any) -> Tuple[str, str, str, str]:
    try:
        dest = SshDestination(host.ssh_target or "", host.ssh_port)
    except SshArgumentError as exc:
        raise JobError("host_target_invalid", "the stored ssh target is not valid", 400) from exc
    jail = add_preview.HostKeyJail.create(secrets.token_hex(4))
    try:
        _res, fp = await add_preview.first_contact(dest, jail)
        if fp is None:
            raise JobError("unreachable", "that computer did not show a host key", 502)
        line = Path(jail.known_hosts).read_text(encoding="ascii", errors="replace").splitlines()
        found = _KEY_FIELDS.match(line[0]) if line else None
        if found is None:
            raise JobError("unreachable", "that computer did not show a usable host key", 502)
        return fp, found.group(1)[:32], f"{found.group(1)} {found.group(2)}", await add_preview.known_status(dest, fp)
    finally:
        jail.remove()


async def _pin(host: Any, row: Dict[str, Any], fingerprint: Optional[str]) -> str:
    shown_fp, kind, line, known = await first_contact_key(host)
    pinned = row.get("pinned_fp")
    if fingerprint != shown_fp:
        raise ConfirmHostKey({"fingerprints": [{"sha256": shown_fp, "type": kind}], "known": known, "pinned": pinned,
                              "changed_since_shown": fingerprint is not None})
    if pinned is not None:
        await asyncio.to_thread(conn.unpin_key, host.key, state_dir())
    await asyncio.to_thread(conn.pin_key, host.key, shown_fp, line, state_dir())
    return shown_fp


async def _check_pinned(host: Any, pinned: str) -> None:
    try:
        shown_fp, kind, _line, known = await first_contact_key(host)
    except JobError as exc:
        log.info("pack_ssh_recheck_skipped", host=host.key[:12], code=exc.code)
        return
    if shown_fp != pinned:
        raise ConfirmHostKey({"fingerprints": [{"sha256": shown_fp, "type": kind}], "known": known, "pinned": pinned, "changed_since_shown": False})


async def apply_settings(store: JobStore, host: Any, *, takes_work: bool, fingerprint: Optional[str], labels: Optional[List[str]],
                         reserve: Optional[Dict[str, Any]]) -> None:
    blocked = refusal(host)
    if blocked is not None:
        raise NotJobTarget(*blocked)
    if not host.enabled:
        raise NotJobTarget(HOST_DISABLED, "this computer is switched off in the hosts list")
    row = store.ssh_target_get(host.key) or {}
    fields: Dict[str, Any] = {"takes_work": 1 if takes_work else 0, "updated_at": time.time()}
    if labels is not None:
        fields["labels_json"] = json.dumps(can_block.clean_labels(labels))
    if reserve is not None:
        fields["reserve_json"] = json.dumps(reserve_model.merged(reserve_model.from_dict(_loads(row.get("reserve_json"))), reserve).model_dump())
    pinned = row.get("pinned_fp")
    newly = False
    if takes_work and pinned is not None and fingerprint is None:
        await _check_pinned(host, pinned)
    elif takes_work and (pinned is None or fingerprint != pinned):
        fields["pinned_fp"] = await _pin(host, row, fingerprint)
        newly = True
    was_on = bool(row.get("takes_work"))
    store.ssh_target_put(host.key, **fields)
    if takes_work and (newly or not was_on):
        await _hello(store, host)


async def _hello(store: JobStore, host: Any) -> None:
    try:
        await ssh_target_for(host.key)._far("hello")
    except JobError as exc:
        if exc.code == "missing_tools":
            store.ssh_target_put(host.key, takes_work=0, last_error=f"{exc.code}: {exc.detail}"[:256])
            raise NotJobTarget("missing_tools", f"that computer lacks tools the jobs need ({exc.detail[:120]})") from exc
        store.ssh_target_put(host.key, last_error=f"{exc.code}: {exc.detail}"[:256])
        log.info("pack_ssh_hello_failed", host=host.key[:12], code=exc.code)
    else:
        store.ssh_target_put(host.key, last_ok=time.time(), last_error=None)


async def probe(store: JobStore, host: Any, clock: Any = time.monotonic) -> Tuple[bool, Optional[Dict[str, Any]]]:
    blocked = refusal(host)
    if blocked is not None:
        raise NotJobTarget(*blocked)
    now = clock()
    if now - _PROBED.get(host.key, float("-inf")) < PROBE_GAP_S:
        return False, None
    _PROBED[host.key] = now
    try:
        answer = await ssh_target_for(host.key)._far("hello")
    except JobError as exc:
        if exc.code == "missing_tools":
            raise NotJobTarget("missing_tools", f"that computer lacks tools the jobs need ({exc.detail[:120]})") from exc
        raise
    await readings.shared(store).refresh_can(host.key, "owner probe", force=True)
    store.ssh_target_put(host.key, last_ok=time.time(), last_error=None)
    tools = [t.split()[0] for t in answer.all("tool") if t.split() and not t.endswith(" -")]
    return True, {"uname": answer.fields.get("uname"), "wsl": answer.fields.get("wsl") == "1", "git": answer.fields.get("git"),
                  "tools": tools, "far_jobs": len(answer.all("job"))}



async def forget_folders(store: JobStore, host: Any, only_uid: Optional[str] = None) -> Dict[str, Any]:
    live = await asyncio.to_thread(live_jobs, store, host.key)
    if [r for r in live if only_uid is None or r.project_uid == only_uid]:
        raise JobError("jobs_running", "a job is running on that computer", 409)
    target = ssh_target_for(host.key)
    out: Dict[str, List[Any]] = {"forgotten": [], "kept": [], "refused": []}
    for uid in await asyncio.to_thread(store.ssh_seeds_for, host.key):
        if only_uid is not None and uid != only_uid:
            continue
        try:
            got = await target._far("forget", {"uid": uid, "name": FORGET_NAME})
        except JobError as exc:
            out["refused"].append({"project": uid, "code": exc.code})
            continue
        kept = [{"project": uid, "slot": line.rsplit("/", 1)[-1][:32]} for line in got.all("kept")]
        out["kept"] += kept
        out["forgotten"].append(uid)
        if not kept:
            await asyncio.to_thread(store.ssh_seed_drop, uid, host.key)
        await asyncio.to_thread(store.base_clear, uid, SSH_PREFIX + host.key)
    try:
        await target._far("sweep")
    except JobError as exc:
        log.warning("ssh_forget_sweep_failed", host=host.key, code=exc.code, only_uid=only_uid)
    return out



async def seed_targets(store: JobStore, uid: str, root: str) -> List[str]:
    never = set(policy.get(store, uid).never_use)
    seeded: List[str] = []
    for row in await asyncio.to_thread(store.ssh_targets_all):
        key = str(row["host_key"])
        if not row.get("takes_work") or not row.get("pinned_fp") or SSH_PREFIX + key in never:
            continue
        try:
            if readings.default_link(key).label in never:
                continue
        except JobError:
            continue
        await carry.ssh_seed(root, uid, SSH_PREFIX + key, store)
        seeded.append(key)
    return seeded
