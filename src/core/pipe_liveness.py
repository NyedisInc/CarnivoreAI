"""Who owns a pane's ``pipe-pane`` copier, and whether it is still ours.

WHY THIS FILE EXISTS. The live terminal stream is
``tmux pipe-pane -o 'cat >> <file>'``: tmux forks a copier that appends
every byte the pane emits to a file, and the server tails that file.
``pipe-pane`` GIVEN A COMMAND REPLACES whatever copier is already running
on that pane. So a second Cloude Code server on the shared ``cloude``
socket that adopts the same session repoints the copier into its own pipe
directory, and the first server goes on tailing a file nobody will ever
write to again.

``#{pane_pipe}`` STILL ANSWERS ``1`` THROUGHOUT, because a copier IS
running - just not one writing where this server reads. That is a check
that passes because it looked at the wrong subject, and it is the reason
the guard in ``TmuxBackend.ensure_pipe_pane`` could not see the theft.

AND THE COPIER IS TMUX'S CHILD, NOT THE REQUESTING SERVER'S, which is
what makes this unrecoverable from the outside: the scratch files kept
growing after the offending server's process was dead. Killing the thief
recovers nothing. Only a re-attach, a restart, or the re-issue this
module triggers does.

WHY A PANE USER OPTION IS THE ARBITER. tmux records the fact of a pipe
and not its command: verified on tmux 3.6a, ``#{pane_pipe_command}`` does
not exist and renders as the empty string, and ``display-message -a`` on
a live piped pane prints exactly one pipe key, ``pane_pipe=1``. So no
format tmux offers can tell "my copier" from "somebody else's copier",
and the only way to know is to write down what we started. The option
lives ON THE PANE, so it survives this server's restart, it is readable
by every other server on the socket, and an operator can read it with one
``display-message``. Its value is the ABSOLUTE path of the file the
owning server tails; that is a contract other tooling reads.

TWO RUNGS, BECAUSE THE OPTION ALONE IS NOT ENOUGH. A server running this
code records the option, so a mismatch names the thief. A thief that does
NOT record it - a server from before this change, or the user's own
logging ``pipe-pane`` - leaves OUR option standing while its copier takes
the bytes. Verified on a throwaway socket, tmux 3.6a: after a foreign
re-issue the option still read the old path, ``#{pane_pipe}`` still read
``1``, the original file stayed at 29 bytes and the thief's grew to 31.
So the second rung is a POSITIVE MEASUREMENT OF THE PANE ITSELF: when our
file has been silent and the pane demonstrably produced output anyway,
the stream was taken, whoever took it.

NOTHING POLLED ``#{pane_pipe}`` BEFORE THIS. ``ensure_pipe_pane`` is
reached only from ``attach_existing``, i.e. at boot re-adopt or on a
reconcile attach. Opening a terminal websocket does not re-attach, so
once the stream was stolen after attach, nothing in the running server
ever noticed. That is the gap :class:`SilenceTracker` closes.
"""

from __future__ import annotations

import time
from typing import NamedTuple, Optional

PIPE_OWNER_OPTION: str = "@cloude_pipe_path"

FIELD_SEPARATOR: str = "|"

OWNERSHIP_FORMAT: str = (
    "#{pane_dead}"
    + FIELD_SEPARATOR
    + "#{pane_pipe}"
    + FIELD_SEPARATOR
    + "#{window_activity}"
    + FIELD_SEPARATOR
    + "#{history_size}:#{cursor_x}:#{cursor_y}"
    + FIELD_SEPARATOR
    + "#{" + PIPE_OWNER_OPTION + "}"
)

PIPE_LIVENESS_SILENCE_SECONDS: float = 5.0


OWNED: str = "owned"

PANE_DEAD: str = "pane_dead"

NO_PIPE: str = "no_pipe"

NO_OWNER_RECORDED: str = "no_owner_recorded"

FOREIGN_OWNER: str = "foreign_owner"

LEGACY_OWNER: str = "legacy_owner"

FILE_MISSING: str = "file_missing"

SILENT_WHILE_PANE_ACTIVE: str = "silent_while_pane_active"

QUIET: str = "quiet"

REISSUE_VERDICTS: frozenset = frozenset(
    {NO_PIPE, NO_OWNER_RECORDED, FOREIGN_OWNER, LEGACY_OWNER, FILE_MISSING,
     SILENT_WHILE_PANE_ACTIVE}
)

THEFT_VERDICTS: frozenset = frozenset(
    {FOREIGN_OWNER, SILENT_WHILE_PANE_ACTIVE}
)


class PaneReading(NamedTuple):

    dead: bool
    piped: bool
    activity_epoch: Optional[int]
    signature: str
    owner: str


