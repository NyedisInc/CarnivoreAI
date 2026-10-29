
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from src.core.approvals.beast_grid import (  # noqa: F401
    ROW_CHROME_DECLINE, ROW_DEV_CHANNELS, ROW_EXTERNAL_IMPORTS, ROW_FOLDER_TRUST, Policy,
)

RULE_DEV_CHANNELS: str = ROW_DEV_CHANNELS
RULE_FOLDER_TRUST: str = ROW_FOLDER_TRUST
RULE_EXTERNAL_IMPORTS: str = ROW_EXTERNAL_IMPORTS
RULE_CHROME_DECLINE: str = ROW_CHROME_DECLINE

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
    RuleInfo(RULE_CHROME_DECLINE, "chromeDecline", RISK_LOW, "chrome_extension"),
)

NEVER_ANSWERED: Tuple[str, ...] = (
    "folder trust, permissions variant", "bypass permissions acceptance", "claude in chrome yes", "login, oauth, api key, terms",
    "use this and all future mcp servers", "plan approval", "askuserquestion", "any unrecognized screen",
)


def info_for(rule_id: str) -> RuleInfo:
    for info in RULE_INFOS:
        if info.id == rule_id:
            return info
    raise KeyError(rule_id)
