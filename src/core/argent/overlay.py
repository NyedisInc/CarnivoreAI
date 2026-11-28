
from __future__ import annotations

import asyncio
import json
import os
import shlex
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import structlog

from src.core.argent import gateway_reach, health, mint, notices, overlay_agy, overlay_codex, row_state, upstream, upstream_registry
from src.core.argent import session_ref as refs
from src.core.argent import settings as settings_module
from src.core.argent.runtime import get_runtime
from src.config import settings as app_settings
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.session_transcript_presence import family_conversation_presence
from src.core.sessions.launch_overlay import OverlayContext, OverlayDelivery, OverlayPlan, OverlayRefused, UpstreamRoute

logger = structlog.get_logger()

SECRET_NAME = "CARNIVORE_ARGENT_KEY"
OVERRIDE_KEYS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS")
COPILOT = "copilot"
COPILOT_ENV_NAMES = ("COPILOT_PROVIDER_BASE_URL", "COPILOT_PROVIDER_TYPE", "COPILOT_PROVIDER_API_KEY", "COPILOT_MODEL", "NODE_EXTRA_CA_CERTS")
COPILOT_DEFAULT_MODEL = "claude-sonnet-5-5"
COPILOT_BASE_NAME = "CARNIVORE_ARGENT_COPILOT_BASE"
CLAUDE_BASE_NAME = "CARNIVORE_ARGENT_CLAUDE_BASE"
AGY_BASE_NAME = "CARNIVORE_ARGENT_AGY_BASE"
WAIT_SECONDS = 10


def _read_key() -> str:
    return (
        f'_ak="${{{SECRET_NAME}-}}"; unset {SECRET_NAME}; _i=0; '
        f'while [ -z "$_ak" ] && [ "$_i" -lt {WAIT_SECONDS * 4} ]; do '
        f'_ak="$(tmux show-environment {SECRET_NAME} 2>/dev/null)"; '
        f'case "$_ak" in {SECRET_NAME}=?*) _ak="${{_ak#*=}}";; *) _ak="";; esac; '
        f'[ -z "$_ak" ] && sleep 0.25; _i=$((_i+1)); done; '
        f'tmux set-environment -u {SECRET_NAME} 2>/dev/null; '
    )


def preamble(gateway_url: str, ca_path: str, proxy: str = "") -> str:
    ca = f"export NODE_EXTRA_CA_CERTS={shlex.quote(ca_path)}; " if ca_path else ""
    return (
        _read_key() + _read_tool_base(CLAUDE_BASE_NAME, gateway_url) +
        f'if [ -n "$_ak" ] && [ "$_ak" != "-" ]; then '
        f'export ANTHROPIC_BASE_URL="$_cb"; {ca}{proxy}'
        f'export ANTHROPIC_CUSTOM_HEADERS="x-api-key: $_ak"; '
        f'else unset ANTHROPIC_BASE_URL ANTHROPIC_CUSTOM_HEADERS; fi; unset _ak _i _cb'
    )


def codex_preamble(ca_path: str, proxy: str = "", gateway_url: str = "") -> str:
    ca = f"export CODEX_CA_CERTIFICATE={shlex.quote(ca_path)}; " if ca_path else ""
    return (
        _read_key() + _read_tool_base(overlay_codex.BASE_DELIVERY, gateway_url.rstrip("/") + overlay_codex.TOKEN_PATH) + f'export {overlay_codex.BASE_ENV}="$_cb"; ' +
        _read_tool_base(overlay_codex.AUTH_DELIVERY, "false") + f'export {overlay_codex.AUTH_ENV}="$_cb"; unset _cb; ' +
        f'if [ -n "$_ak" ] && [ "$_ak" != "-" ]; then {ca}{proxy}export {overlay_codex.HEADER_ENV}="$_ak"; '
        f'else unset {overlay_codex.HEADER_ENV}; fi; unset _ak _i'
    )


def _read_tool_base(n: str, gateway_url: str) -> str:
    return (
        f'_cb="${{{n}-}}"; unset {n}; '
        f'[ -z "$_cb" ] && {{ _cb="$(tmux show-environment {n} 2>/dev/null)"; case "$_cb" in {n}=?*) _cb="${{_cb#*=}}";; *) _cb="";; esac; }}; '
        f'tmux set-environment -u {n} 2>/dev/null; [ -n "$_cb" ] || _cb={shlex.quote(gateway_url)}; '
    )


