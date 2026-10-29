
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.plan_files import ORIGIN_VAULT, PlannedFile, enc_of
from src.cplugs.sdk import crate_sources as cs
from src.core.deepsearch import fallback_hook as fb

_KEYS: Dict[str, str] = {
    P.R_TRANSCRIPT: "claude/transcript", P.R_SUBAGENT: f"claude/{P.FOLDER_CONVERSATION}",
    P.R_TOOL_RESULT: f"claude/{P.FOLDER_CONVERSATION}", P.R_CONV_FILE: f"claude/{P.FOLDER_CONVERSATION}",
    P.R_FILE_HISTORY: "claude/file_history", P.R_ROLLOUT: "codex/codex_rollout",
}
_REASON = "read from the backup vault; the disk no longer has it"


@dataclass
class VaultWalk:

    files: List[PlannedFile] = field(default_factory=list)
    blockers: List[Tuple[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    reconcile: List[Dict[str, Any]] = field(default_factory=list)
    troubled: Set[str] = field(default_factory=set)


def home_of_plugin(plugin_id: str) -> str:
    return f"{P.HOME_PLUGIN_PREFIX}{plugin_id}"


def same_place(home: str, rel: str) -> Tuple[str, str]:
    parts = rel.split("/")
    if home == P.HOME_CLAUDE and parts[0] == "projects" and len(parts) >= 3:
        return home, "/".join(["projects", "*"] + parts[2:])
    return home, rel


def _lines_only(source: Any, conversation: str) -> bool:
    try:
        return bool(source.files(conversation))
    except fb.FallbackUnavailable:
        return True


class _Planner:

    def __init__(self, disk: Sequence[PlannedFile], refused: Set[str], homes: P.HomesView, variant: str,
                 sources: Sequence[Any]) -> None:
        self.on_disk = {same_place(f.home, f.rel) for f in disk}
        self.mains = {f.conversation_id for f in disk if f.role in P.MAIN_ROLES and f.conversation_id} | set(refused)
        self.homes, self.variant, self.sources = homes, variant, list(sources)
        self.walk = VaultWalk()

    def _trouble(self, conversation: str, gone: bool, code: str, detail: str) -> None:
        if gone:
            self.walk.blockers.append((code, detail))
            self.walk.troubled.add(conversation)
        else:
            self.walk.warnings.append(f"{code}: {detail}; only what is on disk is carried")

    def ask(self, conversation: str) -> None:
        gone = conversation not in self.mains
        for source in self.sources:
            try:
                if not hasattr(source, "entries"):
                    if gone and _lines_only(source, conversation):
                        self._trouble(conversation, gone, K.B_VAULT_INCOMPLETE,
                                      f"the backup holding conversation {conversation} lists its transcript lines only, "
                                      "not every file; turn the backup plugin off and on so it registers the full "
                                      "source, then export again")
                        return
                    continue
                entries = source.entries(conversation)
            except OSError as exc:
                self._trouble(conversation, gone, K.B_VAULT,
                              f"the backup holding conversation {conversation} cannot be reached ({type(exc).__name__})")
                return
            except fb.FallbackUnavailable as exc:
                self._trouble(conversation, gone, K.B_VAULT_INCOMPLETE,
                              f"the backup of conversation {conversation} cannot be read ({exc})")
                return
            if entries:
                self._carry(conversation, gone, entries)
                return

    def _carry(self, conversation: str, gone: bool, entries: Sequence[fb.FallbackEntry]) -> None:
        what = f"vault:{conversation}"
        found: List[PlannedFile] = []
        for entry in entries:
            key = _KEYS.get(entry.role)
            if key is None or entry.home not in (P.HOME_CLAUDE, P.HOME_CODEX) or not entry.rel:
                continue
            rule = P.POLICY[key]
            if (rule.own if self.variant == P.OWN else rule.share) != P.CARRY:
                continue
            if same_place(entry.home, entry.rel) in self.on_disk:
                continue
            placed = self.homes.place(entry.source_path) if entry.source_path else None
            index = placed[1] if placed is not None and placed[0] == entry.home else 0
            found.append(PlannedFile(
                key=key, role=entry.role, home=entry.home, home_index=index, rel=entry.rel, source_path=None,
                conversation_id=conversation, family=entry.family, enc_folder=enc_of(entry.home, entry.rel),
                line_mode=P.line_mode(entry.role, os.path.basename(entry.rel)), size=int(entry.length),
                origin=ORIGIN_VAULT, vault=(entry.signature, entry.rel), mtime_ns=int(entry.mtime_ns or 0),
                mode=int(entry.mode or 0) & 0o7777, artifact=what))
            if not gone:
                self.walk.warnings.append(f"{K.W_VAULT_FILE}: {entry.rel} of conversation {conversation} is no longer on "
                                          "disk; it is carried from the backup vault")
        if not found:
            return
        if gone:
            self.walk.warnings.append(f"{K.W_VAULT_FILE}: conversation {conversation} is no longer on disk; its "
                                      f"{len(found)} files are carried from the backup vault")
        self.walk.files += found
        row = {"store": found[0].family or found[0].home, "kind": cs.KIND_FILE, "inventory_count": len(found),
               "inventory_size": sum(f.size for f in found), "decision": P.CARRY, "reason": _REASON}
        if self.variant == P.OWN:
            row["what"] = what
        self.walk.reconcile.append(row)


def plan_vault(scope_ids: Sequence[str], disk: Sequence[PlannedFile], refused: Set[str], homes: P.HomesView,
               variant: str, sources: Optional[Sequence[Any]] = None) -> VaultWalk:
    planner = _Planner(disk, refused, homes, variant, cs.fallback_sources() if sources is None else sources)
    if planner.sources:
        for conversation in sorted(scope_ids):
            planner.ask(conversation)
    return planner.walk


class VaultOpener:

    def __init__(self, sources: Optional[Sequence[Any]] = None) -> None:
        self._sources = list(cs.fallback_sources() if sources is None else sources)
        self._entries: Dict[Tuple[int, str], List[fb.FallbackEntry]] = {}

    def open(self, pf: PlannedFile) -> fb.FallbackReader:
        conversation, (signature, rel) = str(pf.vault_conversation or pf.conversation_id), pf.vault or ("", "")
        if pf.vault_point:
            return self._open_point(pf, conversation, rel)
        for index, source in enumerate(self._sources):
            if not hasattr(source, "entries"):
                continue
            try:
                held = self._entries.get((index, conversation))
                if held is None:
                    held = self._entries[(index, conversation)] = list(source.entries(conversation))
                if any(e.rel == rel and e.signature == signature for e in held):
                    return source.entry_reader(conversation, rel)
            except (OSError, fb.FallbackUnavailable) as exc:
                raise cs.SourceUnavailable(f"the backup of conversation {conversation} could not be read for {rel} "
                                           f"({type(exc).__name__})") from exc
        raise cs.SourceUnavailable(f"the backup no longer holds {rel} of conversation {conversation} as planned")

    def _open_point(self, pf: PlannedFile, conversation: str, rel: str) -> fb.FallbackReader:
        for source in self._sources:
            if not hasattr(source, "point_entry_reader"):
                continue
            try:
                reader = source.point_entry_reader(conversation, pf.vault_point, rel)
            except (OSError, fb.FallbackUnavailable) as exc:
                raise cs.SourceUnavailable(f"the backup point {pf.vault_point} of conversation {conversation} could not be read for "
                                           f"{rel} ({type(exc).__name__})") from exc
            if getattr(reader, "length", pf.size) != pf.size:
                raise cs.SourceUnavailable(f"the backup point {pf.vault_point} of conversation {conversation} no longer holds {rel} as planned")
            return reader
        raise cs.SourceUnavailable(f"the backup holding point {pf.vault_point} of conversation {conversation} is not available")
