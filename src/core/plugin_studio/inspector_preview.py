
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.plugins.host import (
    dev_stream,
    inspector_telemetry,
    runtime,
    sidecar_ui,
    sidecar_view,
    sideload,
    ui_doc,
    ui_slots,
)
from src.plugins.host.plugin_manifest import SidecarManifestError, load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import frames, sandbox
from src.plugins.runtime.process import ProcessEnded
from src.plugins.sdk import signed_links


async def get_inspector_snapshot(
    app: Any,
    studio_id: str,
    workspace: Dict[str, Any],
    dev_status: Dict[str, Any],
) -> Dict[str, Any]:
    plugin_id = str(workspace["plugin_id"])
    folder = Path(str(workspace["folder"]))
    live = getattr(app.state, "sidecar_runtime", None)
    host = runtime.host_for(app)
    defn = runtime.find(plugin_id)
    manifest = getattr(defn, "manifest", None)
    if manifest is None and folder.is_dir():
        with contextlib.suppress(SidecarManifestError, OSError):
            manifest = await asyncio.to_thread(load_sidecar_manifest, folder, plugin_id, allow_local=True)

    base: Dict[str, Any] = {}
    events: List[Dict[str, Any]] = []
    slot_renders: Dict[str, List[Dict[str, Any]]] = {}
    if live is not None:
        install_key = ""
        if isinstance(defn, SidecarDefinition) and host is not None:
            with contextlib.suppress(Exception):
                install_key = await asyncio.to_thread(host.install_key, plugin_id)
        base = await asyncio.to_thread(
            inspector_telemetry.build_snapshot_blocking,
            live.state_dir,
            live.supervisor,
            plugin_id,
            canonical_id=plugin_id,
            install_key=install_key,
            kind=getattr(manifest, "kind", "plugin") if manifest else "plugin",
            trust_tier=sideload.TIER_LOCAL,
            trust_badge="Local Dev",
            unverified=True,
            defn=defn,
            data_dir=getattr(defn, "folder", None),
        )
        events = dev_stream.stream_for(live.state_dir).recent(plugin_id)
        if host is not None:
            defs = live._all_definitions() if hasattr(live, "_all_definitions") else runtime.listed()
            raw_slots = (
                ui_slots.registry_for(live.state_dir)
                .resolve(
                    host=host,
                    definitions=defs,
                    safe_mode_active=any(live.safe_mode().values()),
                    supervisor=live.supervisor,
                )
                .get("slots", {})
            )
            for slot_name, items in raw_slots.items():
                matched = [it for it in items if isinstance(it, dict) and it.get("plugin_id") == plugin_id]
                if matched:
                    slot_renders[slot_name] = matched

    capabilities: Dict[str, Any] = {}
    if manifest is not None:
        capabilities = {
            "permissions": list(getattr(manifest, "permissions", ()) or ()),
            "permission_reasons": dict(getattr(manifest, "permission_reasons", {}) or {}),
            "tools": [t.get("name") for t in (getattr(manifest, "tools", ()) or ()) if isinstance(t, dict) and t.get("name")],
            "routes": list(getattr(manifest, "routes", ()) or ()),
            "views": [v.get("name") for v in (getattr(manifest, "views", ()) or ()) if isinstance(v, dict) and v.get("name")],
            "ui_slots": list(getattr(manifest, "ui_slots", ()) or ()),
            "services_provides": [s.get("name") for s in (getattr(manifest, "services_provides", ()) or ()) if isinstance(s, dict)],
            "services_consumes": list(getattr(manifest, "services_consumes", ()) or ()),
            "events_emit": list(getattr(manifest, "events_emit", ()) or ()),
            "events_on": list(getattr(manifest, "events_on", ()) or ()),
        }
    ui_errors = [ev for ev in events if ev.get("type") in ("ui_error", "reload_error", "permission_widened")]
    return {
        **base,
        "studio_id": studio_id,
        "dev": dev_status,
        "capabilities": capabilities,
        "events": events,
        "ui_errors": ui_errors,
        "slot_renders": slot_renders,
    }


