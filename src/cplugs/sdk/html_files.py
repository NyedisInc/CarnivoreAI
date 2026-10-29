
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.cplugs.sdk.tools import ToolError

SUFFIXES = (".html", ".htm")


def read_html_file(path_text: Any, max_bytes: int, *, argument: str = "file_path") -> str:
    """The text of the page file an agent named.

    Inputs: path_text (str) - an absolute path; max_bytes (int) - the largest file read; argument (str) - the argument's name, for messages.
    Output: str (UTF-8 text). Raises: ToolError (not absolute, wrong suffix, not a regular file, a symlink, over the limit, not UTF-8).
    Example: read_html_file("/tmp/page.html", 2 * 1024 * 1024)
    """
    if not isinstance(path_text, str) or not path_text:
        raise ToolError(f"{argument} must be an absolute path to an .html file")
    path = Path(path_text)
    if not path.is_absolute() or path.suffix.lower() not in SUFFIXES:
        raise ToolError(f"{argument} must be an absolute path ending in .html or .htm")
    try:
        if path.is_symlink() or not path.is_file():
            raise ToolError(f"{argument} must be a regular file (a symlink is refused)")
        if path.stat().st_size > max_bytes:
            raise ToolError(f"the page is over {max_bytes} bytes ({max_bytes // (1024 * 1024)} MB)")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"could not read {argument} as UTF-8 text: {exc}") from exc
