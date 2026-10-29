"""Where every durable thing this app owns actually lives.

The state-directory half of ``Settings``, carved out by slice S5 of
``.claude/notes/backend-decomposition-plan.md``. ``Settings`` is the
LOADER - it holds the env-backed fields and the pin cache - and this
module is the typed READER over them, so each function names exactly
which configuration it depends on instead of reaching into a settings
object for whatever it likes.

**THE PIN IS THE POINT OF THIS MODULE.** A name-keyed state file's
location is decided ONCE per process, on the first resolution, and then
sticks. It used to be re-derived from disk on every call, which made the
answer a function of whatever had just happened to the files:
``detach_session`` unlinked the resolved path and saved again, the save
re-resolved, the old location no longer existed, and the whole file
silently MOVED. A user who then downgraded found no session metadata at
all. The cache is passed in rather than held here, because it belongs to
the ``Settings`` instance whose configuration keys it.

**THE STATE DIR RESOLUTION MUST MATCH ``resolve_state_dir()`` IN
``scripts/upgrade_lib/upgrade_rollback_common.sh`` BYTE-FOR-BYTE**, and
``tests/test_state_dir_drift.py`` is what keeps the two from drifting.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.config.errors import StateDirUnavailableError
from src.core import product_identity

StateFilePin = Tuple[Path, str]

LOCATION_STATE_DIR = "state_dir"
LOCATION_LEGACY_STATE_DIR = "legacy_state_dir"
LOCATION_LOG_DIRECTORY = "log_directory"

_state_dir_legacy_note: Optional[str] = None


def state_dir_legacy_note() -> Optional[str]:
    return _state_dir_legacy_note


def allowed_origins(
    override: Optional[str], host: Optional[str], port: int
) -> List[str]:
    if override:
        parts = [p.strip() for p in override.split(",")]
        return [p for p in parts if p]

    origins: List[str] = []

    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    hostname_bare = hostname[:-6] if hostname.endswith(".local") else hostname

    if host and host != "0.0.0.0":
        origins.append(f"http://{host}:{port}")

    origins.append(f"http://localhost:{port}")
    origins.append(f"http://127.0.0.1:{port}")

    if hostname_bare:
        origins.append(f"http://{hostname_bare}:{port}")
        origins.append(f"http://{hostname_bare}.local:{port}")

    seen = set()
    deduped: List[str] = []
    for o in origins:
        if o not in seen:
            seen.add(o)
            deduped.append(o)
    return deduped


def working_dir(configured: str) -> Path:
    path = Path(configured).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir_is_explicit(override: Optional[str]) -> bool:
    """Did the operator NAME a state directory, or is this the default?

    Description: the one authority for that fact, and the reason it is a
      free function here rather than a method on ``Settings`` is that
      both consumers live in this module's rules. :func:`state_dir`
      branches on it to pick the override over the macOS-native default,
      and :func:`state_file_pin` is HANDED it to decide whether the
      legacy ``log_directory`` rung may fire at all. Deriving it a second
      time is how the two come to disagree.

      It matters because ``LOG_DIRECTORY`` is populated from the
      install's own ``.env`` and is therefore set for an operator who
      never chose it, while ``CLOUDE_STATE_DIR`` is only ever set
      deliberately. A stated location outranks an inferred one, so an
      explicit state directory suppresses a legacy pin derived from a
      variable nobody chose - which is what makes ``CLOUDE_STATE_DIR``
      alone enough to isolate a dev or test instance. Without it a
      throwaway server resolves, holds open, and in one measured case
      WRITES the real user's state files.
    Inputs: override (str | None) - the ``CLOUDE_STATE_DIR`` value.
    Output: bool - True when it was supplied non-empty, False when the
      default location is in force.
    Example: state_dir_is_explicit(None) -> False
    """
    return bool(override)


def state_dir(override: Optional[str]) -> Path:
    """Resolve and ensure the application's durable state directory.

    Description: single source of truth for where Carnivore's durable
      state lives - session_metadata.json, pinned_themes.json,
      unread_state.json, refresh_tokens.db, agent_wrapper_scripts/,
      per-session tmux log files and the app's SQLite database. It
      replaced an older default of putting state under ``log_directory``,
      whose ``.env.example`` default was ``/tmp/cloude-code-logs``, a
      directory macOS purges on every reboot, which is exactly wrong for
      data the user depends on.
    """
    if state_dir_is_explicit(override):
        path = Path(override).expanduser()
    else:
        app_support = Path.home() / "Library" / "Application Support"
        path = app_support / product_identity.STATE_DIR_NAME
        if product_identity.LEGACY_STATE_DIR_NAMES and not path.exists():
            legacy_path = app_support / product_identity.LEGACY_STATE_DIR_NAMES[0]
            if legacy_path.exists():
                path = _migrate_legacy_state_dir_once(legacy_path, path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StateDirUnavailableError(path, exc) from exc
    return path


def _migrate_legacy_state_dir_once(legacy_path: Path, new_path: Path) -> Path:
    """Rename the legacy-named state directory forward, once, atomically.

    Description: called only from :func:`state_dir`, only when
      ``new_path`` is absent and ``legacy_path`` exists. Announces the
      move in ``migration_trail.jsonl`` (kind ``"state_dir"``) the same
      two-phase way a schema migration does: the ``started`` line is
      appended and fsynced into the LEGACY directory (which still exists
      at that point) BEFORE the rename runs, and the closing line is
      appended into the SAME file at its NEW location afterward - the
      rename moves the whole tree, migration_trail.jsonl included, so
      both appends land in what ends up being one continuous file. A
      crash between the two lines is exactly what
      src/core/trail_reader.py's INTERRUPTED detection already exists to
      report on the next boot.

      Never raises. Every failure - the trail append, or the rename
      itself - degrades to "keep using the legacy directory", logged once
      at warning level and recorded via
      :data:`_state_dir_legacy_note`'s setter, never a partial move.
    Inputs: legacy_path (Path) - the existing legacy-named directory.
      new_path (Path) - the current-named directory, confirmed absent by
      the caller.
    Output: Path - ``new_path`` on a successful rename, ``legacy_path``
      when the rename could not happen for any reason.
    """
    global _state_dir_legacy_note

    from src.core.db_models import TRAIL_STATUS_COMPLETED, TRAIL_STATUS_FAILED
    from src.core.migration_trail import MigrationTrail

    logger = structlog.get_logger()
    pre_trail = MigrationTrail(legacy_path)
    try:
        started = pre_trail.open_step(
            "state_dir",
            from_version=legacy_path.name,
            to_version=new_path.name,
            detail=f"renaming state directory {legacy_path} to {new_path}",
        )
    except OSError as exc:
        note = (
            f"using the legacy state directory {legacy_path} - could not "
            f"record the rename attempt in its upgrade trail: {exc}"
        )
        logger.warning(
            "state_dir_legacy_rename_trail_open_failed",
            legacy_path=str(legacy_path),
            new_path=str(new_path),
            error=str(exc),
        )
        _state_dir_legacy_note = note
        return legacy_path

    try:
        legacy_path.rename(new_path)
    except OSError as exc:
        note = (
            f"using the legacy state directory {legacy_path} - could not "
            f"rename it to {new_path}: {exc}"
        )
        logger.warning(
            "state_dir_legacy_rename_failed",
            legacy_path=str(legacy_path),
            new_path=str(new_path),
            error=str(exc),
        )
        try:
            pre_trail.close_step(started, TRAIL_STATUS_FAILED, error=str(exc))
        except OSError as trail_exc:
            logger.warning(
                "state_dir_legacy_rename_trail_close_failed",
                error=str(trail_exc),
            )
        _state_dir_legacy_note = note
        return legacy_path

    post_trail = MigrationTrail(new_path)
    try:
        post_trail.close_step(started, TRAIL_STATUS_COMPLETED)
    except OSError as exc:
        # could not be written
        logger.warning(
            "state_dir_legacy_rename_trail_close_failed",
            new_path=str(new_path),
            error=str(exc),
        )
    _state_dir_legacy_note = None
    logger.info(
        "state_dir_legacy_renamed",
        legacy_path=str(legacy_path),
        new_path=str(new_path),
    )
    return new_path


def state_file_pin(
    filename: str,
    *,
    pins: Dict[tuple, StateFilePin],
    resolved_state_dir: Path,
    state_dir_override: Optional[str],
    log_directory: Optional[str],
    state_dir_explicit: bool,
) -> StateFilePin:
    """Decide ONCE where one name-keyed state file lives, then keep it.

    Description: the single authority behind :func:`resolve_state_file`
      and :func:`state_file_location`. Everything either of those returns
      comes from here, so no call site ever re-derives it.

      RUNG 0, and it outranks every rung below: ``CLOUDE_STATE_DIR`` was
      set, so the operator NAMED where state lives and neither legacy
      location is consulted at all. A stated location outranks one
      inferred from ``LOG_DIRECTORY``, which the install's own ``.env``
      supplies whether or not anyone chose it, and it outranks the
      legacy-named default directory too, for the identical reason. See
      :func:`state_dir_is_explicit`. Neither legacy copy is ever read,
      moved or deleted when this rung fires; a copy left in the
      LOG_DIRECTORY location is logged once at info level so an operator
      who pointed ``CLOUDE_STATE_DIR`` at a fresh directory on an install
      whose real state sits at the legacy location gets a diagnostic
      instead of silence.

      The middle (legacy-named directory) rung is skipped entirely when
      it would name the SAME directory as ``resolved_state_dir`` - this
      happens when :func:`state_dir` itself already fell back to running
      out of the legacy directory because its own rename could not
      complete, and re-probing that same directory here as a separate
      "legacy" candidate would compare a path against itself.

      The pin is keyed on the CONFIGURED directories, so repointing
      ``CLOUDE_STATE_DIR`` or ``LOG_DIRECTORY`` re-asks the question - a
      different configuration is a different question - while a file
      appearing or disappearing does not.
    Inputs: filename (str) - bare filename, e.g. "pinned_themes.json";
      pins (dict) - the caller's cache, MUTATED here; resolved_state_dir
      (Path) - the answer from :func:`state_dir`; state_dir_override
      (str | None) and log_directory (str | None) - the two configured
      spellings the pin is keyed on; state_dir_explicit (bool) - from
      :func:`state_dir_is_explicit`, PASSED IN rather than re-derived
      here so the legacy rung can be driven both ways by a test. A guard
      that asks for its own condition is one whose refusing branch nobody
      has ever watched run.
    Output: tuple[Path, str] - the resolved path and its location, one of
      ``"state_dir"``, ``"legacy_state_dir"`` or ``"log_directory"``.
    Example: state_file_pin("unread_state.json", pins={}, ...)
    """
    state_key = state_dir_override or ""
    log_key = log_directory or ""
    key = (filename, state_key, log_key, state_dir_explicit)

    pinned = pins.get(key)
    if pinned is not None:
        return pinned

    new_path = resolved_state_dir / filename
    decision: StateFilePin = (new_path, LOCATION_STATE_DIR)

    if not state_dir_explicit and product_identity.LEGACY_STATE_DIR_NAMES:
        legacy_named_dir = (
            Path.home() / "Library" / "Application Support"
            / product_identity.LEGACY_STATE_DIR_NAMES[0]
        )
        if legacy_named_dir != resolved_state_dir:
            legacy_named_path = legacy_named_dir / filename
            current_exists = decision[0].exists()
            legacy_named_exists = legacy_named_path.exists()
            if current_exists and legacy_named_exists:
                structlog.get_logger().warning(
                    "state_file_present_in_both_locations",
                    filename=filename,
                    using=str(decision[0]),
                    old_path_retained=str(legacy_named_path),
                )
            elif legacy_named_exists:
                decision = (legacy_named_path, LOCATION_LEGACY_STATE_DIR)

    if log_key and not state_dir_explicit:
        old_path = Path(log_key).expanduser() / filename
        new_exists = decision[0].exists()
        old_exists = old_path.exists()
        if new_exists and old_exists:
            structlog.get_logger().warning(
                "state_file_present_in_both_locations",
                filename=filename,
                using=str(decision[0]),
                old_path_retained=str(old_path),
            )
        elif old_exists:
            decision = (old_path, LOCATION_LOG_DIRECTORY)
    elif log_key and state_dir_explicit:
        old_path = Path(log_key).expanduser() / filename
        if old_path.exists():
            structlog.get_logger().info(
                "state_file_legacy_copy_left_behind",
                filename=filename,
                using=str(new_path),
                legacy_path=str(old_path),
            )

    pins[key] = decision
    return decision
