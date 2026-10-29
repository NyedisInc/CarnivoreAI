
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple, Union

from src.core.transcript_contract import RangeLine

EV_APPENDED: str = "appended"
EV_FILE_REWRITTEN: str = "file_rewritten"
EV_TRUNCATED: str = "truncated"
EV_CONVERSATION_REMOVED: str = "conversation_removed"
EV_FILE_REMOVED: str = "file_removed"

FAMILY_CLAUDE: str = "claude"
FAMILY_CODEX: str = "codex"
FILE_CONVERSATION: str = "conversation"
FILE_SUBAGENT: str = "subagent"

PLUGIN_DIR: str = "pipeline-plugins"
CURSORS_TABLE: str = "plugin_cursors"
META_TABLE: str = "plugin_meta"
META_SCHEMA_VERSION: str = "schema_version"
META_CREATED_AT: str = "created_at"
META_LAST_DELIVERY_AT: str = "last_delivery_at"
ID_PATTERN: str = r"^[a-z][a-z0-9_]{1,39}$"
DB_NAME_PATTERN: str = r"^[a-z][a-z0-9_-]{1,59}\.db$"

INHERIT_HEAD: str = "head"
INHERIT_OPEN: str = "open"
INHERIT_CLOSED: str = "closed"

SLICE_BYTES: int = 4 * 1024 * 1024
RUN_BUDGET_BYTES: int = 64 * 1024 * 1024
READ_TIMEOUT_SECONDS: float = 30.0
ERROR_CHARS: int = 300
BULK_REST_RATIO: float = 0.5
BULK_REST_MAX_SECONDS: float = 5.0


@dataclass(frozen=True)
class Lineage:

    parent_conversation_id: str
    edge_kind: str
    fork_uuid: Optional[str] = None


@dataclass(frozen=True)
class Appended:

    conversation_id: str
    family: str
    path: str
    file_kind: str
    start: int
    end: int
    lines: Tuple[RangeLine, ...]
    inherited_start: int
    inherited_end: int
    lineage: Optional[Lineage]
    trigger: str

    name: str = EV_APPENDED

    def inherited(self, line: RangeLine) -> bool:
        return self.inherited_start <= line.offset < self.inherited_end

    @property
    def own_lines(self) -> Tuple[RangeLine, ...]:
        return tuple(line for line in self.lines if not self.inherited(line))


@dataclass(frozen=True)
class FileReset:

    name: str
    conversation_id: str
    family: str
    path: str
    file_kind: str
    consumed_end: int
    size: int


@dataclass(frozen=True)
class ConversationRemoved:

    conversation_id: str
    paths: Tuple[str, ...]

    name: str = EV_CONVERSATION_REMOVED


@dataclass(frozen=True)
class FileRemoved:

    conversation_id: str
    path: str
    file_kind: str

    name: str = EV_FILE_REMOVED


Event = Union[Appended, FileReset, ConversationRemoved, FileRemoved]

Migrate = Callable[[sqlite3.Connection, int], None]
OnEvents = Callable[[sqlite3.Connection, Tuple[Event, ...]], None]
CarryOver = Callable[[sqlite3.Connection, sqlite3.Connection], None]
OnLifecycle = Callable[[sqlite3.Connection, str, str, float, Mapping[str, Any]], None]
ExportRollup = Callable[[sqlite3.Connection, int], Dict[str, Any]]
ImportRollup = Callable[[str, Mapping[str, Any]], None]
RebuildSeed = Callable[[sqlite3.Connection], None]
OnCaughtUp = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class CatchUp:

    ready: bool
    bytes_read: int = 0


CatchUpHook = Callable[[sqlite3.Connection, "Appended", int], CatchUp]


class PluginContractError(ValueError):
    pass


@dataclass(frozen=True)
class Plugin:

    id: str
    db_name: str
    schema_version: int
    migrate: Migrate
    on_events: OnEvents
    carry_over: Optional[CarryOver] = None
    families: FrozenSet[str] = field(default_factory=lambda: frozenset({FAMILY_CLAUDE, FAMILY_CODEX}))
    file_kinds: FrozenSet[str] = field(default_factory=lambda: frozenset({FILE_CONVERSATION, FILE_SUBAGENT}))
    on_lifecycle: Optional[OnLifecycle] = None
    export_rollup: Optional[ExportRollup] = None
    import_rollup: Optional[ImportRollup] = None
    rebuild: Optional[RebuildSeed] = None
    on_caught_up: Optional[OnCaughtUp] = None
    in_state_dir: bool = False
    catch_up: Optional[CatchUpHook] = None
    file_kinds_fn: Optional[Callable[[], FrozenSet[str]]] = None
    before_scan: Optional[Callable[[sqlite3.Connection], None]] = None
    per_file_removal: bool = False

    def reads(self, family: str, file_kind: Optional[str] = None) -> bool:
        kinds = self.file_kinds_fn() if self.file_kinds_fn is not None else self.file_kinds
        return family in self.families and (file_kind is None or file_kind in kinds)

    def reads_snapshot(self) -> Callable[[str, Optional[str]], bool]:
        kinds = self.file_kinds_fn() if self.file_kinds_fn is not None else self.file_kinds
        families = self.families

        def reads(family: str, file_kind: Optional[str] = None) -> bool:
            return family in families and (file_kind is None or file_kind in kinds)

        return reads


def validate(plugin: Plugin) -> None:
    if not re.match(ID_PATTERN, plugin.id or ""):
        raise PluginContractError(f"plugin id {plugin.id!r} must match {ID_PATTERN}")
    if not re.match(DB_NAME_PATTERN, plugin.db_name or ""):
        raise PluginContractError(f"plugin {plugin.id}: db_name {plugin.db_name!r} must match {DB_NAME_PATTERN}")
    if not isinstance(plugin.schema_version, int) or isinstance(plugin.schema_version, bool) or plugin.schema_version < 1:
        raise PluginContractError(f"plugin {plugin.id}: schema_version must be a positive int")
    if not callable(plugin.migrate) or not callable(plugin.on_events):
        raise PluginContractError(f"plugin {plugin.id}: migrate and on_events must be callable")
    if not plugin.families or not plugin.families <= {FAMILY_CLAUDE, FAMILY_CODEX}:
        raise PluginContractError(f"plugin {plugin.id}: families must be claude and/or codex")
    if not plugin.file_kinds or not plugin.file_kinds <= {FILE_CONVERSATION, FILE_SUBAGENT}:
        raise PluginContractError(f"plugin {plugin.id}: file_kinds must be conversation and/or subagent")


def validate_all(plugins: Iterable[Plugin]) -> None:
    ids, names = set(), set()
    for plugin in plugins:
        validate(plugin)
        if plugin.id in ids or plugin.db_name in names:
            raise PluginContractError(f"plugin {plugin.id}: id or db_name used twice")
        ids.add(plugin.id)
        names.add(plugin.db_name)
