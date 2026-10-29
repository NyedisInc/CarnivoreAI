
from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Callable, Optional

from src.core.federation import peer_prove
from src.core.federation.peer_client import PeerClient, PeerRefused, Route
from src.core.federation.peer_link import LinkDown
from src.core.hosts import ssh_forward
from src.core.hosts.ssh_exec import CONTROL_PATH_MAX, SshDestination, validate_control_path
from src.core.hosts.ssh_forward import ForwardError
from src.core.hosts.ssh_master import (SshMaster, SshTransportError, default_instance_tag,
                                       ensure_control_dir)

BACK_UNIX, BACK_TCP = "unix", "tcp"

_NAME_MAX = 13


def socket_dir_for(preferred: Path) -> Path:
    if len(str(preferred)) + 1 + _NAME_MAX <= CONTROL_PATH_MAX:
        return preferred
    return Path(f"/tmp/cc-cm-{os.getuid()}")


def link_socket_paths(directory: Path, host_key: str, tag: str) -> tuple:
    stem = hashlib.sha256(f"{host_key}:{tag}".encode()).hexdigest()[:10]
    return tuple(validate_control_path(f"{directory}/{stem}-{kind}") for kind in ("0", "o", "p"))


class InitiatorTransport:

    settle = None

    def __init__(self, *, host_key: str, dest: SshDestination, remote_port: int, listener_path: str,
                 make_client: Callable[[Route], PeerClient], peer_grant_id: str = "", back_kind: str = BACK_UNIX,
                 control_dir: Optional[Path] = None, instance_tag: Optional[str] = None,
                 master: Optional[SshMaster] = None) -> None:
        self.dest, self.remote_port, self.back_kind = dest, remote_port, back_kind
        self._listener, self._make_client, self.peer_grant_id = listener_path, make_client, peer_grant_id
        directory = ensure_control_dir(socket_dir_for(control_dir or Path.home() / ".carnivore" / "cm"))
        tag = instance_tag or default_instance_tag()
        control, self.out_path, self.pair_path = link_socket_paths(directory, host_key, tag)
        self._body: Optional[dict] = None
        self._route_id = ""
        self.master = master or SshMaster(host_key, dest, control)

    async def up_local(self) -> Route:
        status = await self.master.connect()
        if not self.master.is_up:
            raise LinkDown(f"ssh {status.state}: {status.failure or ''}")
        try:
            return Route("unix", await self.master.forward_local(self.out_path, "127.0.0.1", self.remote_port))
        except (ForwardError, SshTransportError) as exc:
            raise LinkDown(str(exc)) from None

    async def establish(self) -> Route:
        self._drop_route_id()
        route = await self.up_local()
        if not self.peer_grant_id:
            raise LinkDown("no grant to name the back route with")
        try:
            if self.back_kind == BACK_TCP:
                port = await self.master.forward_remote(None, self._listener)
                self._route_id = secrets.token_hex(16)
                peer_prove.LIVE_ROUTES.add(self._route_id)
                body = {"kind": "tcp", "port": port, "route_id": self._route_id}
            else:
                home = await ssh_forward.remote_home(self.dest, self.master.control_path)
                fed = f"{home}/.carnivore/fed"
                await ssh_forward.ensure_remote_dir(self.dest, self.master.control_path, fed)
                path = f"{fed}/in-{self.peer_grant_id}-{secrets.token_hex(4)}.sock"
                body = {"kind": "unix", "path": await self.master.forward_remote(path, self._listener)}
        except (ForwardError, SshTransportError) as exc:
            raise LinkDown(str(exc)) from None
        self._body = body
        await self.renew(self._make_client(route))
        return route

    async def renew(self, client: PeerClient) -> None:
        response = await client.request("POST", "/federation/link", json=self._body)
        if response.status_code != 200:
            raise PeerRefused(f"http_{response.status_code}")

    def _drop_route_id(self) -> None:
        peer_prove.LIVE_ROUTES.discard(self._route_id)
        self._route_id = ""

    async def close(self) -> None:
        self._drop_route_id()
        await self.master.disconnect()
