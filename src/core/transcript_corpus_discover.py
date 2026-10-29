
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

HASH_CHUNK_SIZE = 4 * 1024 * 1024

SUBAGENTS_DIRNAME = "subagents"

OUTCOME_SAMPLE_LIMIT = 50


@dataclass
class CorpusEntry:

    abs_path: Path
    source_path: str
    kind: str


def default_corpus_root() -> Path:
    return Path.home() / ".claude" / "projects"


@dataclass
class DiscoveryOutcome:
    """What one corpus walk found, refused, and could not look at.

    Description: THE THREE-OUTCOME RULE APPLIED TO DISCOVERY ITSELF.
      Before this existed :func:`discover_corpus` returned a bare list,
      so "this path holds no transcripts", "this path holds files whose
      shape I refuse to classify" and "I could not read this directory
      at all" were the same answer: absence from the list. That is
      exactly how 442 real workflow transcripts sat outside the archive
      for months with every ingest report reading green - the scanner
      was not failing to walk them, it was walking past them and saying
      nothing.
    Inputs: constructed only by :func:`discover_corpus_detailed`.
    Output: n/a (data holder).
    """

    entries: List[CorpusEntry] = field(default_factory=list)
    unrecognised_count: int = 0
    unrecognised_sample: List[str] = field(default_factory=list)
    # could not
    unreadable_count: int = 0
    unreadable_sample: List[Dict[str, str]] = field(default_factory=list)


def _note(count: int, sample: list, value) -> int:
    if len(sample) < OUTCOME_SAMPLE_LIMIT:
        sample.append(value)
    return count + 1


def _iter_dir(path: Path, outcome: DiscoveryOutcome) -> Optional[List[Path]]:
    """List one directory, or record that it could not be listed.

    Description: an ``OSError`` here is the third outcome, not an empty
      directory - it is recorded on the outcome and the caller skips
      that branch rather than reporting it as "nothing found".
    Inputs: path (Path), outcome (DiscoveryOutcome, mutated).
    Output: list[Path] sorted | None when the listing failed.
    Example: _iter_dir(Path("/nope"), DiscoveryOutcome()) -> None
    """
    try:
        return sorted(path.iterdir())
    except OSError as exc:
        outcome.unreadable_count = _note(
            outcome.unreadable_count,
            outcome.unreadable_sample,
            {"path": str(path), "reason": str(exc)},
        )
        return None


def walk_subagents(
    sub: Path, prefix: str, outcome: DiscoveryOutcome,
) -> None:
    """Collect every ``*.jsonl`` at ANY depth under one ``subagents/`` dir.

    Description: RECURSIVE ON PURPOSE, and the recursion is what closes
      the workflows gap. Claude Code nests workflow subagent transcripts
      at ``subagents/workflows/<wf_id>/*.jsonl`` (and iCloud forks that
      directory into ``workflows 2``), which the previous one-level
      listing could not see. Depth is not part of the rooting decision -
      ``<slug>/<uuid>/`` is already fixed by the two path segments above
      this call - so walking deeper adds transcripts without adding a
      single guess.

      THE SUFFIX FILTER IS LOAD-BEARING. ``tool-results/`` artifacts
      (.txt, .pdf, .jpg) live beside these trees and are NOT transcripts;
      the archive's byte-exactness guarantees are built on JSONL. They
      are counted as ``unrecognised``, never ingested.
    Inputs: sub (Path - the ``subagents`` directory), prefix (str -
      ``<slug>/<uuid>/subagents``), outcome (DiscoveryOutcome, mutated).
    Output: None.
    Example: walk_subagents(Path("/c/s/u/subagents"), "s/u/subagents", o)
    """
    listing = _iter_dir(sub, outcome)
    if listing is None:
        return
    for item in listing:
        if item.is_file():
            if item.suffix == ".jsonl":
                outcome.entries.append(
                    CorpusEntry(
                        abs_path=item,
                        source_path=f"{prefix}/{item.name}",
                        kind="subagent",
                    )
                )
            else:
                outcome.unrecognised_count = _note(
                    outcome.unrecognised_count,
                    outcome.unrecognised_sample,
                    f"{prefix}/{item.name}",
                )
        elif item.is_dir():
            walk_subagents(item, f"{prefix}/{item.name}", outcome)


def discover_corpus_detailed(corpus_root: Path) -> DiscoveryOutcome:
    outcome = DiscoveryOutcome()
    corpus_root = Path(corpus_root)
    if not corpus_root.is_dir():
        return outcome

    top = _iter_dir(corpus_root, outcome)
    if top is None:
        return outcome
    for slug_dir in top:
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        listing = _iter_dir(slug_dir, outcome)
        if listing is None:
            continue
        for item in listing:
            if item.is_file():
                if item.suffix == ".jsonl":
                    outcome.entries.append(
                        CorpusEntry(
                            abs_path=item,
                            source_path=f"{slug}/{item.name}",
                            kind="session",
                        )
                    )
                else:
                    outcome.unrecognised_count = _note(
                        outcome.unrecognised_count,
                        outcome.unrecognised_sample,
                        f"{slug}/{item.name}",
                    )
            elif item.is_dir():
                sub = item / SUBAGENTS_DIRNAME
                if not sub.is_dir():
                    outcome.unrecognised_count = _note(
                        outcome.unrecognised_count,
                        outcome.unrecognised_sample,
                        f"{slug}/{item.name}",
                    )
                    continue
                walk_subagents(
                    sub, f"{slug}/{item.name}/{SUBAGENTS_DIRNAME}", outcome,
                )
    return outcome


def discover_corpus(corpus_root: Path) -> List[CorpusEntry]:
    return discover_corpus_detailed(corpus_root).entries


def hash_file(path: Path) -> tuple:
    """Stream-hash a file without holding it fully in memory.

    Description: the pre-ingest identity check - reads the file once in
      bounded chunks purely to compute sha256 and size, so the
      already-present decision can be made before the (separate,
      heavier) actual ingest read happens.
    Inputs: path (Path).
    Output: tuple[str, int] - (sha256 hex digest, byte length).
    Raises: OSError - the file could not be opened or read.
    Example: hash_file(Path("x.jsonl")) -> ("abc123...", 4096)
    """
    hasher = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def mtime_iso(path: Path) -> Optional[str]:
    try:
        ts = os.stat(path).st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
