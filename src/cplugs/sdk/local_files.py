
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Tuple

from src.cplugs.sdk.tools import AgentCaller, ToolError
from src.cplugs.sdk.uploads import UploadRefused, caps, check_bytes


def read_local_file(caller: AgentCaller, path_text: Any, *, argument: str = "file_paths") -> Tuple[bytes, str]:
    """The bytes and safe name of a file a pane named.

    Inputs: caller (the MCP caller; a token is refused); path_text (str, an absolute path); argument (the argument's name, for messages).
    Output: (bytes, sanitized basename). Raises: ToolError (a token caller, not absolute, not a regular file, a symlink, over the larger
      upload cap, unreadable, or refused by the upload rule).
    Example: data, name = read_local_file(pane, "/Users/me/shot.png")
    """
    if caller.from_token:
        raise ToolError(f"{argument} names a file on this computer, so only a session running here may pass it; send the file's content instead")
    if not isinstance(path_text, str) or not path_text or not os.path.isabs(path_text):
        raise ToolError(f"{argument}: each entry must be an absolute path to a file")
    limit = max(caps())
    try:
        fd = os.open(path_text, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ToolError(f"{argument}: {path_text} cannot be opened (a symlink is refused): {exc.strerror}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ToolError(f"{argument}: {path_text} is not a regular file")
        if st.st_size > limit:
            raise ToolError(f"{argument}: {path_text} is {st.st_size} bytes, over the {limit // (1024 * 1024)} MB upload cap")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise ToolError(f"{argument}: {path_text} could not be read: {exc.strerror}") from exc
    finally:
        os.close(fd)
    if len(data) > limit:
        raise ToolError(f"{argument}: {path_text} grew past the {limit // (1024 * 1024)} MB upload cap while it was read")
    try:
        return check_bytes(data, Path(path_text).name)
    except UploadRefused as exc:
        raise ToolError(f"{argument}: {path_text}: {exc}") from exc
