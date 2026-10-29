
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Set

from src.core.notifications import types as T
from src.core.session_activity import EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST, EVENT_STOP
from src.models.websocket import WSMessageType

ROOT = Path(__file__).resolve().parents[3]


def _owners(values: Set[str], attr: str) -> Dict[str, list]:
    return {v: [t.id for t in T.TYPES if v in getattr(t.match, attr)] for v in values}


def test_registry_is_the_plan_table() -> None:
    ids = [t.id for t in T.TYPES]
    assert len(ids) == 39 and len(set(ids)) == 39
    assert "session.finished" in ids and "dev.shape_unrecognized" in ids
    assert {t.family for t in T.TYPES} == set(T.FAMILIES)


def test_every_toast_kind_is_a_carrier_and_every_carried_type_names_one() -> None:
    kinds = {EVENT_STOP, EVENT_PERMISSION_REQUEST, EVENT_NOTIFICATION}
    assert "Stop" in kinds
    assert kinds == set(T.TOAST_CARRIER_KINDS)
    carried = {t.match.carrier for t in T.TYPES if t.match.carrier}
    assert carried == kinds
    assert {t.match.carrier for t in T.TYPES} <= kinds | {""}
    group = (ROOT / "client/js/toast-session-group.js").read_text(encoding="utf-8")
    block = group[group.index("const KIND_BUCKET"):group.index("};", group.index("const KIND_BUCKET"))]
    assert set(re.findall(r"^\s+(\w+):", block, re.M)) == kinds


def test_every_alert_key_maps_to_exactly_one_type() -> None:
    from src.core.account_notice import constants as account_k
    from src.core.self_check import constants as self_k
    from src.core.phone_link.custom_domain import repair

    expected = {account_k.ALERT_KEY: "alert.account",
                repair.ALERT_KEY: "alert.phone_link",
                "cplug.huddle.ping": "alert.plugin",
                "pack_skills.alpha_changed": "pack.skills",
                "pack_skills.placer_gone:iid": "pack.skills",
                "backup_health.usb_backup": "alert.save_pipeline",
                "notifications.destination_disabled": "alert.notifications",
                "notifications.migration_skipped": "alert.notifications"}
    for check in self_k.ALL_CHECKS:
        expected[self_k.ALERT_KEY_PREFIX + check] = "alert.self_check"
    expected.update({"automation.report.run_1": "automation_report", "automation.failed.run_1": "automation_failed"})
    assert len(expected) >= 12 and "self_check.tmux" in expected
    for key, type_id in expected.items():
        assert T.match_alert_key(key) == (type_id,), key
        assert T.type_for_alert_key(key) == type_id
    assert T.match_alert_key("widget.report.x") == ()
    assert T.type_for_alert_key("widget.report.x") == "alert.other"
    assert [t.id for t in T.TYPES if t.match.alert_fallback] == ["alert.other"]


def test_alert_producers_are_the_known_set() -> None:
    found: Set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in ("raise_alert", "register_condition"):
                    found.add(str(path.relative_to(ROOT)))
    assert found == {
        "src/core/account_notice/runner.py",
        "src/core/app_alerts/conditions.py",
        "src/core/app_alerts/service.py",
        "src/core/automations/notify_policy.py",
        "src/core/automations/targets/recipe.py",
        "src/core/backup_health/runner.py",
        "src/core/messaging/runtime.py",
        "src/core/notifications/destinations/migration.py",
        "src/core/notifications/engine.py",
        "src/core/pack/skills/alerts.py",
        "src/core/phone_link/custom_domain/repair.py",
        "src/core/self_check/monitor.py",
        "src/cplugs/host/capabilities.py",
        "src/cplugs/host/catalog_move.py",
    }, found


_NOTIFICATION_FRAMES = {"session.auto_slept", "provider_account.switched", "dev.shape_unrecognized", "stats.tripwire",
                        "session.died"}
_NON_NOTIFICATION_FRAMES = {
    "log", "local_server_detected", "local_server_lost", "session_status", "command", "error", "ping", "pong",
    "pty_data", "pty_resize", "request_dims", "toast.ack", "session.renamed", "terminal_size", "repaint",
    "size_master", "events.hello", "session.status", "sessions.changed", "listing.delta", "peer.listing", "resources.changed",
    "preferences.changed", "skills.changed", "session.note.changed", "provider_ledger.updated",
    "restore_offer.progress", "auto_sleep.changed", "app_alert.updated", "app_alert.resolved",
    "account.session", "perf.sample", "item_settings.changed",
    "ai.config.changed", "terminal.ready", "terminal.resync", "crosstalk.card", "cplug.data",
}


def test_every_ws_frame_is_classified_and_notification_frames_map_to_one_type() -> None:
    enum_values = {m.value for m in WSMessageType}
    assert "toast.new" in enum_values and len(enum_values) > 40
    carriers = set(T.CARRIER_FRAMES)
    assert enum_values == carriers | (_NOTIFICATION_FRAMES - {"stats.tripwire", "session.died"}) | _NON_NOTIFICATION_FRAMES
    for frame, owners in _owners(_NOTIFICATION_FRAMES, "frames").items():
        assert len(owners) == 1, (frame, owners)
    assert {f for t in T.TYPES for f in t.match.frames} == _NOTIFICATION_FRAMES
    assert not carriers & {f for t in T.TYPES for f in t.match.frames}
    assert "stats.tripwire" in (ROOT / "src/core/stats/tripwires.py").read_text(encoding="utf-8")


def test_every_client_toast_kind_is_a_type_a_carrier_or_feedback() -> None:
    pattern = re.compile(r"""(?:kind: *|_KIND *= *)['"]([A-Z][A-Za-z]+)['"]""")
    found: Counter = Counter()
    for base in ("client/js", "web/src"):
        for path in (ROOT / base).rglob("*"):
            if path.suffix not in (".js", ".ts", ".svelte") or "test" in path.name:
                continue
            found.update(pattern.findall(path.read_text(encoding="utf-8")))
    found.pop("Stop", None)
    dedicated = {k for t in T.TYPES for k in t.match.client_kinds}
    assert found and "AutoSlept" in found and "WriteFailed" in found
    assert set(found) == dedicated | set(T.CARRIER_CLIENT_KINDS) | set(T.FEEDBACK_CLIENT_KINDS) | {"PermissionRequest"}
    assert "PermissionRequest" in T.TOAST_CARRIER_KINDS
    for kind, owners in _owners(dedicated, "client_kinds").items():
        assert len(owners) == 1, (kind, owners)
    assert not dedicated & set(T.FEEDBACK_CLIENT_KINDS)
    for kind in ("AutoSleepError", "RecentOpen", "AccountSignedIn", "Attachment", "WriteFailed"):
        assert kind in T.FEEDBACK_CLIENT_KINDS and kind in found
