"""Trimming the pipe-pane output file WITHOUT moving it.

WHY THIS IS NOT A RENAME, AND IT WAS MEASURED. ``pipe-pane`` runs
``cat >> <path>`` in a shell. That redirection performs exactly ONE
``open(2)``, when the pipe is established, and the shell holds the
descriptor for the life of the pipe. It does not reopen the path per
write, so a descriptor - not a name - is what tmux is writing through.

So a rename does not rotate anything. It moves the live file out from
under its own name and leaves a decoy behind, with three consequences
that compound:

* Nothing is reclaimed. The file tmux is filling is simply called
  something else now.
* The size trigger disarms itself permanently, because the next check
  stats the 0-byte decoy and can never see it exceed the threshold
  again. Only the 24 hour age trigger fires after that.
* The NEXT rotation unlinks ``<name>.1`` - the file the writer still
  holds open - so the bytes keep accumulating on an inode with no
  directory entry: invisible to ``ls``, and not reclaimable until the
  pane dies.

The reader, notably, is FINE throughout. It holds a descriptor on the
same inode the writer is appending to, so the rename is invisible to
the stream and the terminal never goes silent. That matters because the
obvious repair - re-pointing the reader at the freshly created path -
would move it onto the decoy nothing writes to and cause exactly the
silence the rename does not.

TRUNCATE IN PLACE IS WHAT WORKS, AND ITS PRECONDITION WAS ALSO
MEASURED. ``>>`` opens with ``O_APPEND``, so every write atomically
seeks to the current end of file before landing. Truncate the file to
zero and the writer's next write goes to offset 0 with no gap: verified on the same socket, a small file truncated under a live pipe came
back at 59 bytes holding the next line, on the same inode, with no
sparse re-grow. A writer WITHOUT ``O_APPEND`` would keep its own offset
and re-create the file at its old length as a hole, which is why this
is a precondition worth stating rather than an implementation detail.

The reader must then seek back to 0 itself, because its own offset is
still out at the old end of file and everything before that offset now
reads as EOF.

WHAT IS DELIBERATELY NOT DONE HERE. No ``<name>.1`` generation is kept.
Nothing in this codebase ever opens that file - ``session_import_evidence``
matches names ending in ``.pipe`` and a ``.pipe.1`` is not one - and the
bytes have already been streamed to the browser and are still in tmux's
own scrollback. Copying up to ``MAX_LOG_BYTES`` synchronously to keep a
generation nobody reads would stall the event loop for the whole copy,
which is the cost this project has repeatedly paid elsewhere. Disk is
therefore bounded at one threshold rather than two.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

__all__ = ["rotation_reason", "truncate_in_place"]


def rotation_reason(
    size_bytes: int,
    age_hours: float,
    max_bytes: int,
    max_age_hours: float,
) -> Optional[str]:
    if size_bytes > max_bytes:
        return "size"
    if age_hours > max_age_hours:
        return "age"
    return None


def truncate_in_place(pipe_path: Path, read_fd: int) -> bool:
    try:
        os.truncate(str(pipe_path), 0)
    except OSError as exc:
        logger.warning(
            "tmux_pipe_truncate_failed", path=str(pipe_path), error=str(exc)
        )
        return False

    try:
        os.lseek(read_fd, 0, os.SEEK_SET)
    except OSError as exc:
        logger.error(
            "tmux_pipe_reseek_failed", path=str(pipe_path), error=str(exc)
        )
        return False

    return True
