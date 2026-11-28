
from __future__ import annotations

import hashlib
import os
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Optional

from src.core.computers import mesh
from src.core.computers.link_streams import LocalSocket
from src.core.computers.mesh_link import MeshSession
from src.core.federation import mesh_grants, peer_token
from src.core.federation.peer_client import API, PeerClient, PeerRefused, Route
from src.core.federation.peer_link import LinkDown
from src.core.relay_identity.device_key import b64url as _b64url

TOKEN_PATH = f"{API}/mesh/token"


class MeshTransport:

    def __init__(self, session: MeshSession, self_iid: str, fed_dir: Path) -> None:
        self.session = session
        tag = hashlib.sha256(f"{self_iid}\0{session.peer}".encode()).hexdigest()[:16]
        self.path = str(Path(fed_dir) / f"mesh-out-{tag}-{secrets.token_hex(4)}.sock")
        self._socket: Optional[LocalSocket] = None

    async def establish(self) -> Route:
        if self.session.mux.closed.is_set():
            raise LinkDown("the mesh session is closed")
        if self._socket is None:
            self._socket = LocalSocket(self.session.mux, self.path)
            await self._socket.start()
        return Route("unix", self.path)

    async def close(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            await sock.close()


class MeshPeerClient(PeerClient):

    def __init__(self, route: Route, *, session: MeshSession, self_iid: str, sign: Callable[[bytes], str],
                 trusted: Callable[[str], Any] = mesh.trusted, clock: Callable[[], float] = time.time) -> None:
        super().__init__(route, grant_id="", peer_install_id=session.peer, sign=sign, peer_public_key=None, clock=clock)
        self._session, self._self_iid, self._trusted = session, self_iid, trusted

    def _grant_id(self) -> str:
        lst = self._trusted(self._session.peer)
        entry = lst.entry(self._self_iid) if lst is not None else None
        if entry is None or not self._session.own_sha:
            raise PeerRefused("grant_invalid")
        return mesh_grants.grant_id_for(self._session.peer, self._self_iid, entry.fed_public_key, self._session.own_sha)

    async def _mint(self) -> str:
        gid = self._grant_id()
        ts, nonce = int(self._clock()), os.urandom(16)
        signature = self._sign(peer_token.challenge_message(gid, self._peer, ts, nonce, prefix=peer_token.MESH_CHALLENGE_PREFIX))
        response = await self._send("POST", TOKEN_PATH, None, {"ts": ts, "nonce": _b64url(nonce), "signature": signature})
        if response.status_code in (401, 403):
            raise PeerRefused("grant_invalid")
        if response.status_code != 200:
            raise PeerRefused(f"http_{response.status_code}")
        try:
            data = response.json()
            if not isinstance(data, dict) or data.get("install_id") != self._peer:
                raise PeerRefused("identity_changed")
            token = str(data["token"])
            expires = self._clock() + float(data.get("expires_in", peer_token.TOKEN_TTL_SECONDS))
        except (ValueError, KeyError, TypeError):
            raise PeerRefused("bad_answer") from None
        self._token, self._expires = token, expires
        return token
