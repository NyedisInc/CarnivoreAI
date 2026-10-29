
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Optional

from src.api import peer_auth, projects_service
from src.config import settings
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.account_switch import session_pin
from src.core.account_switch.launch_env import _config_path
from src.core.federation import peer_hosts, peer_links
from src.core.pack.machines import config_state
from src.core.pack.move import account
from src.core.pack.migrate.plan import Request, SourceEnv
from src.core.pack.migrate.receive import TargetEnv
from src.core.pack.transport import blobs

LINK_TIMEOUT_SECONDS = 120.0


def _install_id() -> str:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        return str(get_meta(conn, META_INSTALL_ID))


def _labels() -> dict:
    with closing(peer_auth.open_db()) as conn:
        return {p.peer_install_id: str(p.label) for p in peer_hosts.list_peers(conn)}


def source_env() -> SourceEnv:
    state = Path(settings.get_state_dir())
    labels = _labels()
    return SourceEnv(open_db=lambda: projects_service.open_db_or_503(settings), state_dir=str(state), install_id=_install_id(),
                     outbox=str(state / "pack" / "outbox"), label_of=lambda iid: labels.get(iid, iid),
                     account_of=lambda uuid: account.session_account_key(_config_path(), uuid),
                     profile_of=lambda uuid: account.session_profile_dir(_config_path(), uuid))


def target_env() -> TargetEnv:
    state = Path(settings.get_state_dir())
    return TargetEnv(open_db=lambda: projects_service.open_db_or_503(settings), state_dir=str(state), inbox=blobs.Inbox(state / "pack" / "inbox"),
                     install_id=_install_id(), restrictions=config_state.default().restrictions,
                     projects_dir=str(Path(settings.default_working_dir).expanduser()),
                     carry_account=lambda uuid, key: session_pin.carry(_config_path(), uuid, key))


def link_request(install_id: str, timeout: float = LINK_TIMEOUT_SECONDS) -> Optional[Request]:
    links = peer_links.LINKS
    client = links.client(install_id) if links is not None else None
    return blobs.request_via(client, timeout) if client is not None else None