def copilot_preamble(gateway_url: str, ca_path: str, proxy: str = "") -> str:
    ca = f"export NODE_EXTRA_CA_CERTS={shlex.quote(ca_path)}; " if ca_path else ""
    return (
        _read_key() + _read_tool_base(COPILOT_BASE_NAME, gateway_url) +
        f'if [ -n "$_ak" ] && [ "$_ak" != "-" ]; then export COPILOT_PROVIDER_BASE_URL="$_cb" COPILOT_PROVIDER_TYPE=anthropic; {ca}{proxy}'
        f'export COPILOT_PROVIDER_API_KEY="$_ak" COPILOT_MODEL="${{COPILOT_MODEL:-{COPILOT_DEFAULT_MODEL}}}"; '
        f'else unset COPILOT_PROVIDER_BASE_URL COPILOT_PROVIDER_TYPE COPILOT_PROVIDER_API_KEY COPILOT_PROVIDER_HEADERS; fi; unset _ak _i _cb'
    )


def settings_override(working_dir: str, environ: Optional[Mapping[str, str]] = None) -> bool:
    env = environ if environ is not None else os.environ
    config_dir = Path(env.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
    files = [config_dir / "settings.json"]
    if working_dir:
        files += [Path(working_dir) / ".claude" / "settings.json", Path(working_dir) / ".claude" / "settings.local.json"]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if text_overrides(text):
            return True
    return False


def text_overrides(text: str) -> bool:
    try:
        block = json.loads(text).get("env")
    except (ValueError, AttributeError):
        return False
    return isinstance(block, dict) and any(k in block for k in OVERRIDE_KEYS)


def _untethered_reason(report: health.HealthReport, now: float) -> str:
    if now - report.checked_at > health.FRESH_SECONDS or report.state not in (health.UP, health.CAP_TOO_LOW) or report.mints_accepted is not True:
        return "argent down at launch"
    return "too large for gateway cap" if report.state == health.CAP_TOO_LOW else ""


class ArgentOverlay:

    def __init__(self, clock: Any = time.time, transport: Optional[Any] = None) -> None:
        self._clock, self._transport = clock, transport

    def plan(self, harness: str, purpose: str, host_key: str = LOCAL_HOST_KEY) -> Optional[OverlayPlan]:
        if purpose != "pane" or harness not in ("claude", "codex", COPILOT, overlay_agy.TOOL):
            return None
        cfg = settings_module.read()
        if not cfg.enabled or not cfg.gateway_url:
            return None
        tethering = not _untethered_reason(health.latest(), self._clock())
        reach = gateway_reach.get()
        proxy = reach.exports_for(host_key) if reach is not None and host_key != LOCAL_HOST_KEY else ""
        if harness == COPILOT:
            return OverlayPlan(preamble=copilot_preamble(cfg.gateway_url, cfg.ca_path, proxy) if tethering else "", env_names=COPILOT_ENV_NAMES, secret_name=SECRET_NAME, tool=COPILOT)
        if harness == overlay_agy.TOOL:
            return OverlayPlan(preamble=overlay_agy.preamble(_read_key() + _read_tool_base(AGY_BASE_NAME, cfg.gateway_url.rstrip("/")), cfg.gateway_url, proxy, overlay_agy.ca_bundle(cfg.ca_path, Path(app_settings.get_state_dir()))) if tethering else "", env_names=overlay_agy.ENV_NAMES,
                               secret_name=SECRET_NAME, tool=overlay_agy.TOOL)
        if harness == "codex":
            if tethering and overlay_codex.headers_supported():
                return OverlayPlan(preamble=codex_preamble(cfg.ca_path, proxy, cfg.gateway_url), env_names=(overlay_codex.HEADER_ENV, overlay_codex.BASE_ENV, overlay_codex.AUTH_ENV, "CODEX_CA_CERTIFICATE"),
                                   secret_name=SECRET_NAME, flags=overlay_codex.flags())
            return OverlayPlan(preamble="", secret_name=SECRET_NAME)
        return OverlayPlan(preamble=preamble(cfg.gateway_url, cfg.ca_path, proxy) if tethering else "", env_names=("ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "NODE_EXTRA_CA_CERTS"),
                           secret_name=SECRET_NAME)

    def chain_plan(self, harness: str, purpose: str, route: UpstreamRoute) -> Optional[OverlayPlan]:
        from src.core.argent import overlay_chain

        if purpose != "pane" or harness not in ("claude", "codex"):
            return None
        cfg = settings_module.read()
        if not cfg.enabled or not cfg.gateway_url:
            return None
        names = ("ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "NODE_EXTRA_CA_CERTS") if harness == "claude" else (overlay_codex.HEADER_ENV, "CODEX_CA_CERTIFICATE")
        report = health.latest()
        if upstream.is_private_network(route.base_url):
            return OverlayPlan(preamble="", secret_name=SECRET_NAME, reason=upstream.PRIVATE_REASON)
        if _untethered_reason(report, self._clock()):
            return OverlayPlan(preamble="", secret_name=SECRET_NAME)
        if report.upstream_chain is not True:
            return OverlayPlan(preamble="", secret_name=SECRET_NAME, reason=upstream.NOT_READY_REASON)
        known = upstream_registry.reason_cached(self._tenant(), route.base_url)
        if known:
            return OverlayPlan(preamble="", secret_name=SECRET_NAME, reason=known)
        if harness == "codex":
            if not overlay_codex.headers_supported():
                return OverlayPlan(preamble="", secret_name=SECRET_NAME)
            return OverlayPlan(preamble=overlay_chain.codex_preamble(cfg.ca_path, route.base_url), env_names=(*names, overlay_chain.UPSTREAM_URL_ENV),
                               secret_name=SECRET_NAME, flags=overlay_chain.codex_flags(cfg.gateway_url, route), chained=True, replaces_flags=True, upstream_url=route.base_url)
        return OverlayPlan(preamble=overlay_chain.claude_preamble(cfg.gateway_url, cfg.ca_path, route.key_env), env_names=names, secret_name=SECRET_NAME, chained=True,
                           upstream_url=route.base_url)

    async def materialize(self, plan: OverlayPlan, ctx: OverlayContext) -> OverlayDelivery:
        cfg = settings_module.read()
        reason = plan.reason or _untethered_reason(health.latest(), self._clock())
        if not reason and ctx.host_key != LOCAL_HOST_KEY:
            reason = self._reach_reason(ctx.host_key, plan)
        tool = plan.tool or ctx.harness
        if tool == "codex":
            if not reason and not plan.flags:
                reason = overlay_codex.UNSUPPORTED_REASON
        elif tool == "claude" and not reason and (ctx.settings_override if ctx.settings_override is not None else await asyncio.to_thread(settings_override, ctx.working_dir)):
            reason = "settings override"
        listed = False
        if not reason and ctx.resume_uuid and tool in ("claude", "codex"):
            reason = await asyncio.to_thread(self._too_large, ctx)
            listed = bool(reason)
        if plan.chained and plan.upstream_url and not reason:
            reason = await upstream_registry.reason_live(await asyncio.to_thread(self._tenant), plan.upstream_url, transport=self._transport)
            listed = bool(reason)
        key = ""
        ref = await asyncio.to_thread(self._ref, ctx.session_ref)
        if not reason:
            try:
                key = await asyncio.wait_for(mint.mint_session_key(ref, ctx.display_name, tool, transport=self._transport), mint.MINT_TIMEOUT_SECONDS)
            except (mint.MintFailed, asyncio.TimeoutError) as exc:
                reason = upstream.reason_for_denial(getattr(exc, "code", "")) or "argent down at launch"
                listed = reason != "argent down at launch"
                logger.warning("argent_mint_failed", error_type=type(exc).__name__, reason=str(exc)[:200], code=getattr(exc, "code", ""))
        key_id = str(getattr(key, "key_id", "") or "")
        try:
            await asyncio.to_thread(self._record, ctx, ref, tethered=bool(key), reason=reason, key_id=key_id,
                                         key_expires_at=float(getattr(key, "expires_at", 0.0) or 0.0))
        except sqlite3.Error as exc:
            logger.warning("argent_row_state_not_recorded", error_type=type(exc).__name__)
        if key:
            note = {"tethered": True, "reason": "", "mint_epoch": int(self._clock()), **({"chained": True} if plan.chained else {})}
            routed = {name: str(getattr(key, attr, "") or "") for name, attr in ((CLAUDE_BASE_NAME, "claude_base"), (COPILOT_BASE_NAME, "copilot_base"), (AGY_BASE_NAME, "agy_base"))}
            if tool == "codex" and not plan.chained:
                chatgpt = cfg.codex_auth_mode == "passthrough" and bool(getattr(key, "codex_chatgpt_base", ""))
                routed[overlay_codex.BASE_DELIVERY] = str(getattr(key, "codex_chatgpt_base" if chatgpt else "codex_base", "") or "")
                routed[overlay_codex.AUTH_DELIVERY] = "true" if chatgpt else "false"
            return OverlayDelivery(secrets={SECRET_NAME: key, **{name: base for name, base in routed.items() if base}}, note=note)
        logger.warning("argent_untethered_launch", reason=reason, session=ctx.session_ref)
        try:
            if await asyncio.to_thread(self._claim_notice, ref):
                notices.untethered_launch(ctx.session_ref, ctx.display_name, reason)
        except sqlite3.Error as exc:
            logger.warning("argent_notice_claim_failed", error_type=type(exc).__name__)
        if cfg.refuse_direct_launch and not plan.reason and not listed:
            raise OverlayRefused(reason)
        delivery: Dict[str, str] = {plan.secret_name: plan.direct_value} if plan.preamble else {}
        return OverlayDelivery(secrets=delivery, note={"tethered": False, "reason": reason, "mint_epoch": 0})

    @staticmethod
    def _too_large(ctx: OverlayContext) -> str:
        cap = health.latest().body_cap_bytes
        if cap is None:
            return ""
        presence = family_conversation_presence(ctx.harness, ctx.resume_uuid, working_dir=ctx.working_dir or None)
        try:
            size = os.stat(presence.path).st_size if presence.path is not None else 0
        except OSError:
            return ""
        return "too large for gateway cap" if size > health.CAP_SHARE * cap else ""

    @staticmethod
    def _reach_reason(host_key: str, plan: OverlayPlan) -> str:
        reach = gateway_reach.get()
        state = reach.state(host_key) if reach is not None else None
        if state is not None and state.state == gateway_reach.DIRECT:
            return ""
        if reach is not None and state is not None and state.state == gateway_reach.CARRIED and reach.exports_for(host_key) and "HTTPS_PROXY" in plan.preamble:
            return ""
        return gateway_reach.unreachable_reason(reach.label_for(host_key) if reach is not None else host_key)

    @staticmethod
    def _tenant() -> str:
        login = get_runtime().store.get_login()
        return str(login["tenant_id"]) if login else ""

    def _ref(self, tmux_name: str) -> str:
        tenant = self._tenant()
        return refs.ref_for_name(tenant, tmux_name) if tenant else tmux_name

    def _claim_notice(self, session_ref: str) -> bool:
        return row_state.claim_notice(self._tenant(), session_ref)

    def _record(self, ctx: OverlayContext, ref: str, *, tethered: bool, reason: str, key_id: str, key_expires_at: float = 0.0) -> None:
        row_state.record_launch(self._tenant(), ref, working_dir=ctx.working_dir, tethered=tethered, reason=reason, key_id=key_id,
                                 key_expires_at=key_expires_at)

    async def prepare_host(self, host_key: str) -> None:
        reach = gateway_reach.get()
        if reach is not None:
            await reach.ensure(host_key)

    async def confirm(self, session_ref: str) -> None:
        try:
            tenant = await asyncio.to_thread(self._tenant)
            session_ref = await asyncio.to_thread(self._ref, session_ref)
            for key_id in await asyncio.to_thread(row_state.confirm, tenant, session_ref):
                if await mint.revoke_key(key_id, transport=self._transport):
                    await asyncio.to_thread(row_state.forget_key, tenant, session_ref, key_id)
        except sqlite3.Error as exc:
            logger.warning("argent_confirm_failed", error_type=type(exc).__name__)
