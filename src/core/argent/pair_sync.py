
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.core import resource_push
from src.core.argent import notices, rollout, settings as settings_module
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.poll_relay import PollSender
from src.core.argent.pair_credential import (CAP_CREDENTIAL, PairRefused, CredentialBody, CredentialSender, PeerFn, PostFn,
                                             receive as receive_credential)
from src.core.argent.settings import ArgentSettings, SettingsRefused
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.resource_push import topics
from src.plugins.sdk import ports

logger = structlog.get_logger()

CAP_SWITCH = "argent.pair.switch"
SWITCH_PATH = "/federation/argent/switch"
REQUEST_PATH = "/federation/argent/credential/request"
MAX_CLOCK_STEP = 1000
MAX_ASK_TRIES, ASK_BACKOFF_SECONDS = 5, 30.0


class SwitchBody(BaseModel):
    """One switch message. The sender is the authenticated peer, never a body field. ``rollout`` is set only when the owner started a rollout there."""

    model_config = ConfigDict(extra="forbid")

    clock: int = Field(ge=0, le=10 ** 18)
    enabled: bool
    server_url: str = Field(default="", max_length=settings_module.MAX_TEXT)
    gateway_url: str = Field(default="", max_length=settings_module.MAX_TEXT)
    rollout: Optional[Literal["on", "off"]] = None


