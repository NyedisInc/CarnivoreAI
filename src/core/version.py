
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
