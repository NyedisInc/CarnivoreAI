
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import structlog

from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.globalsync import collect, rules
from src.core.pack.globalsync.store import Status
from src.core.pack.transport import blobs

logger = structlog.get_logger()

CAP = "pack.global_setup"
BLOBS_PATH = "/federation/pack/global/blobs"
APPLY_PATH = "/federation/pack/global/apply"
APPLY_TIMEOUT = 600.0
WIRE_ERRORS = (PeerUnreachable, PeerRefused, TimeoutError, asyncio.TimeoutError, OSError, blobs.BlobError)

NOT_MAIN, ONE_WAY, NOT_APPROVED, RECEIVER_OFF, OFFLINE, OLD_VERSION = "not_main", "one_way", "not_approved", "receiver_off", "offline", "old_version"


@dataclass(frozen=True)
class PeerView:

    install_id: str
    label: str
    connected: bool
    capabilities: Sequence[str]


RequestFor = Callable[[str, float], Optional[blobs.Request]]


class GlobalSync:

    def __init__(self, *, settings: Callable[[], Dict[str, bool]], is_main: Callable[[], bool], peers: Callable[[], Sequence[PeerView]],
                 approved: Callable[[str], bool], allows: Callable[[str], Optional[bool]], contained: Callable[[str], bool],
                 accounts: Callable[[], Sequence[Any]], request_for: RequestFor, status: Status, outbox: Path, home: Path,
                 notify: Callable[[], None], installs: Optional[Status] = None) -> None:
        self.settings, self.is_main, self.peers, self._approved, self._allows = settings, is_main, peers, approved, allows
        self._contained, self.accounts, self._request_for, self.status = contained, accounts, request_for, status
        self._outbox, self._home, self._notify, self._installs = outbox, home, notify, installs
        self._lock = asyncio.Lock()

    def gate(self, peer: PeerView) -> Optional[str]:
        if not self.is_main():
            return NOT_MAIN
        if self._contained(peer.install_id):
            return ONE_WAY
        if not self._approved(peer.install_id):
            return NOT_APPROVED
        if self._allows(peer.install_id) is not True:
            return RECEIVER_OFF
        if not peer.connected:
            return OFFLINE
        return None if CAP in peer.capabilities else OLD_VERSION

    def harnesses(self) -> List[str]:
        chosen = self.settings()
        return [h for h in rules.HARNESSES if chosen.get(h)]

    async def sync(self, install_ids: Optional[Sequence[str]] = None, *, force: bool = False) -> Dict[str, str]:
        async with self._lock:
            if not self.settings().get("enabled"):
                return {}
            views = [p for p in self.peers() if install_ids is None or p.install_id in install_ids]
            outcome: Dict[str, str] = {}
            eligible: List[PeerView] = []
            reasons = await asyncio.to_thread(lambda: {v.install_id: self.gate(v) for v in views})
            for view in views:
                reason = reasons[view.install_id]
                if reason is None:
                    eligible.append(view)
                else:
                    outcome[view.install_id] = reason
                    self.status.record(view.install_id, "refused", reason=reason)
            if eligible:
                outcome.update(await self._deliver_all(eligible, force))
            self._notify()
            return outcome

    async def _deliver_all(self, eligible: Sequence[PeerView], force: bool) -> Dict[str, str]:
        harnesses = self.harnesses()
        slots = await asyncio.to_thread(collect.slots_for, self._home, list(self.accounts()), harnesses)
        bundle = self._outbox / f"global-{blobs.new_id()}.tgz"
        out: Dict[str, str] = {}
        try:
            built = await asyncio.to_thread(collect.build, slots, bundle, self._home)
            for view in eligible:
                last = self.status.get(view.install_id) or {}
                if not force and last.get("state") in ("synced", "unchanged") and last.get("digest") == built.digest:
                    out[view.install_id] = "unchanged"
                    continue
                out[view.install_id] = await self._deliver_one(view, built, harnesses)
        finally:
            await asyncio.to_thread(_remove, bundle)
        return out

    async def _deliver_one(self, view: PeerView, built: collect.Built, harnesses: Sequence[str]) -> str:
        request = self._request_for(view.install_id, APPLY_TIMEOUT)
        if request is None:
            self.status.record(view.install_id, "refused", reason=OFFLINE)
            return OFFLINE
        try:
            sha = await asyncio.to_thread(blobs.file_sha256, str(built.path))
            blob_id = await blobs.send_file(request, str(built.path), blob_id=blobs.new_id(), kind="tar", base_path=BLOBS_PATH)
            status, answer = await request("POST", APPLY_PATH, json={"blob_id": blob_id, "blob_sha256": sha, "digest": built.digest,
                                                                    "harnesses": list(harnesses)})
        except WIRE_ERRORS as exc:
            code = getattr(exc, "code", type(exc).__name__)
            logger.info("pack_global_deliver_failed", target=view.install_id, error=str(code)[:40])
            self.status.record(view.install_id, "failed", error=str(code)[:60])
            return "failed"
        if status == 200 and isinstance(answer, dict):
            self.status.record(view.install_id, "synced", digest=built.digest, sent=built.summary(), received=answer.get("report"))
            logger.info("pack_global_synced", target=view.install_id, files=built.files)
            return "synced"
        code = _detail_code(answer)
        state = "refused" if status in (401, 403, 409, 422) else "failed"
        reason = RECEIVER_OFF if code == "pack_restricted" else code or f"http_{status}"
        self.status.record(view.install_id, state, reason=reason, sent=built.summary())
        return state

    def snapshot(self) -> Dict[str, Any]:
        rows = []
        records = self.status.all()
        for view in self.peers():
            rows.append({"install_id": view.install_id, "label": view.label, "gate": self.gate(view), "last": records.get(view.install_id)})
        return {"settings": self.settings(), "is_main": self.is_main(), "computers": rows,
                "installs": self._installs.all() if self._installs is not None else {}}


def _detail_code(answer: Any) -> str:
    detail = answer.get("detail") if isinstance(answer, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else ""


def _remove(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("pack_global_outbox_remove_failed", errno=exc.errno)
