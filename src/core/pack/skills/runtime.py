
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

import structlog

from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.skills import alerts, push, receiver, status
from src.core.pack.skills.apply import REASON_NOT_DELIVERED
from src.core.pack.skills.doc import Choices, build_document
from src.core.pack.skills.push import PeerState
from src.core.pack.skills.receiver import ReceiverState
from src.core.pack.skills import warez_alpha
from src.core.pack.skills.scan import scan_root
from src.core.pack.skills.targets import SkillRoot
from src.core.pack.transport import blobs

logger = structlog.get_logger()

DEBOUNCE_SECONDS = 3.0
Sig = Optional[tuple[int, int]]


class ChoicesStore(Protocol):

    def read(self) -> Choices: ...

    def write(self, choices: Choices) -> None: ...


@dataclass(frozen=True)
class PeerView:

    peer_id: str
    label: str
    up: bool
    snapshot: Optional[Mapping[str, Any]]

    def has_cap(self) -> bool:
        caps = self.snapshot.get("capabilities") if isinstance(self.snapshot, Mapping) else None
        return caps_mod.has(caps, caps_mod.CAP_SKILLS)

    def has_ref_cap(self) -> bool:
        caps = self.snapshot.get("capabilities") if isinstance(self.snapshot, Mapping) else None
        return caps_mod.has(caps, caps_mod.CAP_SKILLS_REF)

    def has_take_cap(self) -> bool:
        caps = self.snapshot.get("capabilities") if isinstance(self.snapshot, Mapping) else None
        return caps_mod.has(caps, caps_mod.CAP_SKILLS_TAKE)

    def block(self) -> Optional[dict[str, Any]]:
        return status.clean_block(self.snapshot.get("skills")) if isinstance(self.snapshot, Mapping) else None


@dataclass(frozen=True)
class Publish:

    outcome: str
    gen: int = 0
    detail: str = ""


