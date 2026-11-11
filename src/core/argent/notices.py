
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from src.core.app_alerts import constants as K
from src.core.app_alerts import service
from src.core.argent import budget

SOURCE = "argent"
UNTETHERED_PREFIX = "argent.untethered_launch:"
CLASSIFIER_PREFIX = "argent.classifier.fix:"


def untethered_launch(session_ref: str, display_name: str, reason: str) -> None:
    service.raise_alert(UNTETHERED_PREFIX + session_ref, source=SOURCE, severity=K.SEV_WARN, title_key="app_alert.argent.untethered_launch.title",
                        detail_key="app_alert.argent.untethered_launch.detail", params={"name": display_name or session_ref, "reason": reason},
                        auto_resolve=False)


def queue_overflow(dropped: int) -> None:
    service.raise_alert("argent.queue.overflow", source=SOURCE, severity=K.SEV_WARN, title_key="app_alert.argent.queue_overflow.title",
                        detail_key="app_alert.argent.queue_overflow.detail", params={"count": str(dropped)}, auto_resolve=False)


def pair_login(computer: str) -> None:
    service.raise_alert("argent.pair.login", source=SOURCE, severity=K.SEV_WARN, title_key="app_alert.argent.pair_login.title",
                        detail_key="app_alert.argent.pair_login.detail", params={"computer": computer or "this computer"}, auto_resolve=False)


def pair_login_resolved() -> None:
    service.resolve("argent.pair.login")


CHANGE_STORY_PANEL = "#settings/features/argent/settings"


def classifier_fix(session_ref: str, display_name: str, title: str, previous_title: str, ask: bool) -> None:
    service.raise_alert(CLASSIFIER_PREFIX + session_ref, source=SOURCE, severity=K.SEV_INFO, title_key="app_alert.argent.classifier_fix.title",
                        detail_key="app_alert.argent.classifier_fix.ask" if ask else "app_alert.argent.classifier_fix.detail",
                        params={"name": display_name or session_ref, "item": title, "previous": previous_title or "-"},
                        actions=({"id": "argent_change_story", "label_key": "app_alert.action.argent_change_story", "href": f"{CHANGE_STORY_PANEL}?session={quote(session_ref, safe='')}"},), auto_resolve=False)


BUDGET_WARN_PREFIX, BUDGET_HOLD_PREFIX, HOLD_LIFTED_PREFIX = "argent.budget.warn:", "argent.budget.hold:", "argent.hold.lifted:"
BUDGET_PANEL = "#settings/features/argent/settings"


def budget_warn(item_id: str, item_name: str, spent: str, cap: str) -> None:
    service.raise_alert(BUDGET_WARN_PREFIX + item_id, source=SOURCE, severity=K.SEV_INFO, title_key="app_alert.argent.budget_warn.title",
                        detail_key="app_alert.argent.budget_warn.detail", params={"item": item_name, "spent": spent, "cap": cap}, auto_resolve=False)


def hold_actions(item_id: str, item_name: str, owner: str, spent: str, cap: str) -> Tuple[Tuple[Dict[str, Any], ...], Dict[str, str]]:
    panel = {"id": "argent_open_budget", "label_key": "app_alert.action.argent_open_budget", "href": BUDGET_PANEL}
    params = {"item": item_name, "owner": owner or "-", "spent": spent, "cap": cap}
    actions = ({"id": "argent_request_budget", "label_key": "app_alert.action.argent_ask_owner" if owner else "app_alert.action.argent_request_budget", "method": "POST",
                "route": "/argent/budget/requests", "body": {"item_id": item_id}}, panel)
    return actions, params


def budget_hold(item_id: str, item_name: str, owner: str, spent: str, cap: str) -> None:
    actions, params = hold_actions(item_id, item_name, owner, spent, cap)
    service.raise_alert(BUDGET_HOLD_PREFIX + item_id, source=SOURCE, severity=K.SEV_ERROR, title_key="app_alert.argent.budget_hold.title",
                        detail_key="app_alert.argent.budget_hold.detail", sticky=True, auto_resolve=False, actions=actions, params=params)


