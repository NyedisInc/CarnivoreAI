
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.plugins.host import egress_log, fetch_proxy, secret_store
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime.dispatch import HostDispatcher, PluginContext

_TEMPLATE_VAR = re.compile(r"\{\{([A-Za-z0-9_.-]{1,64})\}\}")


def render_template(template: str, context: Mapping[str, Any]) -> str:
    if not template:
        return ""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        val = context.get(key, "")
        if isinstance(val, (dict, list, bool, int, float)):
            return json.dumps(val)
        return str(val)

    return _TEMPLATE_VAR.sub(_replace, template)


class Tier0ChannelRegistry:

    def __init__(self) -> None:
        self._channels: Dict[str, Tuple[SidecarDefinition, Dict[str, Dict[str, Any]]]] = {}

    def register(self, defn: SidecarDefinition) -> None:
        channels = getattr(defn.manifest, "channels", None) or {}
        if channels:
            self._channels[defn.id] = (defn, {k: dict(v) for k, v in channels.items()})
        else:
            self._channels.pop(defn.id, None)

    def unregister(self, plugin_id: str) -> None:
        self._channels.pop(plugin_id, None)

    def get(self, plugin_id: str, channel: str) -> Optional[Tuple[SidecarDefinition, Dict[str, Any]]]:
        entry = self._channels.get(plugin_id)
        if entry is None:
            return None
        defn, channels = entry
        cfg = channels.get(channel)
        return (defn, dict(cfg)) if cfg is not None else None

    def list_for(self, plugin_id: str) -> Dict[str, Dict[str, Any]]:
        entry = self._channels.get(plugin_id)
        return dict(entry[1]) if entry is not None else {}

    async def send(
        self,
        plugin_id: str,
        channel: str,
        context: Mapping[str, Any],
        *,
        host: Any,
        state_dir: Path,
        limiter: fetch_proxy.RateLimiter,
    ) -> fetch_proxy.FetchResponse:
        found = self.get(plugin_id, channel)
        if found is None:
            raise KeyError(f"channel {plugin_id}:{channel} is not registered")
        defn, cfg = found
        body_text = render_template(str(cfg.get("body_template", "")), context)
        body_bytes = body_text.encode("utf-8") if body_text else None
        fetch_for = getattr(host, "fetch_for", None)
        proxy = fetch_for(plugin_id) if callable(fetch_for) else None
        if proxy is None:
            proxy = fetch_proxy.PluginFetch(
                defn.manifest,
                host.install_key(plugin_id),
                lambda: host._live_grants(defn.manifest),
                secret_store.SecretStore(state_dir),
                egress_log.EgressLog(state_dir),
                limiter,
            )
        return await proxy.fetch(
            str(cfg.get("method", "POST")),
            str(cfg["url"]),
            headers=dict(cfg.get("headers") or {}),
            body=body_bytes,
        )


def find_macro(manifest: Any, macro_id: str) -> Optional[Dict[str, Any]]:
    macros = getattr(manifest, "macros", None)
    if isinstance(macros, Mapping) and macro_id in macros:
        return dict(macros[macro_id])
    ui_meta = getattr(manifest, "ui_meta", None)
    if isinstance(ui_meta, Mapping):
        for cmd in ui_meta.get("commands") or ():
            if isinstance(cmd, Mapping) and cmd.get("id") == macro_id and isinstance(cmd.get("steps"), list):
                return dict(cmd)
    return None


async def execute_macro(
    defn: SidecarDefinition,
    macro_id: str,
    *,
    dispatcher: HostDispatcher,
    ctx: PluginContext,
    owner_token: Optional[str] = None,
    session_ref: Optional[str] = None,
) -> List[Dict[str, Any]]:
    macro = find_macro(defn.manifest, macro_id)
    if macro is None:
        raise KeyError(f"macro {defn.id}:{macro_id} not found")
    tctx = {"session_ref": session_ref or ""}
    results: List[Dict[str, Any]] = []
    for step in macro.get("steps", ()):
        action = str(step.get("action") or step.get("method") or "")
        params = {
            k: (render_template(v, tctx) if isinstance(v, str) else v)
            for k, v in (step.get("params") or {}).items()
        }
        if action == "sessions.message":
            if owner_token and "owner_token" not in params:
                params["owner_token"] = owner_token
            if session_ref and not params.get("ref"):
                params["ref"] = session_ref
        elif action == "notify.toast" and session_ref and not params.get("ref"):
            params["ref"] = session_ref
        res = await dispatcher.handle(ctx, action, params)
        results.append({"action": action, "result": res})
    return results