class SkillsSync:

    def __init__(self, *, install_id: str, state: ReceiverState, alpha_id: Callable[[], str], choices: ChoicesStore,
                 family_roots: Callable[[], dict[str, Path]], receiver_roots: Callable[[], list[SkillRoot]],
                 peers: Callable[[], Sequence[PeerView]], request_for: Callable[[str], Optional[blobs.Request]],
                 notify: Callable[[], None], outbox: Path, services: Callable[[], Any] = lambda: None, clock: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic) -> None:
        self.install_id, self.state, self._alpha_id, self.choices = install_id, state, alpha_id, choices
        self._family_roots, self._receiver_roots, self._peers, self._request_for = family_roots, receiver_roots, peers, request_for
        self._notify, self._outbox, self._clock, self._mono = notify, Path(outbox), clock, mono
        self._services = services
        self._alpha = ""
        self.problem: Optional[str] = None
        self.hold: Optional[dict[str, Any]] = None
        self._block: Optional[dict[str, Any]] = None
        self._block_sig: Sig = (-1, -1)
        self._pub: Optional[dict[str, Any]] = None
        self._pub_sig: Sig = (-1, -1)
        self._peer_sigs: dict[str, str] = {}
        self._peer_state: dict[str, PeerState] = {}
        self._tasks: set["asyncio.Task[Any]"] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._kick_pending = False
        self.after_pass: Optional[Callable[[], Any]] = None


    def refresh_alpha(self) -> str:
        self._alpha = self._alpha_id() or ""
        return self._alpha

    def is_alpha(self) -> bool:
        return bool(self._alpha) and self._alpha == self.install_id

    def _peer(self, peer_id: str, label: str = "") -> PeerState:
        ps = self._peer_state.setdefault(peer_id, PeerState())
        ps.label = label or ps.label
        return ps


    def _scans(self) -> dict[str, Any]:
        return {family: scan_root(root, family) for family, root in self._family_roots().items()}

    def _reported(self) -> list[int]:
        return status.reported_gens(v.block() for v in self._peers())

    @staticmethod
    def _adopt_choices(accepted: Mapping[str, Any]) -> Choices:
        raw = accepted.get("choices") or {}
        return Choices(mode=raw.get("mode", "off"), include=frozenset((a, b) for a, b in raw.get("include", [])),
                       exclude=frozenset((a, b) for a, b in raw.get("exclude", [])))

    def publish_pass(self, *, force: bool = False, min_gen: int = 0) -> Publish:
        if self.refresh_alpha() != self.install_id:
            return Publish("not_alpha")
        scans = self._scans()
        wplan = warez_alpha.plan(self._services(), self._family_roots())
        with self.state.lock:
            data = self.state.load()
            prev, accepted = data.get("published"), data.get("doc")
            if prev is not None and prev.get("alpha") != self.install_id:
                prev = None
            choices = self.choices.read()
            takeover = bool(accepted) and accepted.get("alpha") != self.install_id and (prev is None or accepted["gen"] > prev["gen"])
            if takeover:
                effective = self._adopt_choices(accepted) if choices.mode == "off" else choices
                differs = status.takeover_differences(accepted, scans, effective, wplan)
                behind = int(data.get("applied_gen") or 0) < max(self._reported(), default=0)
                if (differs or behind) and not force:
                    self._set_hold({"differs": differs, "behind": behind})
                    return Publish("hold", detail=f"differs {differs}, behind {behind}")
                adopted = self._adopt_choices(accepted)
                if adopted != choices and choices.mode == "off":
                    self.choices.write(adopted)
                    choices = adopted
            self._set_hold(None)
            return self._publish_locked(data, prev, choices, scans, min_gen, wplan)

    def _set_hold(self, hold: Optional[dict[str, Any]]) -> None:
        if hold != self.hold:
            self.hold = hold
            self._notify()

    def _set_problem(self, problem: Optional[str]) -> None:
        if problem != self.problem:
            self.problem = problem
            self._notify()

    def _publish_locked(self, data: dict[str, Any], prev: Optional[dict[str, Any]], choices: Choices, scans: dict[str, Any],
                        min_gen: int, wplan: warez_alpha.WarezPlan) -> Publish:
        now = int(self._clock())
        queued = data.get("queued") or {}
        carried = {"removals": [*(prev or {}).get("removals", []), *queued.get("removals", [])],
                   "unsynced": [*(prev or {}).get("unsynced", []), *queued.get("unsynced", [])]}
        carried.update(warez=wplan.entries, catalog_held=wplan.held, catalog_pairs=wplan.pairs)
        built = build_document(alpha=self.install_id, gen=0, made_at=now, choices=choices, scans=scans, previous=prev, **carried)
        if built.document is None:
            self._set_problem(built.problem)
            return Publish("problem", detail=built.problem or "")
        self._set_problem(None)
        doc = built.document
        if prev is not None:
            still = {(f, n) for f, n, _ in doc["skills"]} | {(f, n) for f, n, _ in doc["held"]} | {(e[0], e[1]) for e in doc["warez"]}
            dropped = [[f, n, now] for f, n, *_ in [*prev["skills"], *prev.get("warez", [])] if (f, n) not in still]
            if dropped:
                carried["unsynced"] = [*carried["unsynced"], *dropped]
                doc = build_document(alpha=self.install_id, gen=0, made_at=now, choices=choices, scans=scans, previous=prev,
                                     **carried).document or doc
        if prev is None and not doc["skills"] and not doc["held"] and not doc["warez"]:
            return Publish("off")
        if prev is not None and status.content_key(doc) == status.content_key(prev) and min_gen <= prev["gen"]:
            return Publish("unchanged", prev["gen"])
        doc["gen"] = status.next_gen((prev or {}).get("gen", 0), [*self._reported(), int(data.get("applied_gen") or 0)], min_gen)
        data["published"], data["queued"] = doc, {}
        self._pub_sig = (-1, -1)
        if not self.state.save(data):
            self._set_problem("cannot save the skills state")
            return Publish("problem", detail="cannot save")
        self._notify()
        logger.info("pack_skills_published", gen=doc["gen"], skills=len(doc["skills"]), warez=len(doc["warez"]), held=len(doc["held"]))
        return Publish("published", doc["gen"])

    def published(self) -> Optional[dict[str, Any]]:
        sig = self._file_sig()
        if sig != self._pub_sig:
            doc = self.state.load().get("published")
            self._pub = doc if isinstance(doc, dict) and doc.get("alpha") == self.install_id else None
            self._pub_sig = sig
        return self._pub

    def republish(self, min_gen: int) -> Optional[dict[str, Any]]:
        self.publish_pass(min_gen=min_gen)
        return self.published()


    def check_pass(self) -> Optional[dict[str, Any]]:
        alerts.check_alpha(self.state, "check")
        alerts.check_placers(self.state)
        data = self.state.load()
        alpha = self.refresh_alpha() == self.install_id
        published, doc = data.get("published"), data.get("doc")
        applied = int(data.get("applied_gen") or 0)
        gen = int(published["gen"]) if isinstance(published, dict) and published.get("alpha") == self.install_id else None
        off: list[status.OffRow] = []
        if not alpha and isinstance(doc, dict):
            held = {(r["family"], r["name"], r["root"]) for r in data.get("applied", [])
                    if r.get("state") == receiver.CONFLICT and r.get("reason") == REASON_NOT_DELIVERED and r.get("gen") == applied}
            off = status.off_pairs(receiver.survey(doc, self._receiver_roots()), held)
        conflicts = 0 if alpha else sum(1 for r in data.get("applied", []) if r.get("state") == receiver.CONFLICT)
        block = status.block(gen, applied, off, conflicts) if (gen is not None or isinstance(doc, dict)) else None
        if block != self._block:
            self._block = block
            self._notify()
        self._block_sig = self._file_sig()
        return block

    def _file_sig(self) -> Sig:
        try:
            info = os.stat(self.state.path)
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def skills_block(self) -> Optional[dict[str, Any]]:
        if self._file_sig() != self._block_sig:
            self.check_pass()
        return self._block


    def _wants(self, view: PeerView) -> bool:
        doc = self.published()
        if not self.is_alpha() or doc is None or not view.has_cap() or self.hold is not None:
            return False
        ps = self._peer(view.peer_id, view.label)
        block, gen = view.block(), int(doc["gen"])
        if not (block is None or block["applied_gen"] < gen or block["off_count"] > 0):
            ps.last_try = None
            return False
        key = (gen, block["applied_gen"] if block else None, block["off_digest"] if block else None)
        if ps.busy or key == ps.last_try or self._mono() < ps.next_at:
            return False
        ps.pending_key = key
        return True

    def seen(self, peer_id: str, snapshot: Mapping[str, Any]) -> bool:
        sig = repr(snapshot.get("skills"))
        if self._peer_sigs.get(peer_id) != sig:
            self._peer_sigs[peer_id] = sig
            self._notify()
        wants = self._wants(PeerView(peer_id, str(snapshot.get("label") or ""), True, snapshot))
        if wants:
            self.spawn(self.deliver_pass(peer_id))
        return wants

    async def deliver_pass(self, peer_id: str) -> str:
        ps = self._peer(peer_id)
        doc = await asyncio.to_thread(self.published)
        request = self._request_for(peer_id)
        if doc is None or not self.is_alpha():
            return "nothing"
        if request is None:
            return "offline"
        ps.busy = True
        try:
            roots = await asyncio.to_thread(self._family_roots)
            view = next((v for v in self._peers() if v.peer_id == peer_id), None)
            outcome = await push.deliver(request, doc, ps, roots, self._outbox, self.republish, self._mono,
                                         refs_ok=view is not None and view.has_ref_cap())
        finally:
            ps.busy = False
        if outcome == "synced":
            ps.last_try = ps.pending_key
        ps.pending_key = None
        self._notify()
        return outcome

    async def deliver_all(self) -> None:
        for view in list(self._peers()):
            if view.up and view.has_cap():
                await self.deliver_pass(view.peer_id)

    def reset_caps(self) -> None:
        for ps in self._peer_state.values():
            ps.reset()
            ps.counts.clear()
            ps.capped.clear()

    def spawn(self, coro: Any) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro, name="pack-skills-deliver")
        except RuntimeError:
            coro.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def kick(self) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._kick_on_loop)

    def _kick_on_loop(self) -> None:
        if not self._kick_pending:
            self._kick_pending = True
            self.spawn(self._kick_run())

    async def _kick_run(self) -> None:
        await asyncio.sleep(DEBOUNCE_SECONDS)
        self._kick_pending = False
        await self.run_pass()

    async def sync_now(self) -> str:
        self.reset_caps()
        await self.run_pass()
        return "alpha" if self.is_alpha() else "receiver"

    async def run_pass(self) -> None:
        await asyncio.to_thread(self.check_pass)
        await asyncio.to_thread(self.retry_refs)
        if (await asyncio.to_thread(self.publish_pass)).outcome != "not_alpha":
            await self.deliver_all()
        if self.after_pass is not None:
            await self.after_pass()

    async def on_connect(self, peer_id: str) -> None:
        self._peer(peer_id).reset()
        await asyncio.to_thread(self.check_pass)
        if self.is_alpha() and any(v.peer_id == peer_id and v.has_cap() for v in self._peers()):
            await self.deliver_pass(peer_id)


    def peer_views(self) -> Sequence[PeerView]:
        return list(self._peers())

    def request_to(self, peer_id: str) -> Optional[blobs.Request]:
        return self._request_for(peer_id)

    def receive_roots(self) -> list[SkillRoot]:
        return self._receiver_roots()

    def roots(self) -> dict[str, Path]:
        return self._family_roots()

    def services(self) -> Any:
        return self._services()

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    def retry_refs(self) -> bool:
        from src.core.pack.skills import warez_receiver

        data = self.state.load()
        doc, services = data.get("doc"), self._services()
        if isinstance(doc, dict) and doc.get("alpha") != self.refresh_alpha():
            warez_receiver.clear_hold(self.state)
            return False
        if not isinstance(doc, dict) or not doc.get("warez") or services is None or self._loop is None or self.is_alpha():
            if not isinstance(doc, dict) or doc.get("alpha") != self._alpha:
                warez_receiver.clear_hold(self.state)
            return False
        ctx = warez_receiver.Context(self.state, self._receiver_roots(), services, self._loop, doc["alpha"], int(doc["gen"]),
                                     lambda: self._alpha == doc["alpha"])
        return warez_receiver.run(doc, ctx, None, retry_only=True)

    def notify(self) -> None:
        self._notify()

    def queue_entries(self, removals: Sequence[tuple[str, str]] = (), unsynced: Sequence[tuple[str, str]] = ()) -> None:
        now = int(self._clock())
        with self.state.lock:
            data = self.state.load()
            queued = data.get("queued") or {}
            for key, pairs in (("removals", removals), ("unsynced", unsynced)):
                have = {(r[0], r[1]) for r in queued.get(key, [])}
                queued[key] = [*queued.get(key, []), *([f, n, now] for f, n in pairs if (f, n) not in have)]
            data["queued"] = queued
            self.state.save(data)


    def status(self) -> dict[str, Any]:
        doc = self.published()
        gen = int(doc["gen"]) if doc else 0
        rows: dict[str, Any] = {}
        for view in self._peers():
            ps, block = self._peer(view.peer_id, view.label), view.block()
            if not view.has_cap():
                word = "older carnivore"
            elif not view.up:
                word = "offline"
            elif ps.error == "alpha_one_way":
                word = "alpha is one way here"
            elif ps.error == "not_alpha":
                word = "alpha differs"
            elif ps.busy:
                word = "syncing"
            elif block is not None and block["applied_gen"] >= gen and block["off_count"] == 0 and not block["conflict_count"]:
                word = "in sync"
            else:
                word = "differs"
            rows[view.peer_id] = {"label": view.label, "state": word, "applied_gen": block["applied_gen"] if block else None,
                                  "off_count": block["off_count"] if block else None, "conflicts": ps.conflicts()}
        return {"role": "alpha" if self.is_alpha() else "receiver", "alpha": self._alpha, "gen": gen,
                "problem": self.problem, "hold": self.hold, "peers": rows}
