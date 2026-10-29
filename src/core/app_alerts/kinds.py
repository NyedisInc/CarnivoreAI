
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.app_alerts import constants as K

NEEDS_YOU, FYI, QUESTION = "needs_you", "fyi", "question"
KINDS: Tuple[str, ...] = (NEEDS_YOU, FYI, QUESTION)

SOURCE_NAME_PARAMS: Tuple[str, ...] = ("agent", "session", "plugin", "automation", "provider")

RECHECK_PREFIXES: Tuple[str, ...] = ("backup_health.",)

SYSTEM_PANES: Dict[str, str] = {
    "full_disk_access": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
}

_P = K.KEY_PREFIX


def _a(name: str) -> str:
    return f"{_P}action.{name}"


def _link(action_id: str, href: str) -> Dict[str, Any]:
    return {"id": action_id, "label_key": _a(action_id), "href": href}


def _recheck() -> Dict[str, Any]:
    return {"id": "recheck", "label_key": _a("recheck"), "method": "POST", "route": "/alerts/{id}/recheck"}


def _privacy() -> Dict[str, Any]:
    return {"id": "open_privacy", "label_key": _a("open_privacy"), "method": "POST",
            "route": "/alerts/open-system-settings", "body": {"pane": "full_disk_access"}}


_BACKUPS = "#plugins/save/settings"


@dataclass(frozen=True)
class Source:

    label_key: str
    icon: str


@dataclass(frozen=True)
class Declared:

    kind: str
    actions: Tuple[Mapping[str, Any], ...] = ()
    default_detail_key: Optional[str] = None


def _src(name: str, icon: str) -> Source:
    return Source(f"{_P}source.{name}", icon)


SOURCES: Dict[str, Source] = {
    "backup_health": _src("backup_health", "database"),
    "account_notice": _src("account", "star"),
    "phone_link": _src("phone_link", "cloud"),
    "notifications": _src("notifications", "bell"),
    "self_check": _src("self_check", "wrench"),
    "widgets": _src("widgets", "grid"),
    "automations": _src("automations", "bolt"),
    "messaging": _src("messaging", "chat"),
    "pack_skills": _src("pack_skills", "users"),
}
FALLBACK_SOURCE = Source(f"{_P}source.other", "bell")


def source_catalog() -> List[Dict[str, str]]:
    seen: Dict[str, Dict[str, str]] = {}
    for src in (*SOURCES.values(), FALLBACK_SOURCE):
        seen.setdefault(src.label_key, {"id": src.label_key.rsplit(".", 1)[-1], "label_key": src.label_key, "icon": src.icon})
    return list(seen.values())

_TM_UNKNOWN = f"{_P}backup_health.tm_unknown.title"


def _explain_access() -> Dict[str, Any]:
    return {"id": "check_access", "label_key": _a("check_access"), "explain_key": "", "actions": [_privacy(), _recheck()]}


BY_TITLE: Dict[str, Declared] = {
    _TM_UNKNOWN: Declared(NEEDS_YOU, (_explain_access(), _recheck())),
    f"{_P}backup_health.tm_stale.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}backup_health.usb_stale.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}backup_health.usb_missing.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}backup_health.vault_unavailable.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}backup_health.vault_stale.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}backup_health.vault_uncovered.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}backup_health.vault_over_cap.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}backup_health.vault_damaged.title": Declared(NEEDS_YOU, (_recheck(), _link("open_backups", _BACKUPS))),
    f"{_P}notifications.destination_disabled.title": Declared(NEEDS_YOU, (_link("open_notification_settings", "#settings/notifications"),)),
    f"{_P}notifications.migration_skipped.title": Declared(NEEDS_YOU, (_link("open_notification_settings", "#settings/notifications"),)),
    f"{_P}account.signed_out.title": Declared(NEEDS_YOU, (_link("sign_in", "#account"),)),
    f"{_P}phone_link.repair.title": Declared(NEEDS_YOU, (_link("pair_device", "#settings/remote"),)),
    f"{_P}self_check.full_disk_access.title": Declared(NEEDS_YOU, (_privacy(),)),
    f"{_P}messaging.gap.title": Declared(FYI, (), f"{_P}detail.messaging_gap"),
    f"{_P}widget.report.title": Declared(FYI, (_link("open_widgets", "#widgets"),)),
    f"{_P}automation.report.title": Declared(FYI),
    f"{_P}automation.failed.title": Declared(NEEDS_YOU),
    f"{_P}automation.notice.title": Declared(FYI),
    f"{_P}pack_skills.alpha_changed.title": Declared(NEEDS_YOU),
    f"{_P}pack_skills.placer_gone.title": Declared(NEEDS_YOU),
    f"{_P}pack_skills.edit_replaced.title": Declared(FYI),
    f"{_P}pack_skills.edits_replaced.title": Declared(FYI),
    f"{_P}pack_skills.settings_refused.title": Declared(NEEDS_YOU),
    # the plugins page
    **{f"{_P}cplug_runtime.{name}.title": Declared(NEEDS_YOU, (_link("open_plugins", "#plugins"),))
       for name in ("crash_loop", "revoked", "integrity", "index_expired", "safe_mode", "plugin_alert", "sandbox")},
}

BY_KEY_PREFIX: Tuple[Tuple[str, Declared], ...] = (
    ("self_check.", Declared(NEEDS_YOU, (_link("open_settings", "#settings/advanced"),))),
    ("cplug.", Declared(NEEDS_YOU, (_link("open_plugins", "#plugins"),))),
)


def declared_for(key: str, title_key: str) -> Optional[Declared]:
    found = BY_TITLE.get(title_key)
    if found is not None:
        return found
    return next((d for prefix, d in BY_KEY_PREFIX if key.startswith(prefix)), None)


def _fill(action: Mapping[str, Any], alert_id: int, params: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(action)
    if "route" in out:
        out["route"] = str(out["route"]).replace("{id}", str(alert_id))
    if "actions" in out:
        out["actions"] = [_fill(a, alert_id, params) for a in out["actions"]]
    if out.get("id") == "check_access":
        out["explain_key"] = f"{_P}backup_health.tm_unknown.explain.{params.get('reason') or 'unreadable'}"
    return out


def _kind_by_severity(severity: str) -> str:
    return FYI if severity == K.SEV_INFO else NEEDS_YOU


def describe(alert_id: int, key: str, source: str, severity: str, title_key: str,
             params: Mapping[str, Any], stored_actions: Sequence[Mapping[str, Any]],
             stored_detail_key: Optional[str]) -> Dict[str, Any]:
    src = SOURCES.get(source, FALLBACK_SOURCE)
    declared = declared_for(key, title_key)
    actions: List[Dict[str, Any]] = [dict(a) for a in stored_actions]
    have = {a.get("id") for a in actions}
    if declared is not None:
        actions += [_fill(a, alert_id, params) for a in declared.actions if a.get("id") not in have]
    name = next((str(params[p]) for p in SOURCE_NAME_PARAMS if params.get(p)), None)
    kind = declared.kind if declared is not None else _kind_by_severity(severity)
    detail = stored_detail_key
    if detail is None and declared is not None and not actions:
        detail = declared.default_detail_key
    return {"source_label_key": src.label_key, "source_icon": src.icon, "source_name": name, "kind": kind,
            "actions": actions, "detail_key": detail}