class PairSync:

    def __init__(self, *, store: ArgentStore, tokens: TokenStore, self_id: str, self_label: str, peer: PeerFn,
                 listing: Callable[[], List[Tuple[str, str, str, List[str]]]], candidates: Callable[[], List[str]],
                 allows: Callable[[str], Optional[bool]], approved: Optional[Callable[[str], bool]] = None, config_path: Optional[Path] = None,
                 state_dir: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
        self._store, self._tokens, self._self_id, self._self_label = store, tokens, self_id, self_label
        self._peer, self._listing, self._candidates, self._config_path, self._clock = peer, listing, candidates, config_path, clock
        if state_dir is None:
            from src.config import settings as app_settings  # noqa: PLC0415
            state_dir = Path(app_settings.get_state_dir())
        self._state_dir = state_dir
        self.credentials = CredentialSender(store=store, tokens=tokens, peer=peer, candidates=candidates, allows=allows,
                                            approved=approved, read_settings=lambda: settings_module.read(config_path), clock=clock,
                                            label=self._label_of)
        self._allows = allows
        self.poll = PollSender(self.send_links, clock)
        self.switch_sent: Dict[str, Dict[str, Any]] = {}
        self._asked: Dict[str, Tuple[float, int, float, bool]] = {}
        self.waiting_on_owner = ""
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = asyncio.Lock()
        self._tasks: set = set()


    def send_links(self) -> List[Tuple[str, PostFn, List[str]]]:
        out = []
        for iid in self._candidates():
            link = self._peer(iid)
            if link is not None:
                out.append((iid, link[0], link[1]))
        return out

    def is_listed(self, sender: str) -> bool:
        return sender != self._self_id and sender in {row[0] for row in self._listing()}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on_settings_changed(self, before: ArgentSettings, after: ArgentSettings) -> None:
        if (before.enabled, before.server_url, before.gateway_url) == (after.enabled, after.server_url, after.gateway_url) or self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._spawn, self.export(None, bump=True))

    def on_connect(self, install_id: str) -> None:
        if install_id == self.waiting_on_owner:
            self._asked.pop(install_id, None)
            self._spawn(self.ask_owner())
        self._spawn(self._catch_up(install_id))

    def _label_of(self, install_id: str) -> str:
        return next((label for iid, label, _state, _caps in self._listing() if iid == install_id), install_id)

    async def credentials_pass(self) -> None:
        await self._push_credentials(None)

    async def credentials_requested(self, sender: str) -> None:
        if sender not in self._candidates():
            return
        await self._push_credentials(sender, force=True)

    def copy_unauthorized(self) -> None:
        self._spawn(self.ask_owner())

    async def ask_owner(self) -> str:
        source = await asyncio.to_thread(self._store.login_source)
        login = await asyncio.to_thread(self._store.get_login)
        if not source.startswith("relay:") or login is None:
            return "not_a_copy"
        owner, held = source[len("relay:"):], float(login["expires_at"])
        seen = self._asked.get(owner)
        if seen is not None and seen[0] == held:
            if seen[3]:
                return "already_asked"
            if seen[1] >= MAX_ASK_TRIES or self._clock() < seen[2]:
                return "waiting_on_owner"
        fails = seen[1] if seen is not None and seen[0] == held else 0
        link = self._peer(owner)
        status = 0
        if link is not None and CAP_CREDENTIAL in link[1]:
            try:
                status, _ = await link[0]("POST", REQUEST_PATH, {})
            except (asyncio.TimeoutError, OSError, ValueError, PeerUnreachable, PeerRefused) as exc:
                logger.info("argent_pair_credential_ask_failed", target=owner, error=type(exc).__name__)
        self._asked[owner] = (held, 0, 0.0, True) if status == 200 else (held, fails + 1, self._clock() + ASK_BACKOFF_SECONDS * 2 ** fails, False)
        self.waiting_on_owner = "" if status == 200 else owner
        resource_push.notify(topics.ARGENT_PAIR)
        resource_push.notify(topics.ARGENT_STATUS)
        return "asked" if status == 200 else "waiting_on_owner"

    def login_changed(self) -> None:
        self._spawn(self._push_credentials(None))

    def _spawn(self, coro: Awaitable[Any]) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)  # type: ignore[arg-type]
        except RuntimeError:
            coro.close()  # type: ignore[attr-defined]
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _catch_up(self, install_id: str) -> None:
        await self.export(install_id, bump=False)
        await self._push_credentials(install_id)

    async def _push_credentials(self, only: Optional[str], force: bool = False) -> None:
        try:
            if await self.credentials.push(only, force):
                resource_push.notify(topics.ARGENT_PAIR)
        except Exception as exc:  # noqa: BLE001
            logger.warning("argent_pair_credential_pass_failed", error=type(exc).__name__)

    async def export(self, only: Optional[str], *, bump: bool = False, rollout_direction: Optional[str] = None) -> List[str]:
        async with self._lock:
            cur = await asyncio.to_thread(settings_module.read, self._config_path)
            clock, origin = await asyncio.to_thread(self._store.pair_state)
            if bump:
                clock = max(clock + 1, int(self._clock() * 1000))
                await asyncio.to_thread(self._store.set_pair_state, clock, self._self_id)
            elif origin != self._self_id or clock == 0:
                return []
            body = SwitchBody(clock=clock, enabled=cur.enabled, server_url=cur.server_url, gateway_url=cur.gateway_url, rollout=rollout_direction)
            took: List[str] = []
            for iid in ([only] if only else self._candidates()):
                link = self._peer(iid)
                if link is None or CAP_SWITCH not in link[1]:
                    continue
                outcome = await self._post(link[0], iid, body.model_dump(mode="json"))
                self.switch_sent[iid] = {"state": outcome, "clock": clock}
                if outcome == "applied":
                    took.append(iid)
            resource_push.notify(topics.ARGENT_PAIR)
            return took

    async def _post(self, post: PostFn, iid: str, body: dict) -> str:
        try:
            status, _ = await post("POST", SWITCH_PATH, body)
        except (asyncio.TimeoutError, OSError, ValueError, PeerUnreachable, PeerRefused) as exc:
            logger.info("argent_pair_switch_push_failed", target=iid, error=type(exc).__name__)
            return "failed"
        logger.info("argent_pair_switch_pushed", target=iid, status=status)
        return "applied" if status == 200 else ("refused" if status in (401, 403, 409, 422) else "failed")


    def _apply_switch(self, sender: str, body: SwitchBody) -> Tuple[bool, bool]:
        if sender == self._self_id or sender not in {row[0] for row in self._listing()}:
            raise PairRefused("not_listed", 403)
        try:
            server = settings_module.clean_url(body.server_url, "server_url")
            gateway = settings_module.clean_url(body.gateway_url, "gateway_url")
        except SettingsRefused:
            raise PairRefused("bad_address") from None
        held = int(self._store.pair_state()[0])
        if body.clock > max(held, int(self._clock() * 1000)) + MAX_CLOCK_STEP:
            logger.warning("argent_pair_switch_clock_refused", sender=sender)
            return False, settings_module.read(self._config_path).enabled
        if (body.clock, sender) < tuple(self._store.pair_state()):
            return False, settings_module.read(self._config_path).enabled
        want = body.enabled and bool(server)
        cur = settings_module.read(self._config_path)
        differs = (server, gateway) != (cur.server_url, cur.gateway_url)
        may_fill = not cur.server_url and not cur.gateway_url and self._store.login_source().startswith("relay:")
        if differs and not may_fill:
            if want:
                raise PairRefused("address_locked", 409)
            server, gateway = cur.server_url, cur.gateway_url
        enabled = want and bool(server and gateway) and self.logged_in()
        if (cur.enabled, cur.server_url, cur.gateway_url) != (enabled, server, gateway):
            settings_module.update(lambda block: block.update(enabled=enabled, serverUrl=server, gatewayUrl=gateway), self._config_path, imported=True)
        self._store.set_pair_state(body.clock, sender)
        return True, want if want and not enabled and not self.logged_in() else enabled

    async def receive_switch(self, sender: str, body: SwitchBody, app_state: Any) -> Dict[str, Any]:
        applied, enabled = await asyncio.to_thread(self._apply_switch, sender, body)
        resource_push.notify(topics.ARGENT_PAIR)
        if applied:
            await self._after_import(enabled, body.rollout, app_state)
        return {"applied": applied}

    def logged_in(self) -> bool:
        login = self._store.get_login()
        return login is not None and float(login["expires_at"]) > self._clock() and not self._store.login_expired()

    async def _after_import(self, enabled: bool, rollout_direction: Optional[str], app_state: Any) -> None:
        have_login = await asyncio.to_thread(self.logged_in)
        if enabled and not have_login:
            notices.pair_login(self._self_label)
        elif have_login:
            notices.pair_login_resolved()
        if rollout_direction is None or ports.get(PORT_NAME) is None or (enabled and not have_login):
            return
        rollout.bind(app_state)
        await rollout.begin("on" if enabled else "off")
        rollout.ensure_running()

    async def receive_credential(self, sender: str, body: CredentialBody) -> int:
        if sender == self._self_id or sender not in {row[0] for row in self._listing()}:
            raise PairRefused("not_listed", 403)
        expiry = await asyncio.to_thread(receive_credential, sender, body, store=self._store, tokens=self._tokens,
                                         state_dir=self._state_dir, config_path=self._config_path, now=self._clock())
        from src.core.argent import device_login  # noqa: PLC0415

        device_login.poke_after_login()
        notices.pair_login_resolved()
        self.waiting_on_owner = ""
        resource_push.notify(topics.ARGENT_PAIR)
        return expiry


    def view(self) -> Dict[str, Any]:
        clock, origin = self._store.pair_state()
        rows = [{"install_id": iid, "label": label, "link": state, "can_sync_switch": CAP_SWITCH in caps,
                 "can_relay_credential": CAP_CREDENTIAL in caps, "accepts_credentials": self._allows(iid),
                 "switch": self.switch_sent.get(iid), "credential": self.credentials.sent.get(iid)}
                for iid, label, state, caps in self._listing()]
        return {"clock": clock, "origin": origin, "login_source": self._store.login_source(), "waiting_on_owner": self.waiting_on_owner, "computers": rows}


