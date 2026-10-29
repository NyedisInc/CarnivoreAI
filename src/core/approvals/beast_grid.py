
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple

MODE_OFF: str = "off"
MODE_ON: str = "on"
MODES: Tuple[str, ...] = (MODE_OFF, MODE_ON)

KIND_STARTUP: str = "startup"
KIND_PROMPT: str = "prompt"
KIND_WRITES: str = "writes"

ROW_DEV_CHANNELS: str = "dev_channels"
ROW_FOLDER_TRUST: str = "folder_trust"
ROW_EXTERNAL_IMPORTS: str = "external_imports"
ROW_CHROME_DECLINE: str = "chrome_decline"
ROW_CLAUDE_PERMISSION: str = "claude_permission"
ROW_CODEX_APPROVAL: str = "codex_approval"
ROW_AGENT_WRITES: str = "agent_writes"


@dataclass(frozen=True)
class RowInfo:

    id: str
    base: str
    kind: str
    default_off: bool
    default_on: bool

    def cell(self, mode: str) -> str:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        return f"{self.base}{'On' if mode == MODE_ON else 'Off'}"

    def default(self, mode: str) -> bool:
        return self.default_on if mode == MODE_ON else self.default_off


ROWS: Tuple[RowInfo, ...] = (
    RowInfo(ROW_DEV_CHANNELS, "devChannels", KIND_STARTUP, True, True),
    RowInfo(ROW_FOLDER_TRUST, "folderTrust", KIND_STARTUP, True, True),
    RowInfo(ROW_EXTERNAL_IMPORTS, "externalImports", KIND_STARTUP, True, True),
    RowInfo(ROW_CHROME_DECLINE, "chromeDecline", KIND_STARTUP, True, True),
    RowInfo(ROW_CLAUDE_PERMISSION, "claudePermission", KIND_PROMPT, False, True),
    RowInfo(ROW_CODEX_APPROVAL, "codexApproval", KIND_PROMPT, False, True),
    RowInfo(ROW_AGENT_WRITES, "agentWrites", KIND_WRITES, False, True),
)

UNCONFIRMED_ROWS: Tuple[str, ...] = (ROW_CLAUDE_PERMISSION, ROW_CODEX_APPROVAL, ROW_AGENT_WRITES)

LOCKED_ROWS: Tuple[str, ...] = (
    "questions", "free_text", "plan_approval", "widening_yes", "other_startup", "always_waits", "own_dialog", "loop_breaker", "inbox_tools",
)


class Policy(Protocol):

    def handles(self, row_id: str) -> bool:
        pass

    def rule_on(self, rule_id: str) -> bool:
        pass

    def ticked_in(self, row_id: str, mode: str) -> bool:
        pass

    def trust_scope(self) -> str:
        pass


def row_for(row_id: str) -> RowInfo:
    for row in ROWS:
        if row.id == row_id:
            return row
    raise KeyError(row_id)


def cell_defaults() -> dict:
    return {row.cell(mode): row.default(mode) for row in ROWS for mode in MODES}
