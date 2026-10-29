
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from src.core import relay_keychain
from src.core.notifications.destinations.secrets import DestinationSecrets
from src.core.notifications.destinations.service import NotificationService
from src.core.notifications.sync import secrets_sync, wire
from src.core.notifications.sync.manager import EXCHANGE_PATH, SECRETS_PATH, SyncManager
from src.core.notifications.sync.peers import PeerCallError, PeerInfo

PEER_LIMIT = 64 * 1024


class FakeKeychain:

    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}
        self.fail_writes = False

    def read_state(self, service, account):
        v = self.items.get((service, account))
        return (relay_keychain.READ_OK, v) if v else (relay_keychain.READ_ABSENT, None)

    def write(self, service, account, secret):
        if self.fail_writes:
            raise relay_keychain.KeychainWriteError("locked")
        self.items[(service, account)] = secret

    def delete(self, service, account):
        return self.items.pop((service, account), None) is not None


class Cluster:

    def __init__(self) -> None:
        self.computers: Dict[str, "Computer"] = {}
        self.links: Set[Tuple[str, str]] = set()
        self.grants: Set[Tuple[str, str]] = set()
        self.minors: Dict[str, int] = {}
        self.sent: List[Tuple[str, str, str, Dict[str, Any]]] = []
        self.answers: List[Any] = []
        self.secret_answers: List[Any] = []

    def link(self, a: str, b: str) -> None:
        self.links |= {(a, b), (b, a)}


class FakeGateway:

    def __init__(self, cluster: Cluster, me: str) -> None:
        self.cluster, self.me = cluster, me

    async def roster(self) -> List[PeerInfo]:
        return [PeerInfo(f"peer-{o}", o, o, (self.me, o) in self.cluster.links, self.cluster.minors.get(o, 1))
                for o in sorted(self.cluster.computers) if o != self.me and (self.me, o) in self.cluster.links]

    async def post(self, install_id: str, path: str, body: Dict[str, Any]) -> Tuple[int, Any]:
        c = self.cluster
        if (self.me, install_id) not in c.links:
            raise PeerCallError("unreachable")
        c.sent.append((self.me, install_id, path, body))
        assert len(json.dumps(body)) < PEER_LIMIT
        if (self.me, install_id) not in c.grants:
            return 401, None
        callee = c.computers[install_id]
        if path == EXCHANGE_PATH:
            answer = await wire.serve_exchange(callee.service.docs, callee.service.secrets, body, callee.now())
        else:
            assert path == SECRETS_PATH
            answer = await secrets_sync.serve(callee.service.docs, callee.service.secrets, body["dest_ids"])
        (c.secret_answers if path == SECRETS_PATH else c.answers).append(answer)
        assert len(json.dumps(answer)) < PEER_LIMIT
        return 200, answer

    async def set_scope(self, install_id: str, granted: bool) -> None:
        pair = (install_id, self.me)
        (self.cluster.grants.add if granted else self.cluster.grants.discard)(pair)


class Computer:

    def __init__(self, name: str, root: Path, cluster: Cluster) -> None:
        self.name, self.keychain = name, FakeKeychain()
        self.path = root / f"{name}.json"
        self.path.write_text(json.dumps({"agents": {}}))
        self.service = NotificationService(self.path)
        self.service.secrets = DestinationSecrets(backend=self.keychain)
        self.service.destinations._secrets = self.service.secrets
        self.manager = SyncManager(self.service.docs, self.service.secrets, FakeGateway(cluster, name),
                                   clock=self.now)
        cluster.computers[name] = self

    def now(self) -> float:
        return time.time()

    def doc(self) -> dict:
        return self.service.docs.snapshot()

    def sync(self) -> Dict[str, str]:
        return asyncio.run(self.manager.sync_all())
