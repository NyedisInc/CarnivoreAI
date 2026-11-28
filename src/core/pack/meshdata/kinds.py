
from __future__ import annotations

from typing import Any, Callable, Dict, NamedTuple, Optional

from src.core.pack.meshdata import notify_kind, ops_kind, panel_kind, status, telemetry_kind, withhold, workspace_kind

MAX_VALUE_BYTES = 4096
MAX_KEY_LEN = 128


class KindRule(NamedTuple):

    cap: int
    key_is_origin: bool
    validate: Callable[[Any], bool]
    origin_cap: Optional[int] = None
    key_ok: Optional[Callable[[str, Any], bool]] = None
    origin_ok: Optional[Callable[[Any, str], bool]] = None
    serve_ok: Optional[Callable[[Any, str], bool]] = None
    tomb: Optional[Callable[[Any], bool]] = None
    tomb_ttl_ms: int = 0
    privileged: Optional[Callable[[Any, str], bool]] = None
    reserve: int = 0
    tomb_value: Any = None
    local_ok: Optional[Callable[[str, Optional[str]], bool]] = None
    forget_ok: Optional[Callable[[str], bool]] = None


KINDS: Dict[str, KindRule] = {
    status.KIND: KindRule(cap=64, key_is_origin=True, validate=status.valid),
    panel_kind.KIND: KindRule(cap=panel_kind.CAP, key_is_origin=False, validate=panel_kind.valid_shape, origin_cap=panel_kind.ORIGIN_CAP,
                              key_ok=panel_kind.valid, origin_ok=panel_kind.origin_ok, serve_ok=panel_kind.serve_ok, tomb=panel_kind.is_tomb,
                              tomb_ttl_ms=panel_kind.TOMB_TTL_MS, privileged=panel_kind.privileged, reserve=panel_kind.RESERVE, tomb_value={"pos": None}),
    ops_kind.KIND: KindRule(cap=len(ops_kind.KEYS), key_is_origin=False, validate=ops_kind.valid_shape, key_ok=ops_kind.valid,
                            origin_ok=ops_kind.origin_ok, serve_ok=ops_kind.serve_ok),
    notify_kind.KIND: KindRule(cap=notify_kind.CAP, key_is_origin=False, validate=notify_kind.valid_shape, origin_cap=notify_kind.ORIGIN_CAP,
                               key_ok=notify_kind.valid, origin_ok=notify_kind.origin_ok, serve_ok=notify_kind.serve_ok, tomb=notify_kind.is_tomb,
                               tomb_ttl_ms=notify_kind.TOMB_TTL_MS, privileged=notify_kind.privileged, reserve=notify_kind.RESERVE,
                               local_ok=notify_kind.local_ok, forget_ok=notify_kind.forget_ok),
    withhold.KIND: KindRule(cap=64, key_is_origin=True, validate=withhold.valid),
    workspace_kind.KIND: KindRule(
        cap=workspace_kind.CAP,
        key_is_origin=False,
        validate=workspace_kind.valid_shape,
        origin_cap=workspace_kind.ORIGIN_CAP,
        key_ok=workspace_kind.valid,
        origin_ok=workspace_kind.origin_ok,
        serve_ok=workspace_kind.serve_ok,
        tomb=workspace_kind.is_tomb,
        tomb_ttl_ms=workspace_kind.TOMB_TTL_MS,
        privileged=workspace_kind.privileged,
        reserve=workspace_kind.RESERVE,
        tomb_value=None,
    ),
    telemetry_kind.KIND: KindRule(
        cap=telemetry_kind.CAP,
        key_is_origin=True,
        validate=telemetry_kind.valid,
        origin_ok=telemetry_kind.origin_ok,
        serve_ok=telemetry_kind.serve_ok,
    ),
}
