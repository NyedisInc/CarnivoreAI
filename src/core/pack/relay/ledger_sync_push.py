
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

import structlog

from src.core.hosts.identity import is_remote_info
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.relay import ledger_sync_store as store, ledger_sync_view as view, targets as targets_mod
from src.core.pack.relay.ledger_sync_wire import (CAP_LEDGER_STATUS, SESSIONS_PATH, STATUS_PATH, LedgerSessionsBody, WireSession,
                                                  status_of)
from src.core.pack.relay.owner_side import PROVIDERS, PeerFn, AllowsFn
from src.core.provider_ledger import relay_accounts
from src.models.provider_ledger import LedgerSnapshot

logger = structlog.get_logger()

RETRY_SECONDS = 30.0
OwnSessions = Dict[str, List[WireSession]]


def own_sessions_by_account(infos: Iterable[Any], self_id: str, self_label: str) -> OwnSessions:
    out: OwnSessions = {}
    for info in infos:
        account = getattr(info, "account_id", None)
        tmux = getattr(info, "tmux_session", None)
        if not account or not tmux or getattr(info, "activity_status", None) == "dead" or is_remote_info(info):
            continue
        out.setdefault(account, []).append(WireSession(name=(getattr(info, "claude_title", None) or tmux)[:200], tmux=tmux,
                                                       computer=self_label[:64], computer_id=self_id[:64]))
    for sessions in out.values():
        sessions.sort(key=lambda s: s.tmux or "")
    return out


class LedgerSync:

    def __init__(self, *, open_db: Callable[[], sqlite3.Connection], peer: PeerFn, snapshot: Callable[[], LedgerSnapshot],
                 self_id: str, self_label: str, allows: Optional[AllowsFn] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._open_db, self._peer, self._snapshot, self._clock = open_db, peer, snapshot, clock
        self._self_id, self._self_label = self_id, self_label
        self._allows: AllowsFn = allows or (lambda _iid: True)
        self._own: OwnSessions = {}
        self._sent: Dict[Tuple[str, str, str, str], str] = {}
        self._retry_at: Dict[Tuple[str, str, str, str], float] = {}
        self._only: Optional[Set[str]] = None
        self._lock = asyncio.Lock()
        self._tasks: Set["asyncio.Task[None]"] = set()


    def on_snapshot(self, _snapshot: LedgerSnapshot) -> None:
        self._spawn(None)

    def on_listing(self, infos: Iterable[Any]) -> None:
        own = own_sessions_by_account(infos, self._self_id, self._self_label)
        if own != self._own:
            self._own = own
            self._spawn(None)

    def on_connect(self, install_id: str) -> None:
        for key in [k for k in self._sent if k[1] == install_id]:
            del self._sent[key]
        self._spawn({install_id})

    def on_credential_pushed(self, account_key: str, install_ids: List[str]) -> None:
        self._spawn(set(install_ids))

    def _spawn(self, only: Optional[Set[str]]) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self.push_all(only))
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


    async def push_all(self, only: Optional[Set[str]] = None) -> int:
        async with self._lock:
            try:
                owned, pairs = await asyncio.to_thread(self._read_plan)
            except (sqlite3.Error, OSError) as exc:
                logger.warning("pack_ledger_sync_plan_failed", error=type(exc).__name__)
                return 0
            sent = 0
            rows = {r.id: r for r in self._snapshot().accounts if r.provider in PROVIDERS and not r.relayed}
            reports = await asyncio.to_thread(self._other_reports, list(owned))
            for key, target in owned:
                row = rows.get(key)
                if row is None or (only is not None and target not in only):
                    continue
                others = [s for s in reports.get(key, []) if s.computer_id != target]
                body = status_of(row, [*self._own.get(key, []), *others])
                sent += await self._send("status", target, row.provider, key, STATUS_PATH, body, owner_side=True)
            for owner, provider, key, relay_id in pairs:
                if only is not None and owner not in only:
                    continue
                mine = self._own.get(relay_id, [])
                if not mine and ("sessions", owner, provider, key) not in self._sent:
                    continue
                sent += await self._send("sessions", owner, provider, key, SESSIONS_PATH,
                                         LedgerSessionsBody(account_key=key, provider=provider, sessions=mine), owner_side=False)
            return sent

    def _read_plan(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str, str, str]]]:
        with closing(self._open_db()) as conn:
            owned = [(t.account_key, t.target_install_id) for t in targets_mod.list_all(conn) if t.state == "pushed"]
        peers, _ = view.directory()
        pairs: List[Tuple[str, str, str, str]] = []
        for account in relay_accounts.relay_accounts() + relay_accounts.codex_relay_accounts():
            match = relay_accounts.RELAY_NAME_RE.fullmatch(account.id) or relay_accounts.CODEX_RELAY_NAME_RE.fullmatch(account.id)
            if match is None:
                continue
            for iid in peers:
                if targets_mod.profile_name_for(account.provider, match.group(2), iid) == account.id:
                    pairs.append((iid, account.provider, match.group(2), account.id))
        return owned, pairs

    def _other_reports(self, keys: List[Tuple[str, str]]) -> Dict[str, List[WireSession]]:
        names, _ = view.directory()
        out: Dict[str, List[WireSession]] = {}
        for key in {k for k, _t in keys}:
            for provider in PROVIDERS:
                for report in store.sessions_reports(provider, key):
                    label = names.get(report.sender, ("", ""))[0]
                    out.setdefault(key, []).extend(
                        WireSession(name=s.name, tmux=None, computer=(s.computer or label)[:64] or None, computer_id=report.sender[:64])
                        for s in report.body.sessions)
        return out

    async def _send(self, kind: str, target: str, provider: str, key: str, path: str, body: Any, *, owner_side: bool) -> int:
        slot = (kind, target, provider, key)
        fingerprint = body.model_dump_json()
        if self._sent.get(slot) == fingerprint or self._retry_at.get(slot, 0.0) > self._clock():
            return 0
        link = self._peer(target)
        if link is None or CAP_LEDGER_STATUS not in link[1]:
            return 0
        if owner_side and self._allows(target) is not True:
            return 0
        try:
            status, _ = await link[0]("POST", path, body.model_dump(mode="json"))
        except (asyncio.TimeoutError, OSError, ValueError, PeerUnreachable, PeerRefused) as exc:
            logger.info("pack_ledger_sync_push_failed", kind=kind, account=key, target=target, error=type(exc).__name__)
            self._retry_at[slot] = self._clock() + RETRY_SECONDS
            return 0
        if status == 200:
            self._sent[slot] = fingerprint
            self._retry_at.pop(slot, None)
            return 1
        logger.info("pack_ledger_sync_push_refused", kind=kind, account=key, target=target, status=status)
        self._retry_at[slot] = self._clock() + RETRY_SECONDS
        return 0
