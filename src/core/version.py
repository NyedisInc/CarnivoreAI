"""Single source of version truth for Cloude Code.

THE RULE: a release is a GIT TAG. Everything that displays or compares a
version derives from that tag - the release workflow, the header chip in the
web client, and the release self check in ``update_check.py``. Two version
strings that can disagree is a stale-doc bug waiting to happen, so there is
exactly one resolver and it lives here.

Resolution order, first hit wins:

1. ``CLOUDE_APP_VERSION`` environment variable. The Electron shell injects
   the installed version this way at spawn (``macOS/server-manager.js``).
2. A ``VERSION`` file at the source root. GENERATED, not hand-written:
   ``macOS/bootstrap.js`` stamps it into the Application Support copy on
   every packaged launch. It carries a header saying so. This is the only
   source that survives on disk in production, where there is no ``.git``
   and no ``macOS/package.json``.
3. An EXACT git tag on HEAD (``git describe --tags --exact-match``). Covers
   an install whose VERSION file went missing but whose checkout is still
   parked on the release tag.
4. ``macOS/package.json``. Legacy fallback so the chip is not blank on an old
   layout, and so a dev tree sitting between releases shows a clean number.
5. A LOOSE ``git describe --tags``, for example "0.8.1-3-gabc1234". Last,
   deliberately: it is the most honest answer but the ugliest, and it is not
   a release tag, so the self check will correctly report "this install is
   not at a release tag" when it is what resolved.

Every step can fail. When all five fail the resolver returns "" and callers
render nothing rather than a wrong literal.

THE TWO GIT STEPS ARE PINNED TO THE ROOT. ``git -C <dir>`` searches upwards
for a repository, so a directory that merely sits inside some unrelated
checkout will happily answer with that checkout's tags. See
:func:`is_git_root`. Blank is a correct answer; another project's version is
not.
"""

from __future__ import annotations

import json
import subprocess
from src.core.dev_tools import git_guard
from pathlib import Path

from src.core.product_identity import env_value

VERSION_FILE_HEADER = (
    "# GENERATED FROM THE GIT TAG AT RELEASE TIME. DO NOT EDIT BY HAND.\n"
    "# See src/core/version.py for the resolution order.\n"
)

VERSION_FILENAME = "VERSION"

_GIT_TIMEOUT_SECONDS = 5.0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_tag(tag: str) -> str:
    return tag.strip().lstrip("vV").strip()


def read_version_file(root: Path | None = None) -> str:
    path = (root or repo_root()) / VERSION_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return normalize_tag(stripped)
    return ""


def write_version_file(version: str, root: Path | None = None) -> Path:
    path = (root or repo_root()) / VERSION_FILENAME
    path.write_text(f"{VERSION_FILE_HEADER}{normalize_tag(version)}\n", encoding="utf-8")
    return path


def is_git_root(root: Path) -> bool:
    """Is ``root`` itself the top of a git work tree?

    THIS GUARD IS LOAD-BEARING, NOT A NICETY. ``git -C <dir>`` walks UPWARDS
    until it finds a repository, so an unversioned directory that merely SITS
    somewhere inside a checkout answers with that checkout's tags. In
    production the source root is a plain copy under Application Support with
    no ``.git`` of its own; if that copy is ever placed inside any repository
    the resolver would report a completely unrelated project's version, with
    no error, and a wrong literal is exactly what the "" fallback exists to
    prevent. So git is only consulted when the root IS the work tree.

    Args:
        root: the directory to test.

    Returns:
        True when ``git rev-parse --show-toplevel`` from ``root`` resolves to
        ``root`` itself. False when git is absent, the path is not a work
        tree, or the work tree is some ancestor.
    """
    if not git_guard.git_available():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    toplevel = result.stdout.strip()
    if not toplevel:
        return False
    try:
        return Path(toplevel).resolve() == Path(root).resolve()
    except OSError:
        return False


def _git_describe(root: Path | None, args: list[str]) -> str:
    cwd = root or repo_root()
    if not is_git_root(cwd):
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "describe"] + args,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return normalize_tag(result.stdout)


def exact_git_tag(root: Path | None = None) -> str:
    return _git_describe(root, ["--tags", "--exact-match", "HEAD"])


def describe_git_tag(root: Path | None = None) -> str:
    return _git_describe(root, ["--tags"])


def read_package_json_version(root: Path | None = None) -> str:
    path = (root or repo_root()) / "macOS" / "package.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            return normalize_tag(str(json.load(handle).get("version", "")))
    except (OSError, ValueError):
        return ""


def resolve_version(root: Path | None = None) -> str:
    env_version = normalize_tag(env_value("APP_VERSION") or "")
    if env_version:
        return env_version
    return (
        read_version_file(root)
        or exact_git_tag(root)
        or read_package_json_version(root)
        or describe_git_tag(root)
    )


# CLOUDE_APP_VERSION

_startup_version: str | None = None


def freeze_startup_version(root: Path | None = None) -> str:
    global _startup_version
    if _startup_version is None:
        _startup_version = resolve_version(root)
    return _startup_version


def startup_version() -> str:
    return freeze_startup_version()


def reset_startup_version() -> None:
    global _startup_version
    _startup_version = None
