
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from src.core.transcript_corpus_discover import (
    CorpusEntry,
    DiscoveryOutcome,
    _iter_dir,
    _note,
)

CODEX_ROOT_ENV = "CLOUDE_CODEX_ROOT"

CODEX_SOURCE_PREFIX = "codex-sessions"

_ROLLOUT_UUID_RE = re.compile(
    r"^rollout-.*-("
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl$"
)


def default_codex_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def codex_conversation_id(source_path_or_name: str) -> Optional[str]:
    name = source_path_or_name.rsplit("/", 1)[-1]
    match = _ROLLOUT_UUID_RE.match(name)
    return match.group(1) if match is not None else None


def _walk_codex(directory: Path, prefix: str, outcome: DiscoveryOutcome) -> None:
    listing = _iter_dir(directory, outcome)
    if listing is None:
        return
    for item, kind in listing:
        if kind == "d":
            _walk_codex(item, f"{prefix}/{item.name}", outcome)
        elif kind == "f":
            if codex_conversation_id(item.name) is not None:
                outcome.entries.append(
                    CorpusEntry(
                        abs_path=item,
                        source_path=f"{prefix}/{item.name}",
                        kind="session",
                    )
                )
            else:
                outcome.unrecognised_count = _note(
                    outcome.unrecognised_count,
                    outcome.unrecognised_sample,
                    f"{prefix}/{item.name}",
                )


def discover_codex_detailed(codex_root: Path) -> DiscoveryOutcome:
    outcome = DiscoveryOutcome()
    codex_root = Path(codex_root)
    if not codex_root.is_dir():
        return outcome
    _walk_codex(codex_root, CODEX_SOURCE_PREFIX, outcome)
    return outcome


def discover_codex(codex_root: Path) -> List[CorpusEntry]:
    return discover_codex_detailed(codex_root).entries
