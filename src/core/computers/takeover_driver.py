
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from typing import Any, Callable, Dict, Optional

import structlog

from src.core.computers import alpha_rows
from src.core.computers.takeover_walk import LinkHistory, RelayConnect, Walker
from src.core.pack.machines import interim_policy
from src.core.pack.reconnect import config as reconnect_config
from src.core.resource_push import topics

log = structlog.get_logger(__name__)


class TakeoverDriver:

    def __init__(self, rt: Any, *, clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time,
                 relay_connect: Optional[RelayConnect] = None) -> None:
        self._rt, self._clock, self._wall = rt, clock, wall_clock
        self._last_ticks: Optional[tuple] = None
        self.history = LinkHistory()
        self._walker: Optional[Walker] = None
        self._relay_connect = relay_connect
        self._master = ""
        self._last_round = -1e9
        self._bound = False
        self._answer_key: tuple = ()

    def _custody(self) -> Any:
        return self._rt._roster._wired().runtime.custody

    def _linked(self) -> list:
        rt = self._rt
        live = list(rt.listener.connected()) if rt.listener is not None else []
        main = rt._main_row()
        if main is not None and rt._main_linked():
            live.append(main.peer_install_id)
        return live

    def _bind(self, custody: Any) -> None:
        rt = self._rt
        custody.takeover_on = lambda: reconnect_config.takeover_on(rt._config_path)
        custody.standing = lambda: self._walker.standing(self._master, self.history) if self._walker is not None else None
        custody.on_alpha_change = self._alpha_changed
        self._walker = Walker(identity=rt.identity, self_id=rt.iid, clock=self._clock, roster=custody.roster,
                              relay_connect=self._relay_connect, linked=self._linked)
        self._bound = True

    async def rotation_paused(self) -> bool:
        try:
            return await asyncio.to_thread(self._custody().interim)
        except (RuntimeError, OSError, ValueError):
            return False

    async def answer_walks(self, ml: Any) -> bool:
        rt = self._rt
        held = rt._roster_cache[0] if rt._roster_cache is not None else None
        if held is None or rt.iid is None or held.entry(rt.iid) is None or not reconnect_config.takeover_on(rt._config_path):
            return False
        follow = rt._follow_pins("")
        if not follow:
            return False
        if ml.state != "listening" and not await ml.reserve(rt.link_port):
            return False
        key = tuple(sorted(c.cert_sha256 for c in follow))
        if key != self._answer_key:
            await ml.set_pins([], follow)
            self._answer_key = key
        return True

    def _alpha_changed(self, master: str, case: str) -> None:
        loop = self._rt._loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.after_alpha_change(master, case)))

    async def after_alpha_change(self, master: str, case: str) -> None:
        rt = self._rt
        try:
            roster = await asyncio.to_thread(rt._roster.roster)
            if roster is None or rt.identity is None:
                return

            def write() -> int:
                with closing(rt._open_db()) as conn:
                    return alpha_rows.rewrite_rows(conn, own_iid=rt.iid, own_link_fid=rt.identity.cert.link_fid,
                                                   own_link_port=rt.link_port, roster=roster, new_alpha=master)

            await asyncio.to_thread(write)
            await rt.after_roster_change()
            await rt.repin(force=True)
            rt.notify(topics.COMPUTERS)
            rt.notify(topics.PACK_MACHINES)
            log.info("takeover_alpha_changed", case=case, master=master[:8], this_computer_is_alpha=master == rt.iid)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            log.warning("takeover_after_change_failed", error_type=type(exc).__name__)

    async def tick(self) -> str:
        try:
            return await self._tick()
        except asyncio.CancelledError:
            raise
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            log.warning("takeover_tick_failed", error_type=type(exc).__name__)
            return ""

    async def _tick(self) -> str:
        rt = self._rt
        if rt._roster is None or rt.identity is None or rt.iid is None:
            return ""
        custody = self._custody()
        if not self._bound:
            self._bind(custody)
        now = self._clock()
        ticks, self._last_ticks = self._last_ticks, (now, self._wall())
        if ticks is not None and self._walker is not None and (self._last_ticks[1] - ticks[1]) - (now - ticks[0]) > interim_policy.GAP_SECONDS:
            self._walker.reset()
        self.history.observe(self._linked(), now)
        if not custody.takeover_on() or now - self._last_round < interim_policy.ROUND_SECONDS:
            return ""
        roster = await asyncio.to_thread(custody.roster)
        if roster is None or len(roster.computers) < 2 or roster.entry(rt.iid) is None:
            return ""
        self._master = (await asyncio.to_thread(custody.settings)).master_install_id
        self._last_round = now
        assert self._walker is not None
        hellos = await self._walker.round()
        for iid, hello in hellos.items():
            await asyncio.to_thread(rt._roster.merge_follow, hello, iid)
        roster = await asyncio.to_thread(custody.roster)
        master = (await asyncio.to_thread(custody.settings)).master_install_id
        if roster is None:
            return ""
        self._master = master
        now = self._clock()
        state = await asyncio.to_thread(custody.home_state)
        current = custody.rival_alpha() or master
        if interim_policy.reclaim_due(self_id=rt.iid, roster=roster, state=state, master=current, linked_seconds=max(self.history.linked_for(current, now), self._walker.reached_seconds(current))):
            return "reclaimed" if await asyncio.to_thread(custody.reclaim_home) else ""
        if master == rt.iid:
            return ""
        ok, why = interim_policy.may_claim(roster=roster, self_id=rt.iid, alpha=master, alpha_span=self._walker.alpha_span(master),
                                           walk=self._walker.walk, now=now)
        if ok:
            log.info("takeover_claiming", master=master[:8])
            return "claimed" if await asyncio.to_thread(custody.claim) else ""
        log.debug("takeover_not_claiming", reason=why)
        return ""
