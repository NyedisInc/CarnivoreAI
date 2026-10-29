
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
    """Extract the uuidv7 conversation id from a rollout path or filename.

    Description: pure string arithmetic over the filename, no file read -
      the conversation id is the uuidv7 the codex rollout filename ends
      with. A name that is not a rollout, or a rollout with no uuid, has
      no id and returns None rather than a guess.
    Inputs: source_path_or_name (str) - a full ``source_path``
      (``codex-sessions/2026/09/05/rollout-...jsonl``), an absolute path,
      or a bare filename.
    Output: str | None - the uuidv7, or None when the name does not match
      the rollout shape.
    Example:
      codex_conversation_id("codex-sessions/2026/09/05/"
      "rollout-2026-09-05T19-21-32-01a06e76-0273-75b2-ac59-5838bf03fa3b.jsonl")
      -> "01a06e76-0273-75b2-ac59-5838bf03fa3b"
    """
    name = source_path_or_name.rsplit("/", 1)[-1]
    match = _ROLLOUT_UUID_RE.match(name)
    return match.group(1) if match is not None else None


def _walk_codex(directory: Path, prefix: str, outcome: DiscoveryOutcome) -> None:
    """Collect every ``rollout-*.jsonl`` at ANY depth under one directory.

    Description: recursive on purpose. Codex nests rollouts under
      ``YYYY/MM/DD/`` and could nest deeper; depth is not part of any
      decision here (the conversation id comes from the filename, not the
      path), so walking deeper adds rollouts without adding a guess. A
      ``.jsonl`` that is not a rollout, or any other file, is
      ``unrecognised`` - not a transcript, never ingested. A directory
      that cannot be listed is ``unreadable`` via :func:`_iter_dir`.
    Inputs: directory (Path), prefix (str - the ``source_path`` prefix for
      items directly inside ``directory``), outcome (DiscoveryOutcome,
      mutated).
    Output: None.
    Example: _walk_codex(Path("/c/sessions"), "codex-sessions", outcome)
    """
    listing = _iter_dir(directory, outcome)
    if listing is None:
        return
    for item in listing:
        if item.is_dir():
            _walk_codex(item, f"{prefix}/{item.name}", outcome)
        elif item.is_file():
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