async def preview_render(
    app: Any,
    studio_id: str,
    workspace: Dict[str, Any],
    *,
    theme_id: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    surface_id: Optional[str] = None,
) -> Dict[str, Any]:
    _ = studio_id
    plugin_id = str(workspace["plugin_id"])
    folder = Path(str(workspace["folder"]))
    live = getattr(app.state, "sidecar_runtime", None)
    host = runtime.host_for(app)
    defn = runtime.find(plugin_id)
    manifest = getattr(defn, "manifest", None)
    if manifest is None:
        try:
            manifest = await asyncio.to_thread(load_sidecar_manifest, folder, plugin_id, allow_local=True)
        except SidecarManifestError as exc:
            return {
                "kind": "error",
                "doc": None,
                "view_url": None,
                "theme_id": theme_id,
                "width": width,
                "height": height,
                "errors": [{"code": "manifest_invalid", "detail": str(exc)}],
            }

    views = list(getattr(manifest, "views", ()) or ())
    view_names = [str(v.get("name")) for v in views if isinstance(v, dict) and v.get("name")]
    target_surface = surface_id or "widget"
    if view_names and (
        surface_id in view_names
        or (surface_id is None and not getattr(manifest, "tier0", False) and not getattr(manifest, "ui_meta", None))
    ):
        vname = surface_id if surface_id in view_names else view_names[0]
        if isinstance(defn, SidecarDefinition) and host is not None and host.enabled(plugin_id):
            install_key = await asyncio.to_thread(host.install_key, plugin_id)
            ticket = signed_links.mint(sidecar_view.TICKET_LABEL, [install_key, vname], sidecar_view.TICKET_TTL_S)
            return {
                "kind": "view",
                "surface": vname,
                "view_url": f"/api/v1/cplugs/{plugin_id}/view/{vname}/{ticket}/index.html",
                "doc": None,
                "theme_id": theme_id,
                "width": width,
                "height": height,
                "errors": [],
            }
        return {
            "kind": "view",
            "surface": vname,
            "view_url": None,
            "doc": None,
            "theme_id": theme_id,
            "width": width,
            "height": height,
            "errors": [{"code": "not_installed", "detail": "Start Dev Mode or Install the plugin to load its sandboxed view URL."}],
        }

    tool_names = [t.get("name") for t in (getattr(manifest, "tools", ()) or ()) if isinstance(t, dict)]
    if getattr(manifest, "tier0", False):
        local_defn = defn if isinstance(defn, SidecarDefinition) else SidecarDefinition(
            manifest=manifest,
            item_id=f"local/{plugin_id}",
            install_key=f"preview-{plugin_id}",
            code_root=folder,
            folder=folder,
        )
        try:
            raw_doc = sidecar_ui._tier0_static_document(local_defn, target_surface)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return {
                "kind": "declarative",
                "surface": target_surface,
                "doc": None,
                "view_url": None,
                "theme_id": theme_id,
                "width": width,
                "height": height,
                "errors": [{"code": "tier0_ui_invalid", "detail": str(exc)}],
            }
        if raw_doc is None:
            return {"kind": "none", "surface": target_surface, "doc": None, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": []}
        try:
            validated = ui_doc.validate(raw_doc, routes=manifest.routes, tools=tool_names)
        except ui_doc.UiDocError as exc:
            return {"kind": "declarative", "surface": target_surface, "doc": None, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": [{"code": exc.code, "path": exc.path}]}
        return {"kind": "declarative", "surface": target_surface, "doc": validated, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": []}

    if live is None or not isinstance(defn, SidecarDefinition):
        return {"kind": "none", "surface": target_surface, "doc": None, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": [{"code": "dev_not_running", "detail": "Start Dev Mode to render live RPC UI."}]}
    try:
        proc = live.supervisor.process(plugin_id)
        if proc is None or bool(getattr(proc, "ended", None)):
            proc = await live.supervisor.ensure(plugin_id)
        if proc is None or bool(getattr(proc, "ended", None)):
            return {"kind": "declarative", "surface": target_surface, "doc": None, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": [{"code": "cplug_not_running", "detail": "Plugin sidecar process is not running."}]}
        rendered = await sidecar_ui._render(proc, target_surface, {})
        validated = ui_doc.validate(rendered, routes=manifest.routes, tools=tool_names)
        return {"kind": "declarative", "surface": target_surface, "doc": validated, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": []}
    except sidecar_ui.NoSuchSurface:
        return {"kind": "none", "surface": target_surface, "doc": None, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": []}
    except ui_doc.UiDocError as exc:
        return {"kind": "declarative", "surface": target_surface, "doc": None, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": [{"code": exc.code, "path": exc.path}]}
    except (OSError, sandbox.SandboxUnavailable, RuntimeError, frames.FrameViolation, ProcessEnded) as exc:
        return {"kind": "declarative", "surface": target_surface, "doc": None, "view_url": None, "theme_id": theme_id, "width": width, "height": height, "errors": [{"code": type(exc).__name__, "detail": str(exc)[:200]}]}
