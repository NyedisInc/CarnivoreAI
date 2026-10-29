
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

FAMILY_NEEDS_YOU = "needs_you"
FAMILY_SESSIONS = "sessions"
FAMILY_ACCOUNTS = "accounts"
FAMILY_HEALTH = "health"
FAMILY_APP = "app"
FAMILY_IN_APP = "in_app"
FAMILIES: Tuple[str, ...] = (
    FAMILY_NEEDS_YOU, FAMILY_SESSIONS, FAMILY_ACCOUNTS, FAMILY_HEALTH, FAMILY_APP, FAMILY_IN_APP,
)

TOAST_CARRIER_KINDS: Tuple[str, ...] = ("Stop", "PermissionRequest", "Notification")
CARRIER_FRAMES: Tuple[str, ...] = ("toast.new", "app_alert.raised", "approvals")
CARRIER_CLIENT_KINDS: Tuple[str, ...] = ("AppAlert",)
FEEDBACK_CLIENT_KINDS: Tuple[str, ...] = (
    "AutoSleepError", "RecentOpen", "AccountSignedIn", "Attachment", "WriteFailed", "AgentOpen", "BeastError",
    "NotifyMuted", "ApprovalGone", "Bookmark", "PackSend",
    "WidgetsBars", "SwarmSwitchError",
)

_NO_FINISHED_SEED: Tuple[str, ...] = ("sns", "twilio", "pagerduty")


@dataclass(frozen=True)
class Match:

    frames: Tuple[str, ...] = ()
    alert_keys: Tuple[str, ...] = ()
    alert_prefixes: Tuple[str, ...] = ()
    alert_fallback: bool = False
    client_kinds: Tuple[str, ...] = ()
    approval_kinds: Tuple[str, ...] = ()
    carrier: str = ""


@dataclass(frozen=True)
class Defaults:

    screen: bool = True
    seed: bool = False
    outside_locked_off: bool = False
    passes_quiet_hours: bool = False
    screen_surface: str = "card"


@dataclass(frozen=True)
class NotifyType:

    id: str
    family: str
    label_key: str
    description_key: str
    copy_prefix: str
    source: str
    match: Match
    defaults: Defaults
    seed_excluded_kinds: Tuple[str, ...] = ()

    @property
    def copy_title_key(self) -> str:
        return f"{self.copy_prefix}.title"

    @property
    def copy_body_key(self) -> str:
        return f"{self.copy_prefix}.body"


_NEEDS = Defaults(screen=True, seed=True, passes_quiet_hours=True)
_SEED = Defaults(seed=True)
_SHOWN = Defaults()
_NO_OUT = Defaults(outside_locked_off=True)
_SWARM_ALERT = Defaults(screen=False, seed=True)
_ALL_KINDS: Tuple[str, ...] = (
    "slack", "discord", "teams", "telegram", "ntfy", "pushover", "webhook", "email", "sns", "twilio", "pagerduty", "webpush", "apns",
)
_ALERT_SEED_KINDS: Tuple[str, ...] = ("webpush", "apns")
_FLASH_SEED_KINDS: Tuple[str, ...] = ("sns", "twilio")


def catalog_namespace(type_id: str) -> Tuple[str, str]:
    parts = type_id.split(".", 2)
    if len(parts) == 3 and parts[0] == "cplug":
        return f"cplug.{parts[1]}.notify.type.{parts[2]}", f"cplug.{parts[1]}.notify.copy.{parts[2]}"
    return f"notify.type.{type_id}", f"notify.copy.{type_id}"


def _row(
    type_id: str, family: str, source: str, match: Match, defaults: Defaults,
    seed_excluded_kinds: Tuple[str, ...] = (),
) -> NotifyType:
    type_stem, copy_stem = catalog_namespace(type_id)
    return NotifyType(
        id=type_id, family=family, label_key=f"{type_stem}.label",
        description_key=f"{type_stem}.description", copy_prefix=copy_stem,
        source=source, match=match, defaults=defaults, seed_excluded_kinds=seed_excluded_kinds,
    )


