
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from src.core.sessions.ports import InstallRoots
from src.core.skills.legacy_trash import trash_root_for
from src.core.skills.roots import target_dir, unsafe_name_reason

REFUSED_NAME = "name_unsafe"

REFUSED_SCOPE = "scope_unknown"

REFUSED_TARGET = "target_outside_roots"

REFUSED_ROOT = "target_is_a_root"

REFUSED_STAGED = "staged_not_beside_target"

REFUSED_TRASH = "trash_not_for_this_scope"

REFUSED_STAMP = "stamp_escapes_the_trash"

REFUSAL_CODES: tuple[str, ...] = (
    REFUSED_NAME,
    REFUSED_SCOPE,
    REFUSED_TARGET,
    REFUSED_ROOT,
    REFUSED_STAGED,
    REFUSED_TRASH,
    REFUSED_STAMP,
)


class JournalFields(Protocol):

    install_id: str
    kind: str
    name: str
    scope: str
    project_path: Optional[str]
    target: str
    staged: str
    trash: str
    stamp: str


@dataclass(frozen=True)
class JournalRefusal:

    code: str
    detail: str


def same_entry(left: Path, right: Path) -> bool:
    if left.name != right.name:
        return False
    return os.path.realpath(left.parent) == os.path.realpath(right.parent)


def journal_refusal(
    journal: JournalFields, *, roots: InstallRoots
) -> Optional[JournalRefusal]:
    reason = unsafe_name_reason(journal.name)
    if reason is not None:
        return JournalRefusal(code=REFUSED_NAME, detail=reason)

    try:
        targets = roots.targets_for(
            journal.kind, journal.scope, journal.project_path
        ) + roots.legacy_targets_for(
            journal.kind, journal.scope, journal.project_path
        )
    except ValueError as exc:
        return JournalRefusal(code=REFUSED_SCOPE, detail=str(exc))

    target = Path(journal.target)

    for candidate in targets:
        if same_entry(candidate.leaf_dir, target):
            return JournalRefusal(
                code=REFUSED_ROOT,
                detail=(
                    f"{journal.target} IS the {candidate.harness} install "
                    "root; a recovery acting on it would rename or delete "
                    "every skill in it"
                ),
            )

    matched = None
    for candidate in targets:
        if same_entry(target_dir(candidate, journal.name), target):
            matched = candidate
            break

    if matched is None:
        return JournalRefusal(
            code=REFUSED_TARGET,
            detail=(
                f"{journal.target} is not {journal.name!r} under any root "
                f"this app installs {journal.scope} scope into "
                f"({', '.join(str(t.leaf_dir) for t in targets)})"
            ),
        )

    staged = Path(journal.staged)
    staged_reason = unsafe_name_reason(staged.name)
    if staged_reason is not None:
        return JournalRefusal(code=REFUSED_STAGED, detail=staged_reason)
    if same_entry(staged, target):
        return JournalRefusal(
            code=REFUSED_STAGED,
            detail=(
                f"{journal.staged} is the target itself; a swap of a folder "
                "with itself would delete it"
            ),
        )
    if not same_entry(staged.parent, target.parent):
        return JournalRefusal(
            code=REFUSED_STAGED,
            detail=(
                f"{journal.staged} is not beside {journal.target}; this app "
                "stages the new copy in the target's own directory, because "
                "the swap is a rename and a rename stays on one volume"
            ),
        )

    try:
        expected_trash = trash_root_for(
            roots,
            kind=journal.kind,
            harness=matched.harness,
            scope=journal.scope,
            project_path=journal.project_path,
            live_path=target,
        )
    except ValueError as exc:
        return JournalRefusal(code=REFUSED_TRASH, detail=str(exc))
    if not same_entry(Path(journal.trash), expected_trash):
        return JournalRefusal(
            code=REFUSED_TRASH,
            detail=(
                f"{journal.trash} is not the {matched.harness} trash for "
                f"{journal.scope} scope ({expected_trash})"
            ),
        )

    displaced_name = f"{target.name}-{journal.stamp}"
    stamp_reason = unsafe_name_reason(displaced_name)
    if stamp_reason is not None:
        return JournalRefusal(
            code=REFUSED_STAMP,
            detail=(
                f"the stamp {journal.stamp!r} composes {displaced_name!r}, "
                f"which would leave the trash root: {stamp_reason}"
            ),
        )

    return None
