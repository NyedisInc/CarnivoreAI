"""
What ONE ``GET /config-files/tree`` request is asking for - the pure rules,
with no filesystem and no HTTP in them.

WHY THE FULL TREE IS THE DEFAULT, AND MUST STAY THE DEFAULT. The server half
of this change ships and is verifiable before the client half exists, and an
older client - a phone with a cached page, a browser tab open since before
the deploy - keeps working with no negotiation, because it sends no ``depth``
and therefore selects exactly the previous behaviour. A new parameter that
changes what an omitted parameter means is not an additive change.

VALIDATION RAISES ``ValueError``, WHICH THE ROUTE TRANSLATES TO 400. That is
deliberate and it preserves this endpoint's three-outcome error contract: a
malformed request is 400 ("you asked wrongly"), a root that exists but could
not be enumerated is 503 ("I could not evaluate this"), and a successful read
of an empty directory is 200 with an empty list ("there is genuinely nothing
here"). Folding a bad ``depth`` into the 503 branch, or letting it reach the
filesystem and surface as something else, would blur the one distinction this
endpoint's client relies on to decide whether to show an error row or show
nothing at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.config_files_constants import TREE_MAX_DEPTH

FULL_TREE_LEVELS = TREE_MAX_DEPTH + 1


@dataclass(frozen=True)
class TreeRequest:
    rel_path: str
    levels: int
    shallow: bool


def plan_tree_request(path: Optional[str], depth: Optional[int]) -> TreeRequest:
    if depth is not None:
        if depth < 1:
            raise ValueError("depth must be at least 1")
        if depth > FULL_TREE_LEVELS:
            raise ValueError(f"depth must be at most {FULL_TREE_LEVELS}")

    return TreeRequest(
        rel_path=(path or ""),
        levels=(FULL_TREE_LEVELS if depth is None else depth),
        shallow=depth is not None,
    )