TYPES: Tuple[NotifyType, ...] = (
    _row("session.permission", FAMILY_NEEDS_YOU, "toast", Match(carrier="PermissionRequest"), _NEEDS),
    _row("session.question", FAMILY_NEEDS_YOU, "toast", Match(carrier="PermissionRequest"), _NEEDS),
    _row("session.plan_approval", FAMILY_NEEDS_YOU, "toast", Match(carrier="PermissionRequest"), _NEEDS),
    _row("session.attention", FAMILY_NEEDS_YOU, "toast", Match(carrier="Notification"), _NEEDS),
    _row("approval.agent_action", FAMILY_NEEDS_YOU, "approvals", Match(approval_kinds=("agent_action",)),
         Defaults(screen=True, passes_quiet_hours=True, screen_surface="approvals_inbox")),
    _row("session.finished", FAMILY_SESSIONS, "toast",
         Match(carrier="Stop"),
         _SEED, _NO_FINISHED_SEED),
    _row("session.died", FAMILY_SESSIONS, "died",
         Match(frames=("session.died",), client_kinds=("SessionDied",)), _SEED),
    _row("session.skill_tripwire", FAMILY_SESSIONS, "toast", Match(carrier="Notification"), _SHOWN),
    _row("session.auto_slept", FAMILY_SESSIONS, "frame",
         Match(frames=("session.auto_slept",), client_kinds=("AutoSlept",)), _SHOWN),
    _row("session.posted", FAMILY_SESSIONS, "toast", Match(), _SHOWN),
    _row("approval.folder_trust", FAMILY_SESSIONS, "approvals", Match(approval_kinds=("folder_trust",)),
         Defaults(screen=False)),
    _row("agent.message", FAMILY_SESSIONS, "toast", Match(carrier="Notification"), _SHOWN),
    _row("swarm.alert", FAMILY_SESSIONS, "swarm", Match(), _SWARM_ALERT,
         tuple(k for k in _ALL_KINDS if k not in _ALERT_SEED_KINDS)),
    _row("swarm.flash", FAMILY_SESSIONS, "swarm", Match(), _SWARM_ALERT,
         tuple(k for k in _ALL_KINDS if k not in _FLASH_SEED_KINDS)),
    _row("swarm.question_climbed", FAMILY_SESSIONS, "swarm", Match(), _SWARM_ALERT,
         tuple(k for k in _ALL_KINDS if k not in _ALERT_SEED_KINDS)),
    _row("agent.update_ready", FAMILY_SESSIONS, "agent_update", Match(), _SHOWN),
    _row("session.beast_approved", FAMILY_SESSIONS, "beast_prompts", Match(), _SEED, _NO_FINISHED_SEED),
    _row("session.auto_accepted", FAMILY_SESSIONS, "auto_answer", Match(), _SHOWN),
    _row("plugin.notice", FAMILY_SESSIONS, "toast", Match(carrier="Notification"), _SHOWN),
    _row("provider.needs_login", FAMILY_ACCOUNTS, "login", Match(), _SEED),
    _row("account.switched", FAMILY_ACCOUNTS, "frame",
         Match(frames=("provider_account.switched",), client_kinds=("AccountSwitched",)), _SHOWN),
    _row("session.limit_rotation", FAMILY_ACCOUNTS, "limit_rotation", Match(), _SHOWN),
    _row("alert.self_check", FAMILY_HEALTH, "alerts", Match(alert_prefixes=("self_check.",)), _SEED),
    _row("alert.save_pipeline", FAMILY_HEALTH, "alerts", Match(alert_prefixes=("backup_health.",)), _SEED),
    _row("alert.account", FAMILY_HEALTH, "alerts", Match(alert_keys=("account.signed_out",)), _SEED),
    _row("alert.phone_link", FAMILY_HEALTH, "alerts", Match(alert_keys=("phone_link.repair",)), _SEED),
    _row("alert.plugin", FAMILY_HEALTH, "alerts", Match(alert_prefixes=("cplug.",)), _SHOWN),
    _row("pack.skills", FAMILY_HEALTH, "alerts", Match(alert_prefixes=("pack_skills.",)), _SEED),
    _row("alert.other", FAMILY_HEALTH, "alerts", Match(alert_fallback=True), _SHOWN),
    _row("alert.notifications", FAMILY_HEALTH, "alerts", Match(alert_keys=("notifications.destination_disabled", "notifications.migration_skipped")),
         _NO_OUT),
    _row("computer.wrong_code", FAMILY_HEALTH, "computers", Match(), _SHOWN),
    _row("computer.link_cert", FAMILY_HEALTH, "computers", Match(), _SHOWN),
    _row("app.restore_offer", FAMILY_APP, "restore", Match(), _SHOWN),
    _row("app.update_available", FAMILY_APP, "update", Match(), _SHOWN),
    _row("automation_report", FAMILY_APP, "automation", Match(alert_prefixes=("automation.report.",)), _SHOWN),
    _row("automation_failed", FAMILY_APP, "automation", Match(alert_prefixes=("automation.failed.",)), _SHOWN),
    _row("automation_notice", FAMILY_APP, "automation", Match(alert_prefixes=("automation.notice.",)), _SHOWN),
    _row("stats.tripwire", FAMILY_IN_APP, "frame",
         Match(frames=("stats.tripwire",), client_kinds=("StatsTripwire",)), _NO_OUT),
    _row("dev.shape_unrecognized", FAMILY_IN_APP, "frame",
         Match(frames=("dev.shape_unrecognized",), client_kinds=("ShapeUnrecognized",)), _NO_OUT),
)

NEEDS_YOU: frozenset = frozenset(t.id for t in TYPES if t.family == FAMILY_NEEDS_YOU)

_BY_ID: Dict[str, NotifyType] = {t.id: t for t in TYPES}


def get_type(type_id: str) -> Optional[NotifyType]:
    return _BY_ID.get(type_id)


def is_registered(type_id: object) -> bool:
    return isinstance(type_id, str) and type_id in _BY_ID


def ordered_types() -> List[NotifyType]:
    return list(TYPES)


def seed_type_ids() -> Tuple[str, ...]:
    return tuple(t.id for t in TYPES if t.defaults.seed)


def seed_for_kind(kind_id: str) -> Tuple[str, ...]:
    return tuple(t.id for t in TYPES if t.defaults.seed and kind_id not in t.seed_excluded_kinds)


def match_alert_key(key: str) -> Tuple[str, ...]:
    found = []
    for row in TYPES:
        m = row.match
        if key in m.alert_keys or any(key.startswith(p) for p in m.alert_prefixes):
            found.append(row.id)
    return tuple(found)


def type_for_alert_key(key: str) -> str:
    found = match_alert_key(key)
    if found:
        return found[0]
    return next(t.id for t in TYPES if t.match.alert_fallback)
