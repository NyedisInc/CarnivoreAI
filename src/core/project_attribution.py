"""Matching one session's working directory onto a known project root.

WHY THIS IS ITS OWN MODULE. The rule was previously six lines inside
src/core/session_import_mapping.py, which is the first-run import's pure
mapping layer. Attribution is not an import concern: the adopt path, the
create path and any future re-probe all have to answer the same question
the same way, and a rule that lives inside one caller grows a second,
divergent copy the first time a second caller needs it. That is exactly
how the ownership badge came to disagree with itself across three call
sites. One rule, one module, one set of tests.

THE THIRD OUTCOME IS THE POINT, AND IT IS THE PART THAT WAS BROKEN.

  ``derived_deepest``  we read a working directory and it sits inside a
                       known project root. The deepest root wins.
  ``none``             we READ a working directory and it sits inside no
                       known project. A complete, actionable answer: the
                       session genuinely belongs to no project, and the
                       user can create one or leave it alone.
  ``unknown``          we could not read the working directory, or read
                       something we cannot situate. NOT an answer. Lands
                       the row in NEEDS ATTENTION (design 4.3).

``none`` and ``unknown`` are different claims and only one of them is a
measurement. A row is NEVER guessed onto the nearest project, and a
probe that failed NEVER renders as "belongs to nothing" - that is the
false green this whole subsystem exists to remove.

RESOLVE() IS FORBIDDEN HERE. S3's rule, restated because this is the
module most tempted to break it: ``expanduser()`` only, never
``resolve()``.

``expanduser()`` expands a shorthand the user typed - ``~/Development``
and ``/Users/him/Development`` are the same path he named two ways, and
project_store.normalize_root already stores roots expanded, so the
session side must expand too or a ``~``-form working directory can never
match an expanded root.

``resolve()`` is a different operation wearing similar clothes. It
collapses symlinks, which REWRITES the path the user chose. If he works
in ``/Users/him/code`` and that is a symlink to
``/Volumes/big/code``, resolving relocates his session into a path he
never typed, and it will not match the project he declared at the
symlink. Worse, ``resolve()`` touches the filesystem, so an unmounted
volume or a dangling symlink turns a pure function into one that can
hang or raise. Matching here is therefore PURELY LEXICAL on both sides:
a session under a symlinked root matches the project declared at that
same symlinked root, and the stored ``working_dir`` keeps the form it
was probed in.

WHAT LEXICAL MATCHING CANNOT DO, STATED SO NOBODY IS SURPRISED. A
session reached through a symlink will not match a project declared at
the symlink's TARGET (or the reverse). That is a deliberate miss, not an
oversight: the alternative is resolving, and resolving silently rewrites
the user's own path. The miss is honest and it renders as ``none``,
which is a true statement - no DECLARED root contains that path as
written.

COMPONENTS, NOT STRING PREFIXES. ``/a/bc`` must not match a project
rooted at ``/a/b``. Every comparison walks path components.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Optional, Tuple

from src.core.db_models import (
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
)

_PARENT_SEGMENT = ".."


def normalize_path_for_match(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        expanded = Path(text).expanduser()
    except (RuntimeError, TypeError, ValueError):
        return None
    if not expanded.is_absolute():
        return None
    if _PARENT_SEGMENT in expanded.parts:
        return None
    return str(expanded)


def _ancestor_chain(normalized: str) -> Tuple[str, ...]:
    pure = PurePosixPath(normalized)
    return (str(pure), *(str(parent) for parent in pure.parents))


def _depth(normalized: str) -> int:
    return len(PurePosixPath(normalized).parts)


def normalize_roots(roots: Dict[str, int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for root, project_id in roots.items():
        normalized = normalize_path_for_match(root)
        if normalized is None:
            continue
        existing = out.get(normalized)
        if existing is None or int(project_id) < existing:
            out[normalized] = int(project_id)
    return out


def attribute(
    working_dir: Optional[str], roots: Dict[str, int]
) -> Tuple[Optional[int], str]:
    """Resolve one working directory onto a project, deepest root wins.

    Description: the whole rule, in one place. Four cases it must get
      right, and they are the four the live database got wrong:

        EXACT       working_dir IS a project root.
        SUBDIR      working_dir sits under a project root; the DEEPEST
                    root containing it wins, so a session in
                    ``~/Development/app`` attributes to the
                    CloudeCode project and not to the ``~/Development``
                    project that also contains it.
        TILDE       ``~/Development`` and ``/Users/him/Development`` are
                    the same path named two ways. Both sides expand.
        SYMLINK     the path is compared AS WRITTEN. A session under a
                    symlinked root matches the project declared at that
                    same symlinked root, and nothing is rewritten.

      THREE OUTCOMES. ``none`` means read-and-matched-nothing. ``unknown``
      means could-not-read or could-not-situate. Never guessed to the
      nearest project, and a failed probe never renders as ``none``.
    Inputs: working_dir (str | None) - the probed cwd; None means the
      probe did not answer. roots (dict[str, int]) - project root ->
      project id, in any form; normalised here.
    Output: tuple[int | None, str] - (project_id, attribution), where
      attribution is one of ``derived_deepest``, ``none``, ``unknown``.
      project_id is non-None if and only if attribution is
      ``derived_deepest``.
    Example:
        >>> attribute('/a/b/c', {'/a': 1, '/a/b': 7})
        (7, 'derived_deepest')
    """
    normalized = normalize_path_for_match(working_dir)
    if normalized is None:
        return None, SESSION_ATTRIBUTION_UNKNOWN

    candidates = _ancestor_chain(normalized)
    comparable = normalize_roots(roots)

    best_id: Optional[int] = None
    best_depth = -1
    for root, project_id in comparable.items():
        if root not in candidates:
            continue
        depth = _depth(root)
        if depth > best_depth:
            best_id, best_depth = project_id, depth

    if best_id is None:
        return None, SESSION_ATTRIBUTION_NONE
    return best_id, SESSION_ATTRIBUTION_DERIVED_DEEPEST


def attribution_is_determined(attribution: Optional[str]) -> bool:
    if attribution is None:
        return False
    return attribution != SESSION_ATTRIBUTION_UNKNOWN


def unresolved_roots(roots: Iterable[str]) -> Tuple[str, ...]:
    return tuple(
        root for root in roots if normalize_path_for_match(root) is None
    )
