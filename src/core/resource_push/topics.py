
from __future__ import annotations

from typing import Tuple

BROWSERS = "browsers"
LAYOUTS = "layouts"
TOASTS = "toasts"
PROJECTS = "projects"
COMPANIES = "companies"
APPROVALS = "approvals"
PROVIDER_LEDGER = "provider_ledger"
ACCOUNT_SWITCH = "account_switch"
AUTO_SLEEP = "auto_sleep"
BEAST_MODE = "beast_mode"
SWARM_SWITCH = "swarm_switch"
RESTORE_OFFER = "restore_offer"
ITEM_SETTINGS = "item_settings"
CLIENT_BUILD = "client_build"

CATALOG = "catalog"

MACHINE_STATS = "machine_stats"

PANE_FACTS = "pane_facts"

GIT_STATUS = "git_status"

AI_CALLS = "ai_calls"
CUSTOM_DOMAIN = "custom_domain"
CROSSTALK = "crosstalk"
NOTIFICATION_SETTINGS = "notification_settings"
SWARM_ROSTER = "swarm_roster"
SWARM_AGENT = "swarm_agent"
BOOKMARKS = "bookmarks"


SWARM_NODE_ORDER = "swarm_node_order"

AUTOMATIONS = "automations"
AUTOMATION_RUNS = "automation_runs"
AUTOMATION_LOG = "automation_log"
AUTOMATION_COMMANDS = "automation_commands"
MODS = "mods"
LOCAL_SKILLS = "local_skills"

PACK_MACHINES = "pack_machines"

COMPUTERS = "computers"

PACK_ROSTER = "pack_roster"

PACK_RELAY = "pack_relay"
PACK_RELAY_OFFER = "pack_relay_offer"
PACK_SKILLS = "pack_skills"
PACK_OPS = "pack_ops"

STATS_FEED = "stats_feed"

THEMES = "themes"

MESSAGING = "messaging"
SESSION_TASKS = "session_tasks"
SESSION_TIMELINE = "session_timeline"
BROWSER_SELECT = "browser_select"
UI_SHOW = "ui_show"
BROWSER_PAGES = "browser_pages"
OPEN_FILES = "open_files"
ROW_LOOKS = "row_looks"
CPLUG_UI = "cplug_ui"
CPLUG_TOPIC = "cplug_topic"
ALL_KEY = "*"
KEY_SEPARATOR = ":"

PIPELINE = "pipeline"

SERVER_LOG = "server_log"

EXPORTS = "exports"

APP_UPDATE = "app_update"

DESKTOP_PREFERENCES = "desktop_preferences"

CATALOG_SUBMISSIONS = "catalog_submissions"

RESOURCE_TOPICS: Tuple[str, ...] = (
    BROWSERS, LAYOUTS, TOASTS, PROJECTS, APPROVALS, PROVIDER_LEDGER,
    ACCOUNT_SWITCH, AUTO_SLEEP, BEAST_MODE, SWARM_SWITCH, RESTORE_OFFER, ITEM_SETTINGS, CLIENT_BUILD, CATALOG, PANE_FACTS,
    MACHINE_STATS, CUSTOM_DOMAIN, CROSSTALK, NOTIFICATION_SETTINGS, COMPANIES,
    SWARM_ROSTER, SWARM_AGENT, GIT_STATUS, SWARM_NODE_ORDER, AUTOMATIONS, AUTOMATION_RUNS, BOOKMARKS, AUTOMATION_LOG, AUTOMATION_COMMANDS, MODS,
    LOCAL_SKILLS, THEMES, MESSAGING, SESSION_TASKS, SESSION_TIMELINE, PACK_MACHINES, COMPUTERS, PACK_ROSTER, PACK_RELAY, PACK_RELAY_OFFER, PACK_OPS, PACK_SKILLS,
    STATS_FEED, BROWSER_SELECT, UI_SHOW, BROWSER_PAGES, AI_CALLS, PIPELINE, OPEN_FILES, ROW_LOOKS, SERVER_LOG, EXPORTS,
    CPLUG_UI, CPLUG_TOPIC, APP_UPDATE, DESKTOP_PREFERENCES, CATALOG_SUBMISSIONS,
)


_all_topics: Tuple[str, ...] = ()


def all_topics() -> Tuple[str, ...]:
    global _all_topics
    if not _all_topics:
        from src.cplugs.host.runtime import topic_families  # noqa: PLC0415

        _all_topics = RESOURCE_TOPICS + topic_families()
    return _all_topics


def keyed(family: str, key: str) -> str:
    return f"{family}{KEY_SEPARATOR}{key}"


def family_of(topic: str) -> str:
    return topic.split(KEY_SEPARATOR, 1)[0]
