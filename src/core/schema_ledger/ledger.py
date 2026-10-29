"""The rung ledger: one text line per applied-or-applicable schema rung, pinned to the code by a test.

WHY. On 2026-10-05 two branches claimed the same rung number and one silently skipped its tables
(``docs/DECISIONS.md``). A ledger is a plain text file, one line per rung, in rung order. Two branches that add rung N
both edit the line after the last one, so git reports a conflict at merge time instead of at first boot. A test
(:func:`check_ledger`) fails when the code's rungs and the file differ in either direction.

Format (``data/<ladder>.ledger``), lines starting ``#`` and blank lines ignored::

    <PREFIX><number> <sha256> <author> <slug>        e.g.   H48 3b1f...e9 - message-receipts

PREFIX is one letter per ladder (C core, H huddle, W work). Rung numbers start at 1 and have no gaps. ``author`` is
``-`` for a rung written before the ledger existed. The file only ever GROWS by appended lines; a changed hash on an
existing line is a failing test, never an automatic rewrite (:func:`append_missing` refuses it).

Both ladders feed this module through :class:`Rung` values, built by :func:`sql_rungs` (an SQL ladder) or
:func:`step_rungs` (the core ``STEPS`` table), so the future work ladder reuses it unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence

import structlog

from src.core.schema_ledger.errors import LedgerFormatError, LedgerMismatch
from src.core.schema_ledger.hashing import sql_rung_hash, step_rung_hash

logger = structlog.get_logger()

DATA_DIR = Path(__file__).resolve().parent / "data"
_LINE = re.compile(r"^(?P<prefix>[A-Z])(?P<number>[1-9][0-9]*) (?P<sha>[0-9a-f]{64}) (?P<author>\S+) (?P<slug>[a-z0-9][a-z0-9-]*)$")
_SLUG_MAX = 48


@dataclass(frozen=True)
class Rung:
    """One schema rung as the code defines it. Fields: number (int, 1-based, the version it produces), sha256 (str), slug (str)."""

    number: int
    sha256: str
    slug: str


@dataclass(frozen=True)
class LedgerLine:
    """One parsed ledger line. Fields: prefix (str), number (int), sha256 (str), author (str), slug (str)."""

    prefix: str
    number: int
    sha256: str
    author: str
    slug: str


@dataclass(frozen=True)
class LadderSpec:
    """A ladder a ledger covers.

    Fields: name (str, e.g. ``huddle``); prefix (str, one capital letter); path (Path, its ledger file);
    rungs (callable returning the code's rungs, evaluated lazily so importing a spec imports no ladder).
    """

    name: str
    prefix: str
    path: Path
    rungs: Callable[[], Sequence[Rung]]


def slugify(text: str) -> str:
    """A kebab-case slug of the first words of ``text``. Inputs: text (str). Output: str, never empty ('rung').
    Example: slugify("Messaging: unconfirmed delivery (table rebuild)") -> 'messaging-unconfirmed-delivery-table-rebuild'"""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:_SLUG_MAX].rstrip("-")
    return slug or "rung"


def sql_rungs(scripts: Sequence[str], slugs: Optional[Sequence[str]] = None) -> List[Rung]:
    """Rungs of an SQL ladder: script ``i`` (0-based) is rung ``i + 1``.

    Inputs: scripts (sequence of SQL text); slugs (sequence of str, same length, or None for ``rung-<n>``).
    Output: list[Rung]. Example: sql_rungs(("CREATE TABLE a (x);",)) -> [Rung(1, '<sha>', 'rung-1')]
    """
    return [Rung(i + 1, sql_rung_hash(sql), slugs[i] if slugs else f"rung-{i + 1}") for i, sql in enumerate(scripts)]


def step_rungs(steps: Mapping[int, Callable[..., object]]) -> List[Rung]:
    """Rungs of a Python step table keyed by FROM version (``db_steps.STEPS``): key ``k`` is rung ``k + 1``.

    Inputs: steps ({from_version: function}). Output: list[Rung] in rung order; the slug is the function's docstring
    summary. Example: step_rungs({0: _step_v0_to_v1}) -> [Rung(1, '<sha>', 'create-the-v1-tables...')]
    """
    out = []
    for key in sorted(steps):
        doc = (steps[key].__doc__ or steps[key].__name__).strip().splitlines()[0]
        out.append(Rung(key + 1, step_rung_hash(steps[key]), slugify(doc)))
    return out


def parse_ledger(path: Path, prefix: str) -> List[LedgerLine]:
    """Read a ledger file. Inputs: path (Path), prefix (str) - every line must carry it.
    Output: list[LedgerLine] in file order. Raises: LedgerFormatError (bad line, wrong prefix, number out of sequence,
    unreadable file)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LedgerFormatError(f"{path}: cannot read the ledger ({exc})") from exc
    lines: List[LedgerLine] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.startswith("#"):
            continue
        match = _LINE.match(raw)
        if match is None:
            raise LedgerFormatError(f"{path}:{lineno}: not '<PREFIX><n> <sha256> <author> <slug>': {raw[:80]!r}")
        entry = LedgerLine(match["prefix"], int(match["number"]), match["sha"], match["author"], match["slug"])
        if entry.prefix != prefix:
            raise LedgerFormatError(f"{path}:{lineno}: prefix {entry.prefix} in a {prefix} ledger")
        if entry.number != len(lines) + 1:
            raise LedgerFormatError(f"{path}:{lineno}: rung {entry.number} where {len(lines) + 1} was expected (a gap or a repeat)")
        lines.append(entry)
    return lines


def diff_ledger(spec: LadderSpec, entries: Sequence[LedgerLine], rungs: Sequence[Rung]) -> List[str]:
    """Every difference between a ledger and the code, as readable sentences (empty list means they agree).

    Inputs: spec (LadderSpec), entries (parsed lines), rungs (the code's). Output: list[str].
    """
    problems: List[str] = []
    by_number = {r.number: r for r in rungs}
    for entry in entries:
        rung = by_number.get(entry.number)
        label = f"{spec.prefix}{entry.number}"
        if rung is None:
            problems.append(f"{label}: in the ledger but the {spec.name} code has no such rung (ledger {entry.sha256[:12]})")
        elif rung.sha256 != entry.sha256:
            problems.append(f"{label}: the {spec.name} rung changed; ledger {entry.sha256[:12]}, code {rung.sha256[:12]}")
    ledgered = {e.number for e in entries}
    for rung in rungs:
        if rung.number not in ledgered:
            problems.append(f"{spec.prefix}{rung.number}: the {spec.name} code has this rung ({rung.sha256[:12]}) but the ledger has no line")
    return problems


def check_ledger(spec: LadderSpec) -> None:
    """Fail when the code's rungs and the ledger disagree in either direction.

    Inputs: spec (LadderSpec). Output: None. Raises: LedgerMismatch (every difference listed, plus how to fix),
    LedgerFormatError (the file is malformed).
    """
    problems = diff_ledger(spec, parse_ledger(spec.path, spec.prefix), spec.rungs())
    if problems:
        raise LedgerMismatch(
            f"the {spec.name} ladder and {spec.path.name} disagree:\n  " + "\n  ".join(problems)
            + f"\nA rung that already shipped must never change. A new rung needs its line appended: "
              f"python3 scripts/schema_ledger/cli.py write {spec.name} --author <you> (see docs/maintenance-history.md).")


def render_line(prefix: str, rung: Rung, author: str) -> str:
    """One ledger line. Inputs: prefix (str), rung (Rung), author (str, no spaces). Output: str without newline."""
    return f"{prefix}{rung.number} {rung.sha256} {author} {rung.slug}"


def append_missing(spec: LadderSpec, author: str) -> List[str]:
    """Append a line for every code rung the ledger lacks; never edit or reorder an existing line.

    Inputs: spec (LadderSpec), author (str, no whitespace). Output: list[str] of the lines appended.
    Raises: LedgerMismatch when an existing line differs from the code (a shipped rung changed) or the ledger holds
    a rung the code lacks; LedgerFormatError; OSError on write.
    """
    entries = parse_ledger(spec.path, spec.prefix) if spec.path.exists() else []
    rungs = spec.rungs()
    existing = [p for p in diff_ledger(spec, entries, rungs) if "has no line" not in p]
    if existing:
        raise LedgerMismatch("refusing to append over a changed or removed rung:\n  " + "\n  ".join(existing))
    have = {e.number for e in entries}
    new = [render_line(spec.prefix, r, author) for r in rungs if r.number not in have]
    if new:
        with spec.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(new) + "\n")
        logger.info("schema_ledger_appended", ladder=spec.name, rungs=len(new))
    return new
