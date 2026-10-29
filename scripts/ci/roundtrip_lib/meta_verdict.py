#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from typing import Optional

STALE_LOG = "03-upgraded-new.server.log"


def load(art: str, name: str) -> dict:
    try:
        with open(os.path.join(art, name)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return {"_unreadable": str(exc)}


def load_last_json(art: str, name: str) -> dict:
    try:
        with open(os.path.join(art, name)) as fh:
            lines = fh.read().strip().splitlines()
        for line in reversed(lines):
            if line.startswith("{"):
                return json.loads(line)
        return {"_unreadable": "no JSON line in " + name}
    except (OSError, json.JSONDecodeError) as exc:
        return {"_unreadable": str(exc)}


def logged(art: str, fname: str, needle: str) -> Optional[bool]:
    try:
        with open(os.path.join(art, fname)) as fh:
            return needle in fh.read()
    except OSError:
        return None


def decide(detach: dict, old_d: dict, cleared: Optional[bool], rehydrated: Optional[bool]) -> tuple[str, str]:
    live_id = detach.get("persisted_after_detach")
    if "_unreadable" in detach or "error" in detach or not live_id:
        return ("CANNOT-DETERMINE",
                "the detach step did not measure a persisted id (%s), so there is nothing to compare the old version against"
                % (detach.get("error") or detach.get("_unreadable") or "no metadata file after the detach"))
    if "_unreadable" in old_d:
        return "CANNOT-DETERMINE", "the post-downgrade probe produced no readable JSON"
    if cleared is None:
        return ("CANNOT-DETERMINE",
                "the upgrade server log could not be read, so it is unknown whether "
                "the reconciler rejected the seeded session before the relocation "
                "path was ever reached")
    if cleared and not rehydrated:
        return ("CANNOT-DETERMINE",
                "the new version deleted the seeded metadata as stale at startup "
                "(no cloude_<id> match on the socket), so the upgrade->downgrade "
                "relocation path was never exercised - this measures the fixture, "
                "not the product")
    if not old_d.get("present"):
        return ("ABSENT",
                "the old version resolves %s and there is no file there - every "
                "persisted session, its working dir and the owned-tmux set are gone"
                % old_d.get("resolved"))
    if old_d.get("session_id") == live_id:
        return "INTACT", "the old version reads the session the new version last persisted"
    return ("STALE",
            "the old version reads %r while the new version last persisted %r - "
            "a wrong answer, not a missing one" % (old_d.get("session_id"), live_id))


def main(run_dir: str) -> dict:
    art = os.path.join(run_dir, "artifacts")
    cleared = logged(art, STALE_LOG, "stale_session_metadata_deleted")
    rehydrated = logged(art, STALE_LOG, "session_re_registered_from_backend")
    old_w = load(art, "meta-01-old-writes.json")
    detach = load_last_json(art, "meta-03-new-after-detach.json")
    new_u = load(art, "meta-02-new-after-upgrade.json")
    old_d = load(art, "meta-04-old-after-downgrade.json")
    verdict, why = decide(detach, old_d, cleared, rehydrated)
    return {
        "verdict": verdict,
        "why": why,
        "old_wrote_at": old_w.get("resolved"),
        "new_resolved_after_upgrade": new_u.get("resolved"),
        "old_resolved_after_downgrade": old_d.get("resolved"),
        "old_sees_session_id": old_d.get("session_id"),
        "new_last_persisted": detach.get("persisted_after_detach"),
        "upgrade_cleared_metadata_as_stale": cleared,
        "upgrade_rehydrated_seeded_session": rehydrated,
    }


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=2, sort_keys=True))