PAIR: Optional[PairSync] = None


def get() -> Optional[PairSync]:
    return PAIR


def copy_unauthorized() -> None:
    if PAIR is not None:
        PAIR.copy_unauthorized()


def login_changed() -> None:
    if PAIR is not None:
        PAIR.login_changed()


async def rollout_started() -> None:
    if PAIR is not None:
        await PAIR.export(None, bump=True, rollout_direction="on" if (await asyncio.to_thread(settings_module.read)).enabled else "off")


def start(links_getter: Callable[[], Any]) -> PairSync:
    global PAIR
    from src.core.computers import direction  # noqa: PLC0415
    from src.core.argent.runtime import get_runtime
    from src.core.pack.machines import runtime as machines_runtime
    from src.core.pack.machines.exchange import post_via

    wired = machines_runtime.wiring()
    if wired is None:
        raise RuntimeError("the Pack machine layer must start before the argent pair sync")

    def peer(install_id: str):
        links = links_getter()
        client = links.client(install_id) if links is not None else None
        return None if client is None else (post_via(client, 10.0), links.capabilities(install_id))

    def listing() -> List[Tuple[str, str, str, List[str]]]:
        return [(p.install_id, p.label, str(p.link_state), list(p.capabilities)) for p in wired.peers() if p.install_id != wired.runtime.install_id]

    def candidates() -> List[str]:
        return [row[0] for row in listing() if not direction.contained(row[0])]

    from src.api.peer_auth import open_db  # noqa: PLC0415
    from src.core.pack.relay import approval  # noqa: PLC0415

    runtime = get_runtime()
    PAIR = PairSync(store=runtime.store, tokens=runtime.tokens, self_id=wired.runtime.install_id, self_label=wired.runtime.label, peer=peer,
                    listing=listing, candidates=candidates, allows=lambda iid: machines_runtime.peer_restriction(iid, "may_receive_credentials"),
                    approved=approval.reader(open_db))
    PAIR.bind_loop(asyncio.get_running_loop())
    settings_module.add_listener(PAIR.on_settings_changed)
    links = links_getter()
    if links is not None:
        links.add_connect_listener(PAIR.on_connect)
    return PAIR
