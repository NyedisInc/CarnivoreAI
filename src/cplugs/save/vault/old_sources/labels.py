
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import structlog

from src.cplugs.save.vault.old_sources import names

logger = structlog.get_logger()

JUNK_DATE, TRASH_DATE = "20260930", "20261016"
HIDING_PREFIXES: Tuple[str, ...] = ("junk-", "trash-", "review-")
REVIEWED_PREFIX, KEEP_VERDICT = "reviewed-", ":keep"
SECRETS_LABEL = "secrets-flagged"


class LabelError(ValueError):
    pass


def is_hidden(labels: Iterable[str]) -> bool:
    found = list(labels)
    if any(label.startswith(REVIEWED_PREFIX) and label.endswith(KEEP_VERDICT) for label in found):
        return False
    return any(label.startswith(HIDING_PREFIXES) for label in found)


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LabelError(f"{path}: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise LabelError(f"{path}: not a JSON object")
    return data


@dataclass
class LabelBook:

    by_conv: Dict[str, List[str]] = field(default_factory=dict)
    trashed: Set[str] = field(default_factory=set)
    row_folders: Mapping[str, str] = field(default_factory=dict)
    secret_rows: Set[str] = field(default_factory=set)

    @classmethod
    def load(cls, plan_applied: Optional[Path] = None, trash_manifests: Sequence[Path] = (), rows_file: Optional[Path] = None,
             secret_rows: Iterable[str] = ()) -> "LabelBook":
        book = cls(secret_rows=set(secret_rows))
        if plan_applied is not None:
            plan = _load_json(plan_applied)
            for entry in plan.get("conversations") or []:
                if entry.get("verdict") == "delete":
                    book._add_entry(entry, f"junk-{JUNK_DATE}:{','.join(entry.get('reasons') or [])}")
            for entry in plan.get("needs_review") or []:
                book._add_entry(entry, f"review-{JUNK_DATE}:{','.join(entry.get('reasons') or [])}")
            for entry in plan.get("kept") or []:
                book._add_entry(entry, f"kept-by-tree-{JUNK_DATE}")
        for manifest in trash_manifests:
            try:
                lines = Path(manifest).read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise LabelError(f"{manifest}: {type(exc).__name__}") from exc
            for line in lines:
                path = line.partition("  ")[2] if "  " in line else ""
                ident = names.identify(path)
                found = ident.conv if ident is not None else names.file_id(path)
                if found:
                    book.trashed.add(found)
        if rows_file is not None:
            book.row_folders = {str(r["folder"]): str(r["row"]) for r in _load_json(rows_file).get("rows") or []
                                if isinstance(r, dict) and r.get("folder") and r.get("row")}
        return book

    def _add(self, conv: Optional[str], label: str) -> None:
        if conv:
            self.by_conv.setdefault(str(conv), []).append(label)

    def _add_entry(self, entry: Mapping[str, object], label: str) -> None:
        self._add(entry.get("conversation_id"), label)  # type: ignore[arg-type]
        for item in entry.get("files") or []:  # type: ignore[attr-defined]
            file_id = names.file_id(str(item.get("path") or "")) if isinstance(item, dict) else None
            if file_id and file_id != entry.get("conversation_id"):
                self._add(file_id, label)

    def for_conversation(self, conv: str, enc: str = "") -> Tuple[str, ...]:
        out = list(self.by_conv.get(conv, ()))
        row = self.row_folders.get(enc)
        if conv in self.trashed:
            out.append(f"trash-{TRASH_DATE}" + (f":{row}" if row else ""))
        if row and row in self.secret_rows:
            out.append(SECRETS_LABEL)
        return tuple(out)
