
from __future__ import annotations


def unsafe_name_reason(name: str) -> str | None:
    if "\0" in name:
        return f"member name contains a NUL: {name!r}"
    if name.startswith("/"):
        return f"absolute member path: {name!r}"
    if ".." in name.split("/"):
        return f"member path escapes with '..': {name!r}"
    return None


def unsafe_relpath_reason(relpath: str, name: str) -> str | None:
    reason = unsafe_name_reason(relpath)
    if reason is not None:
        return f"{reason} (derived from member {name!r})"
    segments = relpath.split("/")
    if "" in segments:
        return f"empty path segment in member: {name!r}"
    if "." in segments:
        return f"'.' path segment in member: {name!r}"
    return None
