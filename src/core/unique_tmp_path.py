
from __future__ import annotations

import os
import uuid
from pathlib import Path


def unique_tmp_path(path: Path) -> Path:
    """A temp sibling of ``path`` that no concurrent writer can also pick.

    Description: the temp file carries the calling process's pid and a
      random 8-hex-character suffix, so two writers - in this process or
      in another one - can never stream into the same fd. It lives in
      the SAME directory as ``path`` so the caller's rename into place
      stays within one filesystem and therefore atomic.

      The name is also why a caller must clean up after a failed write:
      a fixed name self-limits to one orphan on disk; a unique one left
      behind on every failure would litter the state directory with a
      fresh corpse each time.
    Inputs: path (Path) - the destination file, not required to exist yet.
    Output: Path - a sibling of ``path`` in the same directory.
    Example:
        >>> unique_tmp_path(Path("/s/state.json")).name
        'state.json.4321.9f0a1b2c.tmp'   # pid and suffix vary
    """
    return path.with_suffix(
        f"{path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