def hold_lifted(item_id: str, item_name: str) -> None:
    service.resolve(BUDGET_HOLD_PREFIX + item_id)
    service.raise_alert(HOLD_LIFTED_PREFIX + item_id, source=SOURCE, severity=K.SEV_INFO, title_key="app_alert.argent.hold_lifted.title",
                        detail_key="app_alert.argent.hold_lifted.detail", params={"item": item_name}, auto_resolve=False)


OUTAGE_KEY, KEY_EXPIRING_KEY = "argent.outage", "argent.key_expiring"


def outage(count: int, reason: str) -> None:
    actions = ({"id": "argent_restart_direct", "label_key": "app_alert.action.argent_restart_direct", "method": "POST", "route": "/argent/outage/restart-direct"},)
    service.raise_alert(OUTAGE_KEY, source=SOURCE, severity=K.SEV_ERROR, title_key="app_alert.argent.outage.title", detail_key="app_alert.argent.outage.detail",
                        sticky=True, auto_resolve=False, actions=actions, params={"count": str(count), "reason": reason})


def outage_resolved() -> None:
    service.resolve(OUTAGE_KEY)


def key_expiring(count: int) -> None:
    service.raise_alert(KEY_EXPIRING_KEY, source=SOURCE, severity=K.SEV_WARN, title_key="app_alert.argent.key_expiring.title",
                        detail_key="app_alert.argent.key_expiring.detail", params={"count": str(count)}, auto_resolve=False)


def key_expiring_resolved() -> None:
    service.resolve(KEY_EXPIRING_KEY)


WRITEBACK_REVIEW_PREFIX, WRITEBACK_REFUSED_PREFIX, WRITEBACK_BLOCKED_PREFIX = "argent.writeback.review:", "argent.writeback.refused:", "argent.writeback.blocked_secret:"
WRITEBACK_PANEL = "#settings/features/argent/settings"


def writeback_review(row_id: int, item_title: str) -> None:
    service.raise_alert(f"{WRITEBACK_REVIEW_PREFIX}{row_id}", source=SOURCE, severity=K.SEV_INFO, title_key="app_alert.argent.writeback_review.title",
                        detail_key="app_alert.argent.writeback_review.detail", params={"item": item_title},
                        actions=({"id": "argent_open_writeback", "label_key": "app_alert.action.argent_open_writeback", "href": WRITEBACK_PANEL},), auto_resolve=False)


def writeback_review_resolved(row_id: int) -> None:
    service.resolve(f"{WRITEBACK_REVIEW_PREFIX}{row_id}")


def writeback_refused(row_id: int, item_title: str) -> None:
    service.raise_alert(f"{WRITEBACK_REFUSED_PREFIX}{row_id}", source=SOURCE, severity=K.SEV_INFO, title_key="app_alert.argent.writeback_refused.title",
                        detail_key="app_alert.argent.writeback_refused.detail", params={"item": item_title}, auto_resolve=False)


def writeback_blocked_secret(row_id: int, item_title: str) -> None:
    service.raise_alert(f"{WRITEBACK_BLOCKED_PREFIX}{row_id}", source=SOURCE, severity=K.SEV_WARN, title_key="app_alert.argent.writeback_blocked_secret.title",
                        detail_key="app_alert.argent.writeback_blocked_secret.detail", params={"item": item_title}, auto_resolve=False)


TRACKER_WINS_PREFIX = "argent.tracker_wins:"


def tracker_wins(item_id: str, card_title: str, what: str) -> None:
    service.raise_alert(TRACKER_WINS_PREFIX + item_id, source=SOURCE, severity=K.SEV_WARN, title_key="app_alert.argent.tracker_wins.title",
                        detail_key="app_alert.argent.tracker_wins.detail", params={"item": card_title, "what": what}, auto_resolve=False)
