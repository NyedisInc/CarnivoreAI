
from __future__ import annotations

import re
DEFAULT_DIM = 0.90

MIN_DIM = 0.0
MAX_DIM = 1.0

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif")

MASCOT_EXTENSIONS = IMAGE_EXTENSIONS + (".svg",)

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}$")

MAX_NAME_LENGTH = 96

SNIFF_LENGTH = 32

CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
}


def sniff_image_extension(head: bytes) -> "str | None":
    if not isinstance(head, (bytes, bytearray)):
        return None
    data = bytes(head)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "avif"
    return None


def content_type_for_extension(ext: str) -> "str | None":
    if not isinstance(ext, str):
        return None
    return CONTENT_TYPES.get(ext.lower())


class UnsafeImageName(ValueError):
    """A theme named an image file it is not allowed to name.

    Carries a machine-readable ``reason`` so a log line and a refusal
    message can both say which rule was broken without re-deriving it.
    """

    def __init__(self, reason: str, value: str) -> None:
        super().__init__(f"unsafe theme image name ({reason}): {value!r}")
        self.reason = reason
        self.value = value


def safe_image_filename(
    value: object, extensions: tuple = IMAGE_EXTENSIONS
) -> str:
    """Accept a theme's image filename, or refuse it outright.

    Description: THE ONE DECISION ABOUT WHAT A THEME MAY NAME. It is an
      allowlist: a single path segment matching :data:`_SAFE_NAME_RE` and
      ending in one of :data:`IMAGE_EXTENSIONS`. Nothing is stripped,
      normalised or rewritten - a value that is not already safe is refused,
      because "sanitise then use" is how a check and the thing it protects
      end up disagreeing.

      THE ORDER OF THE CHECKS IS FOR THE HUMAN READING THE LOG, not for
      correctness: the regexp alone would refuse every case below. Naming
      ``traversal`` and ``scheme`` separately is what makes an install-time
      refusal readable as an attempted escape rather than as a typo.
    Inputs: value (object) - whatever the manifest carried; extensions
      (tuple of str) - the accepted suffixes, :data:`IMAGE_EXTENSIONS` by
      default (a theme's mascot sprite passes :data:`MASCOT_EXTENSIONS`).
    Output: str - the filename, unchanged, when it is safe.
    Raises: :class:`UnsafeImageName` for every other input.
    Example:
        >>> safe_image_filename("grid.png")
        'grid.png'
        >>> safe_image_filename("../../etc/passwd")
        Traceback (most recent call last):
        ...
        src.core.terminal_background.UnsafeImageName: unsafe theme image name (separator): '../../etc/passwd'
    """
    if not isinstance(value, str):
        raise UnsafeImageName("not_a_string", repr(value))
    if not value:
        raise UnsafeImageName("empty", value)
    if len(value) > MAX_NAME_LENGTH:
        raise UnsafeImageName("too_long", value)
    if "/" in value or "\\" in value:
        raise UnsafeImageName("separator", value)
    if ".." in value:
        raise UnsafeImageName("traversal", value)
    if ":" in value:
        raise UnsafeImageName("scheme", value)
    if "%" in value:
        raise UnsafeImageName("escape", value)
    if not _SAFE_NAME_RE.match(value):
        raise UnsafeImageName("charset", value)
    if not value.lower().endswith(extensions):
        raise UnsafeImageName("extension", value)
    return value


def clamp_dim(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_DIM
    number = float(value)
    if number != number:
        return DEFAULT_DIM
    return max(MIN_DIM, min(MAX_DIM, number))
