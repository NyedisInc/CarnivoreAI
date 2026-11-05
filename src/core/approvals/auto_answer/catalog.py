
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from src.core.approvals.beast_grid import (  # noqa: F401
    ROW_BYPASS_ACCEPT, ROW_CHROME_ACCEPT, ROW_CHROME_DECLINE, ROW_DEV_CHANNELS, ROW_EXTERNAL_IMPORTS, ROW_FOLDER_TRUST, ROW_EFFORT_KEEP, ROW_MCP_SERVER, ROW_TRUST_PERMISSIONS, Policy,
)

RULE_DEV_CHANNELS: str = ROW_DEV_CHANNELS
RULE_FOLDER_TRUST: str = ROW_FOLDER_TRUST
RULE_EXTERNAL_IMPORTS: str = ROW_EXTERNAL_IMPORTS
RULE_CHROME_DECLINE: str = ROW_CHROME_DECLINE
RULE_TRUST_PERMISSIONS: str = ROW_TRUST_PERMISSIONS
RULE_BYPASS_ACCEPT: str = ROW_BYPASS_ACCEPT
RULE_CHROME_ACCEPT: str = ROW_CHROME_ACCEPT
RULE_MCP_SERVER: str = ROW_MCP_SERVER
RULE_EFFORT_KEEP: str = ROW_EFFORT_KEEP

RISK_LOW: str = "low"
RISK_MEDIUM: str = "medium"

SCOPE_PROJECTS: str = "projects"
SCOPE_EVERY: str = "every"
SCOPES: Tuple[str, ...] = (SCOPE_PROJECTS, SCOPE_EVERY)
DEFAULT_SCOPE: str = SCOPE_PROJECTS
SCOPE_SETTING: str = "trustScope"


@dataclass(frozen=True)
class RuleInfo:

    id: str
    setting_key: str
    risk: str
    screen: str


RULE_INFOS: Tuple[RuleInfo, ...] = (
    RuleInfo(RULE_DEV_CHANNELS, "devChannels", RISK_LOW, "dev_channels"),
    RuleInfo(RULE_FOLDER_TRUST, "folderTrust", RISK_MEDIUM, "trust"),
    RuleInfo(RULE_EXTERNAL_IMPORTS, "externalImports", RISK_MEDIUM, "external_imports"),
    RuleInfo(RULE_CHROME_ACCEPT, "chromeAccept", RISK_MEDIUM, "chrome_extension"),
    RuleInfo(RULE_CHROME_DECLINE, "chromeDecline", RISK_LOW, "chrome_extension"),
    RuleInfo(RULE_TRUST_PERMISSIONS, "trustPermissions", RISK_MEDIUM, "trust_permissions"),
    RuleInfo(RULE_BYPASS_ACCEPT, "bypassAccept", RISK_MEDIUM, "bypass_permissions"),
    RuleInfo(RULE_MCP_SERVER, "mcpServer", RISK_MEDIUM, "mcp_server"),
    RuleInfo(RULE_EFFORT_KEEP, "effortKeep", RISK_LOW, "effort_nudge"),
)

NEVER_ANSWERED: Tuple[str, ...] = (
    "login, oauth, api key, terms",
    "use this and all future mcp servers", "an mcp server not already installed", "plan approval", "askuserquestion", "any unrecognized screen",
)


def info_for(rule_id: str) -> RuleInfo:
    for info in RULE_INFOS:
        if info.id == rule_id:
            return info
    raise KeyError(rule_id)
