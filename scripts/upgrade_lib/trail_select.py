#!/usr/bin/env python3
"""Choose which backup a CODE rollback must restore, or refuse to choose.

Design section 9.8, the data half of scripts/rollback.sh. Called by that
script; never imports the application, so it keeps working after
`git checkout tags/<old>` has swapped `src/` out from under it. Standard
library only.

THE SELECTION RULE, IN TWO STEPS, BECAUSE ONE IS NOT ENOUGH.
Section 9.8 says: "find the last schema/config entry with started_at
before the target code entry's started_at". That sentence identifies the
data VERSION that was current at the target code point - it does not
identify the backup to restore, and the two are different entries.

  Trail: code v1, schema 1->2, code v2, schema 2->3, code v3.
  Rolling back to code v2.

  Step 1 - the version. The last data entry before `code v2` is
  `schema 1->2`, whose to_version is 2. So the schema version current at
  code v2 was 2.

  Step 2 - the backup OF version 2. Backups are taken BEFORE a step runs
  and are named for the version they leave (`cloude.db.bak-v<from>-<ts>`),
  so the snapshot of version 2 hangs off the entry with from_version=2,
  which is `schema 2->3` - an entry that started AFTER the target code
  point. Selecting the backup attached to the step found in step 1
  (`schema 1->2`, a snapshot of version 1) would restore the wrong
  version while looking exactly as principled.

If the version at the target point is known and NO verified backup of it
exists, that is COULD NOT EVALUATE and this program refuses. It never
falls back to the newest backup. A rollback tool guessing which backup to
restore is the whole failure this design exists to close.

ORDER IS TAKEN FROM started_at, NEVER FROM LINE POSITION. Appends can be
interleaved by two writers (the app and a shell script) and a trail is
still correct if its lines are out of file order; a trail whose lines are
out of TIME order is what corruption looks like, and time is what "before
the target" means.

THE REAL FILE FORMAT DIFFERS FROM THE DESIGN'S PROSE. One entry per
migration RUN spanning the whole jump, split across a `started` line and
a closing line that carries the backup path. All of that is handled in
scripts/upgrade_lib/trail_records.py; read its docstring before changing
anything here that touches versions or backups.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from trail_records import (  # noqa: E402
    READ_ABSENT,
    READ_OK,
    READ_UNREADABLE,
    Step,
    read_steps,
)

KIND_SCHEMA = "schema"
KIND_CONFIG = "config"
KIND_CODE = "code"
KIND_BOOTSTRAP = "bootstrap"
DATA_KINDS = (KIND_SCHEMA, KIND_CONFIG)

VERSION_ESTABLISHING = {KIND_SCHEMA: (KIND_SCHEMA, KIND_BOOTSTRAP),
                        KIND_CONFIG: (KIND_CONFIG,)}

ARTIFACT = {KIND_SCHEMA: "cloude.db", KIND_CONFIG: "config.json"}

OUTCOME_RESTORE = "restore"
OUTCOME_ALREADY_CURRENT = "already_current"
OUTCOME_NOT_APPLICABLE = "not_applicable"
OUTCOME_CANNOT_DETERMINE = "cannot_determine"

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_UNREADABLE = 3
EXIT_ABSENT = 4


def find_target_code(steps: List[Step], target: str) -> Optional[Step]:
    matches = [
        s for s in steps
        if s.kind == KIND_CODE and _same_version(s.to_version, target)
    ]
    return matches[-1] if matches else None


def _same_version(recorded: Optional[str], asked: str) -> bool:
    if recorded is None:
        return False
    return recorded.lstrip("v") == asked.lstrip("v")


def select_for_kind(steps: List[Step], kind: str, code_step: Step) -> Dict[str, Any]:
    of_kind = [s for s in steps if s.kind == kind]
    establishing = [s for s in steps if s.kind in VERSION_ESTABLISHING[kind]]
    item: Dict[str, Any] = {"kind": kind, "artifact": ARTIFACT[kind]}

    if not establishing:
        item["outcome"] = OUTCOME_NOT_APPLICABLE
        item["reason"] = (
            f"the trail records no {kind} migration at all on this install, "
            f"so {ARTIFACT[kind]} has never moved and there is nothing to "
            "restore it to."
        )
        return item

    before = [s for s in establishing if s.started_at < code_step.started_at]
    if not before:
        item["outcome"] = OUTCOME_CANNOT_DETERMINE
        item["reason"] = (
            f"this install has {len(establishing)} recorded {kind} "
            "migration(s) (bootstrap included), "
            f"but every one of them started AFTER it reached code "
            f"{code_step.to_version} at {code_step.started_at}. The {kind} "
            "version in force at that moment therefore predates the trail "
            "and is unknown. Refusing to pick a backup rather than guessing "
            "one."
        )
        return item

    version_at_target = before[-1].to_version
    item["version_at_target"] = version_at_target

    after = [s for s in of_kind if s.started_at >= code_step.started_at]
    moved_away = [s for s in after if s.from_version == version_at_target]
    if not moved_away:
        swallowing = [
            s for s in after
            if s.from_version is not None and s.from_version != version_at_target
        ]
        if not after:
            item["outcome"] = OUTCOME_ALREADY_CURRENT
            item["reason"] = (
                f"{kind} has not moved since this install was at code "
                f"{code_step.to_version}; it is still at v{version_at_target}. "
                f"Nothing to restore for {ARTIFACT[kind]}."
            )
            return item
        item["outcome"] = OUTCOME_CANNOT_DETERMINE
        item["reason"] = (
            f"{kind} was at v{version_at_target} when this install reached "
            f"code {code_step.to_version}, but no backup was ever taken AT "
            f"v{version_at_target}: the next recorded {kind} move started "
            f"from v{swallowing[0].from_version}"
            + (
                f" (a jump v{swallowing[0].from_version}->"
                f"v{swallowing[0].to_version} that ran several steps in one "
                "run and took one backup, at its start)"
                if swallowing else ""
            )
            + ". Refusing to restore a different version's backup."
        )
        return item

    source = moved_away[0]
    if not source.has_verified_backup:
        item["outcome"] = OUTCOME_CANNOT_DETERMINE
        item["reason"] = (
            f"the {kind} move away from v{version_at_target} (entry "
            f"{source.entry_uuid}) recorded backup_path="
            f"{source.backup_path!r} with backup_verified="
            f"{source.backup_verified!r}. An unverified backup is treated as "
            "a backup that does not exist, so there is nothing to restore "
            f"{ARTIFACT[kind]} from."
        )
        return item

    item["outcome"] = OUTCOME_RESTORE
    item["backup_path"] = source.backup_path
    item["backup_taken_at"] = source.started_at
    item["source_entry_uuid"] = source.entry_uuid
    item["reason"] = (
        f"{kind} was at v{version_at_target} at the target code point; the "
        f"backup taken at v{version_at_target}, immediately before the "
        f"v{source.from_version}->v{source.to_version} move, is "
        f"{source.backup_path}."
    )
    return item


def render_confirmation(plan: Dict[str, Any]) -> str:
    lines = [
        f"Rolling back code to {plan['target_code_version']} (which this "
        f"install reached at {plan['target_code_started_at']}).",
        "",
        "This will OVERWRITE live data with these backups:",
    ]
    for item in plan["items"]:
        if item["outcome"] == OUTCOME_RESTORE:
            lines.append(
                f"  {item['artifact']}: restore to {item['kind']} "
                f"v{item['version_at_target']} from {item['backup_path']}, "
                f"taken {item['backup_taken_at']}."
            )
            lines.append(
                f"  Everything written to {item['artifact']} since "
                f"{item['backup_taken_at']} is discarded."
            )
        else:
            lines.append(f"  {item['artifact']}: {item['reason']}")
    lines.append("")
    lines.append("This cannot be undone.")
    return "\n".join(lines)


def build_plan(steps: List[Step], target: str) -> Tuple[int, Dict[str, Any]]:
    """Assemble the full restore plan for a code rollback, or refuse.

    Description: refuses as a whole if ANY data kind could not be
      resolved. A partial restore - database rolled back, config left
      forward, or the reverse - is a state neither version was ever
      tested in, and it would be produced silently.
    Inputs: steps (list[Step]) - coalesced, sorted. target (str) - the
      code version being rolled back to.
    Output: (exit_code, plan) - EXIT_OK with a plan carrying
      "confirmation", or EXIT_REFUSED with a plan carrying "error".
    """
    code_step = find_target_code(steps, target)
    if code_step is None:
        seen = sorted({
            s.to_version for s in steps
            if s.kind == KIND_CODE and s.to_version
        })
        return EXIT_REFUSED, {
            "error": (
                f"the trail records no code entry arriving at {target}, so "
                "the data versions in force at that release are unknown. "
                "Code versions the trail does know: "
                + (", ".join(seen) if seen else "(none)")
                + "."
            ),
            "known_code_versions": seen,
        }

    items = [select_for_kind(steps, kind, code_step) for kind in DATA_KINDS]
    plan = {
        "target_code_version": code_step.to_version,
        "target_code_started_at": code_step.started_at,
        "target_code_entry_uuid": code_step.entry_uuid,
        "items": items,
    }
    undecided = [i for i in items if i["outcome"] == OUTCOME_CANNOT_DETERMINE]
    if undecided:
        plan["error"] = (
            "could not determine what to restore for: "
            + ", ".join(i["kind"] for i in undecided)
            + ". Refusing the whole rollback rather than restoring one half "
            "of the state and leaving the other at a version it was never "
            "paired with. Reasons: "
            + " | ".join(i["reason"] for i in undecided)
        )
        return EXIT_REFUSED, plan
    plan["confirmation"] = render_confirmation(plan)
    return EXIT_OK, plan


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["select"])
    parser.add_argument("--trail", required=True)
    parser.add_argument("--target-code", required=True)
    args = parser.parse_args(argv)

    status, steps, reason, corrupt_line = read_steps(Path(args.trail))
    if status == READ_UNREADABLE:
        json.dump({
            "trail_status": READ_UNREADABLE,
            "corrupt_line": corrupt_line,
            "error": reason,
        }, sys.stdout)
        sys.stdout.write("\n")
        return EXIT_UNREADABLE
    if status == READ_ABSENT:
        json.dump({"trail_status": READ_ABSENT, "error": reason}, sys.stdout)
        sys.stdout.write("\n")
        return EXIT_ABSENT

    code, plan = build_plan(steps, args.target_code)
    plan["trail_status"] = READ_OK
    json.dump(plan, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
