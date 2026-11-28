
from __future__ import annotations

import re
from typing import Dict, FrozenSet, List, Optional, Tuple

from starlette.routing import compile_path

from src.core.federation import peer_forward

MESH_LINK = "mesh.link"
MESH_SESSIONS = "mesh.sessions"
MESH_DATA = "mesh.data"
MESH_TIGHTEN = "mesh.tighten"
MESH_JOBS = "mesh.jobs"
MESH_LOGINS = "mesh.logins"
ALL_POWERS = frozenset({MESH_LINK, MESH_SESSIONS, MESH_DATA, MESH_TIGHTEN, MESH_JOBS, MESH_LOGINS})
OPEN_POWERS = frozenset({MESH_LINK, MESH_LOGINS, MESH_JOBS, MESH_DATA})
REFUSED = "refused"

POWER_SCOPES: Dict[str, FrozenSet[str]] = {
    MESH_LINK: frozenset({"sessions"}),
    MESH_SESSIONS: frozenset({"sessions"}),
    MESH_DATA: frozenset({"machine"}),
    MESH_TIGHTEN: frozenset({"machine"}),
    MESH_JOBS: frozenset({"replica"}),
    MESH_LOGINS: frozenset({"credentials", "machine"}),
}

_P = "/api/v1/"
_F = _P + "federation/"
_PACK = _F + "pack/"

_ALLOWED: Dict[str, List[Tuple[str, str]]] = {
    MESH_LINK: [("GET", _F + "hello")],
    MESH_SESSIONS: [
        ("POST", _P + "crosstalk/peer-deliver"), ("POST", _P + "crosstalk/peer-control"), ("POST", _P + "crosstalk/peer-spawn"),
        ("GET", _P + "sessions/list"), ("GET", _P + "sessions/asleep"), ("GET", _P + "sessions/list-and-asleep"),
        ("POST", _P + "warroom/screens"), ("GET", _P + "projects/history"), ("GET", _P + "provider-ledger/summary"),
        ("GET", _P + "launchers/summary"), ("GET", _P + "filesystem/project-folders"), ("GET", _P + "deepsearch/peer-search"),
        ("GET", _P + "deepsearch/peer-context"), ("GET", _P + "approvals"), ("GET", _P + "scheduled-tasks"),
        ("POST", _P + "sessions/hydrate"),
        ("WS", "/ws/terminal"), ("WS", "/ws/events"),
        *[(r.method, _P.rstrip("/") + r.path) for r in peer_forward.TABLE if r.mode in (peer_forward.FORWARD, peer_forward.SELF)],
    ],
    MESH_DATA: [("POST", _PACK + "mesh/sync"), ("GET", _PACK + "rollup")],
    MESH_TIGHTEN: [("PUT", _PACK + "restrictions/tighten")],
    MESH_JOBS: [
        ("POST", _PACK + "replica"), ("DELETE", _PACK + "replica/{project_uid}"),
        ("PUT", _PACK + "blobs/{blob_id}"), ("POST", _PACK + "blobs/{blob_id}/seal"), ("GET", _PACK + "blobs/{blob_id}"),
        ("POST", _PACK + "bundle/apply"),
        *[("POST", _PACK + "jobs/" + step) for step in ("admit", "start", "status", "collect", "stop", "release", "reply", "forget-copy", "install", "prewarm", "look")],
        ("GET", _PACK + "jobs/install/{install_id}"),
        ("GET", _PACK + "jobs/activity"),
    ],
    MESH_LOGINS: [
        ("POST", _PACK + "credentials"), ("POST", _PACK + "credentials/codex"), ("DELETE", _PACK + "credentials/{account_key}"),
        ("DELETE", _PACK + "credentials/codex/{account_key}"),
        ("POST", _F + "argent/credential"), ("POST", _F + "argent/credential/request"),
    ],
}

_REFUSED: Dict[str, List[Tuple[str, str]]] = {
    "star_only": [("POST", _F + "link"), ("POST", _F + "key/announce"), ("DELETE", _F + "grants/self"), ("POST", _F + "link-cert"),
                  ("POST", _PACK + "global/panel-change"),
                  ("POST", _PACK + "exchange"),
                  ("POST", _F + "notify-sync/exchange"), ("POST", _F + "notify-sync/secrets")],
    "stats_star": [("GET", _P + "stats/feed/local")],
    "not_data": [("PUT", _PACK + "labels"), ("POST", _PACK + "rescan")],
    "alpha_or_self": [
        ("PUT", _PACK + "reserve"), ("GET", _F + "app-update"), ("PUT", _F + "app-update/auto-update"), ("POST", _F + "app-update/check"),
        ("POST", _F + "app-update/install"), ("POST", _PACK + "refresh"),
    ],
    "logins": [
        ("POST", _F + "argent/poll"), ("POST", _F + "argent/switch"),
        ("POST", _PACK + "gh-login"), ("POST", _PACK + "ledger-status"), ("POST", _PACK + "ledger-sessions"),
    ],
    "alpha_only": [
        ("POST", _PACK + "skills/offer"), ("POST", _PACK + "skills/apply"), ("GET", _PACK + "skills/inventory"),
        ("PUT", _PACK + "skills/blobs/{blob_id}"), ("POST", _PACK + "skills/blobs/{blob_id}/seal"), ("GET", _PACK + "skills/blobs/{blob_id}"),
        ("POST", _PACK + "skills/export"), ("GET", _PACK + "skills/export/{blob_id}"), ("POST", _PACK + "skills/export/{blob_id}/done"),
        ("PUT", _PACK + "global/blobs/{blob_id}"), ("POST", _PACK + "global/blobs/{blob_id}/seal"), ("GET", _PACK + "global/blobs/{blob_id}"),
        ("POST", _PACK + "global/apply"), ("POST", _PACK + "global/panel"),
    ],
    "not_jobs": [
        ("POST", _F + "swarm/body"), ("POST", _F + "swarm/body/{home_agent_id}/sleep"), ("POST", _F + "swarm/proxy"),
        ("POST", _F + "swarm/memory/writeback"), ("POST", _PACK + "board/{verb}"), ("POST", _PACK + "sessions/create"),
    ],
    "not_a_power": [
        *[("POST", _PACK + "migrate/" + step) for step in ("prepare", "receive", "verify", "flip", "abort", "back")],
        ("POST", _PACK + "session/receive"), ("POST", _PACK + "carry/check"), ("POST", _PACK + "carry/apply"),
    ],
}

ROUTES: Dict[Tuple[str, str], str] = {}
REFUSED_WHY: Dict[Tuple[str, str], str] = {}
for _power, _rows in _ALLOWED.items():
    for _row in _rows:
        ROUTES[_row] = _power
for _why, _rows in _REFUSED.items():
    for _row in _rows:
        ROUTES[_row] = REFUSED
        REFUSED_WHY[_row] = _why

_COMPILED: Tuple[Tuple[str, "re.Pattern[str]", Tuple[str, str]], ...] = tuple(
    (method, compile_path(path)[0], (method, path)) for method, path in ROUTES)


def power_for(method: str, path: str) -> Optional[str]:
    found = {ROUTES[row] for m, pattern, row in _COMPILED if m == method and pattern.match(path)}
    if len(found) != 1:
        return None
    (power,) = found
    return None if power == REFUSED else power