def parse_reading(raw: str) -> Optional[PaneReading]:
    text = raw.strip("\n")
    if not text:
        return None
    parts = text.split(FIELD_SEPARATOR, 4)
    if len(parts) != 5:
        return None
    dead_raw, piped_raw, activity_raw, signature, owner = parts
    try:
        activity: Optional[int] = int(activity_raw.strip())
    except ValueError:
        activity = None
    return PaneReading(
        dead=dead_raw.strip() == "1",
        piped=piped_raw.strip() == "1",
        activity_epoch=activity,
        signature=signature.strip(),
        owner=owner.strip(),
    )


def classify_ownership(
    reading: PaneReading,
    expected_path: str,
    file_exists: bool,
    legacy_paths: frozenset = frozenset(),
) -> str:
    if reading.dead:
        return PANE_DEAD
    if not reading.piped:
        return NO_PIPE
    if not reading.owner:
        return NO_OWNER_RECORDED
    if reading.owner != expected_path:
        if reading.owner in legacy_paths:
            return LEGACY_OWNER
        return FOREIGN_OWNER
    if not file_exists:
        return FILE_MISSING
    return OWNED


class SilenceTracker:

    def __init__(
        self,
        silence_seconds: float = PIPE_LIVENESS_SILENCE_SECONDS,
        now: Optional[float] = None,
        wall_now: Optional[float] = None,
    ) -> None:
        self._silence = silence_seconds
        self._last_bytes_at: float = time.monotonic() if now is None else now
        self._last_bytes_wall: float = (
            time.time() if wall_now is None else wall_now
        )
        self._last_probe_at: Optional[float] = None
        self._last_signature: Optional[str] = None

    def note_bytes(self, now: Optional[float] = None,
                   wall_now: Optional[float] = None) -> None:
        self._last_bytes_at = time.monotonic() if now is None else now
        self._last_bytes_wall = time.time() if wall_now is None else wall_now
        self._last_signature = None

    def due(self, now: float, has_viewers: bool) -> bool:
        if not has_viewers:
            return False
        if now - self._last_bytes_at < self._silence:
            return False
        if (
            self._last_probe_at is not None
            and now - self._last_probe_at < self._silence
        ):
            return False
        return True

    def verdict(
        self,
        reading: Optional[PaneReading],
        expected_path: str,
        now: float,
        file_exists: bool = True,
        legacy_paths: frozenset = frozenset(),
    ) -> str:
        """Read one probe and say what it proves. Records the baseline.

        Description: runs :func:`classify_ownership` first, so a
            recorded theft, a dead pane, a stopped copier and a missing
            file all answer exactly as they do on the attach path - one
            classifier, not two that drift.

            Only when THAT says the copier is ours do the two silence
            rungs run:

            1. ``#{window_activity}`` is NEWER than the wall clock of our
               last received byte. The pane produced output after we last
               got anything, so somebody else has it. This works on the
               FIRST probe, with no earlier reading to compare against.
            2. the pane signature CHANGED between this probe and the one
               before it. tmux stamps activity at one-second resolution,
               so output landing inside the same second as our last byte
               is invisible to rung 1; this catches it on the next pass.

            Neither rung can fire on a genuinely quiet pane, which is why
            silence is only ever the trigger for looking.

            A reading of None - tmux could not be asked or answered
            nonsense - returns :data:`QUIET` and changes nothing.
            UNMEASURED IS NOT STOLEN, exactly as unmeasured is not dead.
        Inputs:
            reading: the parsed probe answer, or None.
            expected_path: absolute path this server tails, as a string.
            now: monotonic seconds; stamps the probe for :meth:`due`.
            file_exists: whether the tailed path exists right now.
            legacy_paths: previous-rule paths for this session; see
                :func:`classify_ownership`.
        Output:
            str - a verdict constant. Membership of
            :data:`REISSUE_VERDICTS` means re-issue; membership of
            :data:`THEFT_VERDICTS` means it was taken rather than never
            started.
        Example: tracker.verdict(reading, "/tmp/a.pipe", time.monotonic())
        """
        self._last_probe_at = now
        if reading is None:
            return QUIET

        ownership = classify_ownership(
            reading, expected_path, file_exists, legacy_paths
        )
        if ownership != OWNED:
            self._last_signature = None
            return ownership

        previous_signature = self._last_signature
        self._last_signature = reading.signature

        if (
            reading.activity_epoch is not None
            and reading.activity_epoch > int(self._last_bytes_wall)
        ):
            return SILENT_WHILE_PANE_ACTIVE
        if (
            previous_signature is not None
            and previous_signature != reading.signature
        ):
            return SILENT_WHILE_PANE_ACTIVE
        return QUIET
