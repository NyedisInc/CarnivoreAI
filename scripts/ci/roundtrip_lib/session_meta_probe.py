#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="")
    ap.add_argument("--write", default=None, help="session id to persist")
    ap.add_argument("--name", default=None, help="tmux session name")
    ap.add_argument("--working-dir", default="/tmp")
    ap.add_argument("--owned", action="append", default=[])
    args = ap.parse_args()

    sys.path.insert(0, str(Path.cwd()))
    from src.config import Settings  # noqa: E402

    s = Settings()
    out = {"label": args.label}

    try:
        out["state_dir"] = str(s.get_state_dir())
    except AttributeError:
        out["state_dir"] = None
        out["state_dir_note"] = "this version has no get_state_dir()"
    out["log_directory"] = s.log_directory

    path = Path(s.get_session_metadata_path())
    out["resolved"] = str(path)

    if args.write:
        from src.models import Session  # noqa: E402

        payload = json.loads(
            Session(
                id=args.write,
                working_dir=args.working_dir,
                tmux_session=args.name,
            ).model_dump_json()
        )
        payload["owned_tmux_sessions"] = sorted(args.owned)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
        out["wrote"] = str(path)

    out["present"] = path.exists()
    out["session_id"] = None
    out["owned_tmux_sessions"] = None
    if out["present"]:
        try:
            raw = json.loads(path.read_text())
            out["session_id"] = raw.get("id")
            out["owned_tmux_sessions"] = raw.get("owned_tmux_sessions")
        except (ValueError, OSError) as exc:
            out["read_error"] = str(exc)

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
