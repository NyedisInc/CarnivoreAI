
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set, Tuple

import structlog

from src.core.agent_family_display import resolve_family_for_display
from src.core.attention.codex_gather import (
    DEFAULT_CODEX_HOME, gather_codex_evidence, rollout_path_in_sessions,
)
from src.core.approvals.extract import DIALOG_SCROLLBACK_LINES, extract_dialog_scrolled
from src.core.attention.codex_pane import classify_codex_pane
from src.core.attention.codex_reader import CodexEvidence
from src.core.attention.codex_stores import resolve_primary_uuid
from src.core.attention.evidence import Evidence, FAMILY_CLAUDE, FAMILY_CODEX
from src.core.attention.pane_markers import classify_pane_tail
from src.core.attention.process_scope import evidence_process_floor
from src.core.attention.record_identity import RecordIdentity
from src.core.attention.restart_floor import RestartFloors
from src.core.attention.registry_read import read_registry_index
from src.core.attention.resolve import resolve_attention
from src.core.attention.screen_demand import ScreenDemand, decide, stays_sticky
from src.core.attention.screen_reuse import ScreenReuse
from src.core.attention.startup_screen import StartupScreenMemory, read_startup_screen
from src.core.claude_config.profile_roots import registry_file_path
from src.core.attention.output_holders import open_file_path
from src.core.background_work.measured import (
    UNREADABLE, ProcessSnapshot, measure_background,
)
from src.core.background_work.open_count import BackgroundCountReader
from src.core.attention.watcher import WatchTarget
from src.core.hosts.identity import is_remote_backend
from src.core.hosts.remote_attention import RemotePass, read_remote_evidence
from src.core.resource_push.pane_facts_watch import PaneFactsWatch
from src.core.listing_attention import attention_reads_for_name
from src.core.session_agent_evidence import choose_agent_evidence, recorded_launch_family
from src.core.session_status import LIVENESS_LIVE, resolve_listing_liveness
from src.core.session_status_map import listing_proves_alive
from src.core.session_status_seed_read import read_instance_row
from src.core.subagents.parked_work import ParkedWorkReader
from src.core.subagents.reader import subagents_dir_for
from src.core.subagents.tally import SubagentTallyCache, process_start_for
from src.core.skill_fires.tally import SkillTallyCache
from src.core.timers.tally import TimerTallyCache

logger = structlog.get_logger()
CAPTURE_TIMEOUT_SECONDS = 2.0
PROCESS_SNAPSHOT_MAX_AGE_SECONDS = 10.0


