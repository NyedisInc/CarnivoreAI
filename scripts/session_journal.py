#!/usr/bin/env python3
"""Operator CLI over the session journal: read it, or take a pre-reboot snapshot.

Description: a THIN wrapper over the same modules the app runs
  (``src/core/session_journal_*``); it implements nothing of its own. Run it
  from the server directory so it reads what the running app reads:

    cd "$HOME/Library/Application Support/Carnivore Menubar/server"
    python3 scripts/session_journal.py status
    ... scripts/session_journal.py snapshot

  RE-EXEC. This script is bundled into the app and run with whatever
  ``python3`` happens to be on the operator's PATH, which has no
  ``pydantic`` and every other server dependency - only the server's own
  venv does. :func:`_reexec_under_venv_if_needed` detects that (a bare
  ``import pydantic`` failure) and re-execs itself under
  ``<server root>/venv/bin/python3`` before anything else runs. Calling
  ``venv/bin/python3`` directly still works exactly as before and skips
  the re-exec (pydantic already imports), so nothing already relying on
  the explicit form breaks.

  CLOUDE_STATE_DIR. An explicit value always wins outright. When unset,
  :func:`_default_state_dir` makes ONE read-only guess - does
  ``~/Library/Application Support/<current product name>`` (or a legacy
  name) exist on disk - and uses it if so. That check is ``Path.exists()``
  only; it never calls ``state_paths.state_dir()``, which performs the
  Carnivore-rename directory migration as a side effect, and that side
  effect is exactly what this read-only/backup tool must never trigger.
  Nothing found either way still refuses rather than guessing, same as
  before.

  status    prints the journal: boot time, every live session with the
            conversation its process is writing (and whether the row agrees),
            the open offer, and the last lines of the human log. READ ONLY.
  snapshot  runs one journal pass NOW (so the record is current to the
            second before a reboot) and takes an ONLINE backup of the
            database with the sqlite3 ``.backup`` command, never a file copy.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

LOG_TAIL_LINES: int = 20
SQLITE_BIN: str = "/usr/bin/sqlite3"

_REEXEC_SENTINEL: str = "_CLOUDE_JOURNAL_REEXECED"


def _venv_python() -> Optional[Path]:
    candidate = Path(__file__).resolve().parent.parent / "venv" / "bin" / "python3"
    return candidate if candidate.exists() else None


def _reexec_under_venv_if_needed() -> None:
    try:
        import pydantic  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get(_REEXEC_SENTINEL):
        sys.exit(
            "refusing: re-executed under the server venv and pydantic is "
            "still missing - this install's venv is broken"
        )
    venv_python = _venv_python()
    if venv_python is None:
        sys.exit(
            "refusing: no pydantic on this interpreter and no venv found "
            f"at {Path(__file__).resolve().parent.parent / 'venv'} - run "
            "this from the installed server directory, or point python3 "
            "at that venv yourself"
        )
    env = dict(os.environ)
    env[_REEXEC_SENTINEL] = "1"
    os.execve(
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve())] + sys.argv[1:],
        env,
    )


def _default_state_dir() -> Optional[Path]:
    """A read-only guess at the state directory, used only when unset.

    Description: checks ``Path.exists()`` alone against the current
      product name, then each legacy name, in that order, and returns
      the first that exists. Never calls
      ``src.config.state_paths.state_dir()``, which performs the
      Carnivore-rename directory migration as a side effect - a guess
      made by this read-only/backup tool must never rename anything on
      disk. Requires ``sys.path`` to already carry the server root, same
      as every other import in this module.
    Inputs: none.
    Output: Path | None - an existing directory, or None when neither the
      current nor any legacy name exists (the caller keeps refusing).
    Example: _default_state_dir() -> Path("~/Library/.../Carnivore")
    """
    from src.core import product_identity

    app_support = Path.home() / "Library" / "Application Support"
    names = [product_identity.STATE_DIR_NAME, *product_identity.LEGACY_STATE_DIR_NAMES]
    for name in names:
        candidate = app_support / name
        if candidate.exists():
            return candidate
    return None


def _bootstrap():
    """Resolve CLOUDE_STATE_DIR (explicit or a safe default) and return settings.

    Description: an explicit ``CLOUDE_STATE_DIR`` always wins outright.
      When it is unset, tries :func:`_default_state_dir` - a read-only
      guess - and sets the environment variable from it so every
      downstream reader (``settings``, ``state_paths``) sees the same
      value this function used. Refuses only when neither an explicit
      value nor a guess is available.
    Inputs: none (reads the environment, and ``sys.path`` for the import
      below).
    Output: Settings module.
    """
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    _resolve_state_dir_env()
    from src.config import settings  # noqa: E402

    if "src.main" in sys.modules:
        sys.exit("refusing: src.main was imported")
    return settings


def _resolve_state_dir_env() -> None:
    if os.environ.get("CLOUDE_STATE_DIR"):
        return
    guess = _default_state_dir()
    if guess is None:
        sys.exit(
            "refusing: export CLOUDE_STATE_DIR - no default state "
            "directory was found on disk to guess from"
        )
    os.environ["CLOUDE_STATE_DIR"] = str(guess)


def _socket(settings) -> str:
    from src.core.tmux_backend import DEFAULT_SOCKET_NAME

    try:
        return settings.load_auth_config().session.tmux_socket_name
    except (OSError, ValueError, AttributeError):
        return DEFAULT_SOCKET_NAME


def status(settings) -> int:
    from src.core import session_journal_store as store
    from src.core.session_journal_observe import live_entries

    state = Path(settings.get_state_dir())
    loaded = store.load_journal(state)
    print(f"journal   {store.journal_path(state)}  ({loaded.outcome})")
    print(f"human log {store.human_log_path(state)}")
    if loaded.outcome == store.LOAD_UNREADABLE:
        print(f"UNREADABLE: {loaded.detail}")
        return 2
    j = loaded.journal
    print(f"boot      {j.get('boot')}")
    live = live_entries(j)
    print(f"live      {len(live)} sessions (updated {j.get('updated_at')})")
    for key, e in sorted(live.items()):
        agree = "agrees" if e.get("conversation_agree") else f"ROW SAYS {e.get('conversation_recorded')}"
        print(f"  {key}\n    conversation {e.get('conversation_measured')} ({agree})"
              f"\n    cwd {e.get('cwd')}\n    argv {e.get('argv')}\n    last seen live {e.get('last_seen_live')}")
    offer = j.get("offer") or {}
    print(f"offer     state={offer.get('state')} reason={offer.get('reason')} "
          f"count={len(offer.get('candidates') or [])}")
    path = store.human_log_path(state)
    if path.exists():
        print("--- human log tail ---")
        print("".join(path.read_text().splitlines(True)[-LOG_TAIL_LINES:]), end="")
    return 0


def snapshot(settings) -> int:
    from src.core.db import db_path_for
    from src.core.session_journal_task import observe_pass

    state = Path(settings.get_state_dir())
    db = db_path_for(state)
    result = observe_pass(state, settings, _socket(settings), db)
    if result.get("journal") == "unreadable":
        print("journal unreadable; nothing written")
        return 2
    print(f"journal pass: {result}")
    out = state / "session-journal" / f"pre-reboot-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.db"
    proc = subprocess.run([SQLITE_BIN, f"file:{db}?mode=ro", f".backup '{out}'"],
                          capture_output=True, text=True, timeout=300, check=False)
    if proc.returncode != 0 or not out.exists():
        print(f"database backup FAILED: {proc.stderr.strip()}")
        return 2
    check = subprocess.run([SQLITE_BIN, str(out), "PRAGMA integrity_check"],
                           capture_output=True, text=True, timeout=300, check=False)
    print(f"database backup {out} ({out.stat().st_size} bytes) integrity={check.stdout.strip()}")
    return 0 if check.stdout.strip() == "ok" else 2


def main(argv) -> int:
    if len(argv) != 2 or argv[1] not in ("status", "snapshot"):
        print(__doc__)
        return 2
    _reexec_under_venv_if_needed()
    settings = _bootstrap()
    return status(settings) if argv[1] == "status" else snapshot(settings)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