class AttentionEvidenceReader:

    def __init__(
        self, manager: Any,
        instance_for: Callable[[str], Tuple[Optional[str], Optional[int]]],
        publish_status_map: Optional[Callable[[Any], None]] = None,
        restart_floors: Optional[RestartFloors] = None,
        watch_codex_rollouts: Callable[[], bool] = lambda: False,
        ask_open: Callable[[str], bool] = lambda key: False,
        record_identity: Optional[RecordIdentity] = None,
    ) -> None:
        self._manager = manager
        self._restart_floors = restart_floors
        self._watch_codex_rollouts = watch_codex_rollouts
        self._publish_status_map = publish_status_map
        self._instance_for = instance_for
        self._lock = threading.Lock()
        self._pass_at: Optional[datetime] = None
        self._status_map: Any = None
        self._registry_index: Any = None
        self._wrappers: Any = None
        self._instances: Any = None
        self._parents_at: Optional[datetime] = None
        self._snapshot: ProcessSnapshot = UNREADABLE
        self._snapshot_signature: tuple = ()
        self._snapshot_taken_at: float = 0.0
        self._fresh_next: bool = False
        self._subagents = SubagentTallyCache()
        self._timers = TimerTallyCache()
        self._skills = SkillTallyCache()
        self._parked = ParkedWorkReader()
        self._background = BackgroundCountReader()
        self._paths: Dict[str, Tuple[str, ...]] = {}
        self._transcripts: Dict[str, Tuple[str, str]] = {}
        self._codex_rollouts: Dict[str, str] = {}
        self._startup_screens = StartupScreenMemory()
        self._remote = RemotePass()
        self._pane_facts = PaneFactsWatch()
        self._screens = ScreenReuse()
        self._demand = ScreenDemand()
        self._ask_open = ask_open
        self._record_identity = record_identity if record_identity is not None else RecordIdentity()

    def _pass(self, now: datetime) -> Tuple[Any, Any, Any]:
        from src.core.session_manager import _configured_wrappers

        with self._lock:
            if self._pass_at != now:
                status_map = self._manager._build_tmux_status_map()
                registry_index = read_registry_index()
                wrappers = _configured_wrappers()
                self._status_map = status_map
                if self._publish_status_map is not None:
                    self._publish_status_map(status_map)
                self._registry_index = registry_index
                self._record_identity.refresh(
                    (record.pid, record.proc_start) for record in (registry_index or {}).values()
                    if getattr(record, "known", False) and getattr(record, "proc_start", None))
                self._wrappers = wrappers
                self._instances = self._read_instances(status_map)
                if getattr(status_map, "complete", False):
                    self._screens.retain_only(
                        (getattr(status_map, "socket", None), name) for name in status_map
                    )
                self._pass_at = now
            return self._status_map, self._registry_index, self._wrappers

    def _read_instances(self, status_map: Any) -> Any:
        if not getattr(status_map, "complete", False):
            return None
        names = [name for name in status_map.keys() if name]
        if not names:
            return None
        index = self._manager._instance_index_for_listing(
            socket=self._manager._tmux_socket_name(), names=names
        )
        return (index, frozenset(names)) if getattr(index, "complete", False) else None

    def _stored_rows(self, name: str, epoch: Optional[int], session_id: str) -> Tuple[dict, dict]:
        with self._lock:
            instances = self._instances
        if instances is not None and name in instances[1]:
            index = instances[0]
            row = read_instance_row(self._manager, name, epoch, session_id=session_id, index=index)
            return row or {}, index.row_identity(name, epoch) or {}
        row = read_instance_row(self._manager, name, epoch, session_id=session_id)
        return row or {}, self._manager._identity_for_instance(name, epoch) or {}

    def read_fresh(self, target: WatchTarget, now: datetime) -> Optional[Evidence]:
        with self._lock:
            self._snapshot_taken_at = 0.0
            self._fresh_next = True
        return self(target, now, force_screen=True)

    def __call__(self, target: WatchTarget, now: datetime, *,
                 force_screen: bool = False) -> Optional[Evidence]:
        backend = self._manager._registry.backends.get(target.session_id)
        if is_remote_backend(backend):
            return read_remote_evidence(self._manager, self._remote, target.session_id,
                                        backend, now)
        name, epoch = self._instance_for(target.session_id)
        if not name:
            return None
        socket = getattr(backend, "socket_name", None)
        status_map, registry_index, wrappers = self._pass(now)
        proved = listing_proves_alive(status_map, name, backend_socket=socket)
        pane_row = status_map.get(name, {}) if proved else {}
        measured_epoch = pane_row.get("created_at_epoch")
        if epoch is not None and measured_epoch is not None and epoch != measured_epoch:
            return None
        epoch = measured_epoch if measured_epoch is not None else epoch
        if pane_row:
            self._pane_facts.observe(target.session_id, pane_row)
        liveness = resolve_listing_liveness(
            exists=True if proved else None, pane_status=pane_row.get("status")
        )
        row, identity = self._stored_rows(name, epoch, target.session_id)
        session = self._manager._registry.sessions.get(target.session_id)
        chosen = choose_agent_evidence(
            memory_agent_type=getattr(session, "agent_type", None),
            memory_from_fingerprint=getattr(session, "agent_type_via_fingerprint", False),
            row_agent_type=identity.get("agent_type"),
            row_family_source=identity.get("agent_family_source"),
        )
        family, _ = resolve_family_for_display(
            chosen.agent_type, wrappers, from_fingerprint=chosen.from_fingerprint,
            from_process=chosen.from_process,
        )
        recorded = recorded_launch_family(
            row_agent_family=identity.get("agent_family"),
            row_family_source=identity.get("agent_family_source"),
            row_agent_type=identity.get("agent_type"),
            effective_agent_type=chosen.agent_type,
        )
        if recorded is not None:
            family = recorded[0]
        family_name = family.name if family else None
        uuid = row.get("claude_session_uuid")
        cwd = row.get("working_dir") or getattr(session, "working_dir", None)
        floors = self._restart_floors
        restarted_at = floors.floor_for(target.session_id) if floors is not None else None
        registry, transcript = attention_reads_for_name(
            name, registry_index=registry_index, session_started_epoch=epoch,
            claude_session_uuid=uuid if family_name != FAMILY_CODEX else None,
            working_dir=str(cwd) if cwd else None, now=now,
            pane_id=pane_row.get("pane_id"), pane_pid=pane_row.get("pid"),
            process_parents=lambda: self._process_parents(now),
            process_floor_at=restarted_at,
        )
        picked_uuid = None
        codex = None
        if family_name == FAMILY_CODEX:
            pane_pid = pane_row.get("pid")
            measured_uuid = None
            if pane_pid is not None:
                measured_uuid = resolve_primary_uuid(
                    DEFAULT_CODEX_HOME, pane_current_path=str(cwd or ""), pane_title="",
                    pane_pid=pane_pid, process_parents=self._process_parents(now),
                )
                if measured_uuid and measured_uuid != uuid:
                    picked_uuid = measured_uuid
                    uuid = measured_uuid
            codex = (gather_codex_evidence(
                measured_uuid, codex_home=DEFAULT_CODEX_HOME, now=now
            ) if measured_uuid else None) or CodexEvidence()
        elif registry.instance_present:
            uuid = registry.session_uuid or registry.record_session_uuid or uuid
        started = process_start_for(registry, uuid)
        subagents = self._subagents.tally(
            family_name, uuid, str(cwd) if cwd else None, started, now,
        )
        parked = None
        background_open = None
        background_process = None
        skill_source = None
        if family_name == FAMILY_CODEX and uuid:
            skill_source = rollout_path_in_sessions(DEFAULT_CODEX_HOME, uuid)
        if family_name == FAMILY_CODEX:
            self._remember_codex_rollout(target.session_id, skill_source)
        if family_name in (None, FAMILY_CLAUDE):
            transcript_path = self._subagents.transcript_path(uuid, str(cwd) if cwd else None)
            skill_source = transcript_path
            self._remember_paths(target.session_id, registry, transcript_path)
            parked = self._parked.read(
                family_name, transcript_path,
                registry, transcript, now, process_started_at=started,
                process_parents=lambda: self._process_parents(now),
            )
            claude_pid = registry.pid if started is not None else None
            background_open = self._background.read(
                transcript_path,
                claude_pid=claude_pid,
                process_parents=self._process_parents(now),
                process_started_at=started, now=now,
            )
            if family_name == FAMILY_CLAUDE or registry.known:
                background_process = measure_background(
                    claude_pid, self._process_snapshot(now), stdout_of=lambda pid: open_file_path(pid, 1),
                )
        timers = self._timers.tally(
            family_name, uuid, str(cwd) if cwd else None, registry, now,
        )
        skills = self._skills.tally(family_name, skill_source)
        evidence = Evidence(
            tmux_liveness=liveness, agent_family=family_name,
            registry=registry, transcript=transcript, pane=None, codex=codex,
            now=now, identity=(socket, name, epoch, pane_row.get("pid"), uuid),
            codex_bind_uuid=picked_uuid, subagents=subagents, timers=timers, skills=skills,
            parked_work=parked, background_open=background_open,
            background_process=background_process,
            process_floor_at=evidence_process_floor(epoch, restarted_at),
        )
        if liveness != LIVENESS_LIVE or family_name not in (None, FAMILY_CLAUDE, FAMILY_CODEX):
            return replace(evidence, startup_screen=self._startup_screen(
                target.session_id, None, evidence, None, pane_row, now))
        return self._with_screen(target, evidence, socket, name, pane_row, now, force_screen)

    def _with_screen(self, target: WatchTarget, evidence: Evidence, socket: Optional[str], name: str,
                     pane_row: dict, now: datetime, forced: bool) -> Evidence:
        registry = evidence.registry
        paneless = resolve_attention(evidence)
        mono = time.monotonic()
        decision = decide(
            family=evidence.agent_family, registry=registry,
            identity_proven=self._record_identity.proven(registry.pid, registry.proc_start),
            ask_open=self._ask_open(target.key), paneless=paneless,
            sticky=self._demand.sticky(target.session_id),
            seconds_since_read=self._demand.since_read(target.session_id, mono), forced=forced)
        logger.debug("attention_screen_decision", session_id=target.session_id, read=decision.read,
                     reason=decision.reason, registry_status=registry.status if registry.known else None,
                     paneless_state=paneless.state, paneless_tier=paneless.tier)
        if not decision.read:
            return replace(evidence, screen_decision=decision, startup_screen=self._startup_screen(
                target.session_id, None, evidence, None, pane_row, now))
        text = self._screen_text(socket, name, pane_row)
        pane = dialog = None
        codex = evidence.codex
        more = lambda: self._capture(socket, name, DIALOG_SCROLLBACK_LINES)  # noqa: E731
        if text is not None and evidence.agent_family == FAMILY_CODEX:
            codex = replace(codex, pane=classify_codex_pane(text))
            if codex.pane.approval_dialog or codex.pane.trust_dialog:
                dialog = extract_dialog_scrolled(text, FAMILY_CODEX, more)
        elif text is not None:
            pane = classify_pane_tail(text.splitlines())
            if (pane.shows_dialog or pane.trust_dialog or not registry.instance_present
                    or (registry.known and registry.waiting_for)):
                dialog = extract_dialog_scrolled(text, FAMILY_CLAUDE, more)
        startup_screen = self._startup_screen(target.session_id, text, evidence, pane, pane_row, now)
        sticky = stays_sticky(text=text, pane=codex.pane if codex is not None else pane, dialog=dialog,
                              startup_screen=startup_screen, paneless=paneless, registry=registry)
        self._demand.record_read(target.session_id, mono, sticky)
        return replace(evidence, pane=pane, codex=codex, dialog=dialog, startup_screen=startup_screen,
                       screen_decision=decision)

    def _startup_screen(self, session_id: str, text: Optional[str], evidence: Evidence, pane: Any,
                        pane_row: dict, now: datetime) -> Any:
        return read_startup_screen(
            self._startup_screens, session_id, text=text, registry=evidence.registry, pane=pane,
            pane_pid=pane_row.get("pid"), snapshot=lambda: self._process_snapshot(now),
            instance=evidence.identity[:4], now=now)

    def set_skill_probe(self, probe: Any) -> None:
        self._skills.set_probe(probe)

    def _remember_paths(self, session_id: str, registry: Any, transcript: Any) -> None:
        paths = []
        if registry.pid is not None:
            paths.append(registry_file_path(registry.pid))
        if transcript is not None:
            paths += [str(transcript), str(subagents_dir_for(transcript))]
        with self._lock:
            self._paths[session_id] = tuple(paths)
            if transcript is None:
                self._transcripts.pop(session_id, None)
            else:
                self._transcripts[session_id] = (str(transcript), str(subagents_dir_for(transcript)))

    def paths_for(self, session_id: str) -> Optional[Tuple[str, str]]:
        with self._lock:
            return self._transcripts.get(session_id)

    def _remember_codex_rollout(self, session_id: str, rollout: Optional[str]) -> None:
        with self._lock:
            if rollout:
                self._codex_rollouts[session_id] = rollout
            else:
                self._codex_rollouts.pop(session_id, None)

    def rollout_for(self, session_id: str) -> Optional[str]:
        with self._lock:
            return self._codex_rollouts.get(session_id)

    def watch_paths(self, session_ids: Set[str]) -> Dict[str, Tuple[str, ...]]:
        self._pane_facts.retain(session_ids)
        self._demand.retain_only(session_ids)
        with self._lock:
            self._paths = {k: v for k, v in self._paths.items() if k in session_ids}
            self._transcripts = {k: v for k, v in self._transcripts.items() if k in session_ids}
            self._codex_rollouts = {k: v for k, v in self._codex_rollouts.items() if k in session_ids}
            watched = dict(self._paths)
            if self._watch_codex_rollouts():
                for session_id, rollout in self._codex_rollouts.items():
                    watched[session_id] = watched.get(session_id, ()) + (rollout,)
            return watched

    def _process_parents(self, now: datetime) -> dict[int, int]:
        return self._process_snapshot(now).parents  # type: ignore[return-value]

    def _process_snapshot(self, now: datetime) -> ProcessSnapshot:
        """The ONE ``ps`` snapshot of this pass, parents and commands, shared by every pane.

        Description: taken at most once per pass (keyed on the pass's
          ``now``), so identity proof, the background count and the
          measured background answer (issue #1185) all walk the same table.
          A table that could not be read is :data:`UNREADABLE`, never empty.
        Inputs: now (datetime) - the pass clock.
        Output: ProcessSnapshot.
        """
        from src.core.claude_resume_argv import SHARED_TABLE_MAX_AGE_SECONDS, list_process_table

        with self._lock:
            if self._parents_at != now:
                signature = self._process_signature()
                aged = time.monotonic() - self._snapshot_taken_at
                reusable = (
                    self._snapshot is not UNREADABLE
                    and signature == self._snapshot_signature
                    and aged < PROCESS_SNAPSHOT_MAX_AGE_SECONDS
                )
                if not reusable:
                    max_age = 0.0 if self._fresh_next else SHARED_TABLE_MAX_AGE_SECONDS
                    self._fresh_next = False
                    rows = list_process_table(max_age=max_age)
                    self._snapshot = UNREADABLE if not rows else ProcessSnapshot(
                        parents={row.pid: row.ppid for row in rows},
                        commands={row.pid: row.command for row in rows},
                    )
                    self._snapshot_signature = signature
                    self._snapshot_taken_at = time.monotonic()
                self._parents_at = now
            return self._snapshot

    def _process_signature(self) -> tuple:
        pane_pids = frozenset(
            row.get("pid") for row in (self._status_map or {}).values() if isinstance(row, dict)
        )
        registry_pids = frozenset(
            getattr(record, "pid", None) for record in (self._registry_index or {}).values()
        )
        marks = []
        for path in sorted({p for paths in self._paths.values() for p in paths}):
            try:
                st = os.stat(path)
            except OSError:
                marks.append((path, None))
                continue
            marks.append((path, st.st_mtime_ns, st.st_size))
        return (pane_pids, registry_pids, tuple(marks))

    def _screen_text(self, socket: Optional[str], name: str, pane_row: dict) -> Optional[str]:
        """This pane's visible screen: the kept capture while tmux proves it unchanged, else a capture.

        Description: ``pane_row`` is THIS pass's listing row, taken after
          any earlier capture of the pane, which is what lets its stamp
          prove nothing was written since (``attention/screen_reuse.py``).
          The clocks are read immediately before a capture starts.
        Inputs: socket (str | None); name (str) - tmux session name;
          pane_row (dict) - the listing row, ``{}`` when unproven.
        Output: str | None - None when the capture failed.
        """
        pane = (socket, name)
        kept = self._screens.reusable(pane, pane_row, time.time(), time.monotonic())
        if kept is not None:
            return kept
        started_wall, started_mono = time.time(), time.monotonic()
        text = self._capture(socket, name)
        self._screens.keep(pane, pane_row, text, started_wall, started_mono)
        return text

    @staticmethod
    def _capture(socket: Optional[str], name: str, history: int = 0) -> Optional[str]:
        from src.core.tmux_backend import _safe_target
        from src.core.tmux_discovery import tmux_argv_prefix

        if not socket:
            return None
        try:
            result = subprocess.run(
                tmux_argv_prefix(socket) + ["capture-pane", "-p", "-S", str(-history) if history > 0 else "0",
                                            "-t", _safe_target(name)],
                capture_output=True, timeout=CAPTURE_TIMEOUT_SECONDS, check=False,
                close_fds=False,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            logger.warning("attention_capture_failed", tmux_name=name, error=str(exc))
            return None
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace")
