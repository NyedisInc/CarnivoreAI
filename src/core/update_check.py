"""Background release-tag self check.

    current           we fetched the remote tag list, compared, we are newest
    update_available  we fetched the list and a newer tag exists (named)
    unknown           we could NOT look: offline, no git, remote unreachable,
                      timed out, or the local version did not resolve

``unknown`` is its own visible state and must never render as "up to date".
Collapsing "I could not look" into "nothing is wrong" is the single defect
class this project has spent the most time killing.

DESIGN NOTES

* Only a development checkout is asked. A source root with no ``.git`` entry (a packaged install) and no explicit
  ``updates.remote`` is NOT APPLICABLE: ``refresh()`` returns None, runs no git, stores nothing, and the version
  route reports ``update: null``. Not applicable is neither current nor unknown.
* Never blocks. The HTTP endpoint returns whatever is cached; the network
  call happens on a background thread kicked off after startup and then on a
  refresh interval. A page load never waits on a remote.
* The cached answer carries ``checked_at``, and the client shows it, so a
  stale answer is visibly stale rather than silently wrong.
* NEVER auto-updates. It reports, and offers the command. Pulling code out
  from under a running agent session unattended is not acceptable. The
  distribution channel is the signed-by-nobody .dmg built by
  ``macOS/package.json``, so the offered command opens the releases page.
  This is a notice for the web UI only; the Mac app's tray and menu follow
  electron-updater (``macOS/auto-update.js``, #660), the one update path.
* Which remote: the checkout's own ``origin`` when the source root IS a git
  work tree, because a dev running from a fork should be told about that
  fork's tags. A packaged install has no ``origin`` (see
  ``discover_origin_remote``) and falls through to FALLBACK_REMOTE, the
  public upstream the .dmg is released from. ``updates.remote`` in
  config.json overrides both with an explicit URL.
"""

from __future__ import annotations

import json
import re
import subprocess
from src.core.dev_tools import git_guard
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import structlog

from src.core.notifications.sources import update as update_source
from src.core.product_identity import RELEASE_REPO
from src.core.version import (
    is_git_root,
    normalize_tag,
    repo_root,
    resolve_version,
)

logger = structlog.get_logger()

STATUS_CURRENT = "current"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_UNKNOWN = "unknown"

DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60

LS_REMOTE_TIMEOUT_SECONDS = 20.0

_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_LS_REMOTE_REF_RE = re.compile(r"refs/tags/(\S+?)(?:\^\{\})?$")

FALLBACK_REMOTE = f"https://github.com/{RELEASE_REPO}.git"

DEFAULT_UPGRADE_COMMAND = f"open https://github.com/{RELEASE_REPO}/releases/latest"

CACHE_FILENAME = ".update-check.json"


def default_cache_path(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / CACHE_FILENAME


class UpdateCheckError(RuntimeError):
    pass


@dataclass
class UpdateStatus:

    status: str
    current_version: str
    latest_version: str
    remote: str
    checked_at: float
    reason: str
    upgrade_command: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_version(tag: str) -> Optional[tuple[int, int, int]]:
    match = _TAG_RE.match(tag.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def read_configured_remote(config_path: Path) -> str:
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    updates = data.get("updates")
    if not isinstance(updates, dict):
        return ""
    return str(updates.get("remote", "")).strip()


def discover_origin_remote(root: Path) -> str:
    if not is_git_root(root):
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def is_work_tree(root: Path) -> bool:
    """Tell, without running git, whether ``root`` carries its own ``.git`` entry.

    A packaged install copies the server into Application Support with no ``.git``; a development checkout (or a
    linked worktree, whose ``.git`` is a file) has one. Reading the filesystem keeps a stock Mac from ever seeing
    Apple's developer-tools dialog.

    Args:
        root: the source root.

    Returns:
        True when ``<realpath of root>/.git`` exists.
    """
    try:
        return (Path(root).resolve() / ".git").exists()
    except OSError:
        return False


def fetch_remote_tags(remote: str) -> list[str]:
    """List release tags on a remote without cloning or fetching objects.

    Args:
        remote: a git remote URL.

    Returns:
        Sorted-by-version list of plain release tags, newest last.

    Raises:
        UpdateCheckError: git is absent, the remote is unreachable, the call
            timed out, or the output could not be parsed.
    """
    if not git_guard.git_available():
        raise UpdateCheckError("git is not installed")
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", remote],
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise UpdateCheckError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateCheckError("the release remote did not answer in time") from exc
    except OSError as exc:
        raise UpdateCheckError(f"could not run git: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else "no detail"
        raise UpdateCheckError(f"could not reach the release remote: {tail}")

    tags: list[tuple[tuple[int, int, int], str]] = []
    for line in result.stdout.splitlines():
        match = _LS_REMOTE_REF_RE.search(line)
        if not match:
            continue
        tag = match.group(1)
        parsed = parse_version(tag)
        if parsed is not None:
            tags.append((parsed, normalize_tag(tag)))
    tags.sort()
    return [tag for _, tag in tags]


class UpdateChecker:

    def __init__(
        self,
        config_path: Path,
        root: Optional[Path] = None,
        cache_path: Optional[Path] = None,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        upgrade_command: str = DEFAULT_UPGRADE_COMMAND,
    ) -> None:
        self._config_path = config_path
        self._root = root or repo_root()
        self._cache_path = cache_path or default_cache_path(self._root)
        self._interval = interval_seconds
        self._upgrade_command = upgrade_command
        self._lock = threading.Lock()
        self._status: UpdateStatus = self._load_cache() or self._unknown(
            "no check has run yet"
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None


    def status(self) -> UpdateStatus:
        with self._lock:
            return self._status

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="update-check", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def applicable(self) -> bool:
        return is_work_tree(self._root) or bool(read_configured_remote(self._config_path))

    def refresh(self) -> Optional[UpdateStatus]:
        if not self.applicable():
            return None
        remote = self.resolve_remote()
        current = resolve_version(self._root)
        if not current:
            return self._store(self._unknown("the installed version did not resolve", remote))

        parsed_current = parse_version(current)
        if parsed_current is None:
            return self._store(
                self._unknown(
                    f"this install is at {current}, which is not a release tag", remote
                )
            )

        try:
            tags = fetch_remote_tags(remote)
        except UpdateCheckError as exc:
            return self._store(self._unknown(str(exc), remote, current))

        if not tags:
            return self._store(
                self._unknown("the remote published no release tags", remote, current)
            )

        ranked = [(parse_version(tag), tag) for tag in tags]
        ranked = [(parsed, tag) for parsed, tag in ranked if parsed is not None]
        if not ranked:
            return self._store(
                self._unknown("the remote published no release tags", remote, current)
            )
        parsed_latest, latest = max(ranked)
        newer = parsed_latest > parsed_current
        return self._store(
            UpdateStatus(
                status=STATUS_UPDATE_AVAILABLE if newer else STATUS_CURRENT,
                current_version=current,
                latest_version=latest,
                remote=remote,
                checked_at=time.time(),
                reason="",
                upgrade_command=self._upgrade_command,
            )
        )

    def resolve_remote(self) -> str:
        return (
            read_configured_remote(self._config_path)
            or discover_origin_remote(self._root)
            or FALLBACK_REMOTE
        )


    def _loop(self) -> None:
        if self._stop.wait(30):
            return
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception:  # noqa: BLE001
                logger.warning("update_check_refresh_failed", exc_info=True)
            if self._stop.wait(self._interval):
                return

    def _unknown(self, reason: str, remote: str = "", current: str = "") -> UpdateStatus:
        """Build an UNKNOWN status.

        Args:
            reason: short human sentence describing what could not be done.
            remote: the remote that was being consulted, if known.
            current: the installed version, if it resolved.

        Returns:
            An UpdateStatus in STATUS_UNKNOWN.
        """
        return UpdateStatus(
            status=STATUS_UNKNOWN,
            current_version=current,
            latest_version="",
            remote=remote,
            checked_at=time.time(),
            reason=reason,
            upgrade_command=self._upgrade_command,
        )

    def _store(self, status: UpdateStatus) -> UpdateStatus:
        with self._lock:
            self._status = status
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(status.to_dict(), indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("update_check_cache_write_failed", error=str(exc))
        if status.status == STATUS_UPDATE_AVAILABLE:
            update_source.on_available(status.latest_version)
        return status

    def _load_cache(self) -> Optional[UpdateStatus]:
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return UpdateStatus(
                status=str(data["status"]),
                current_version=str(data.get("current_version", "")),
                latest_version=str(data.get("latest_version", "")),
                remote=str(data.get("remote", "")),
                checked_at=float(data.get("checked_at", 0.0)),
                reason=str(data.get("reason", "")),
                upgrade_command=str(data.get("upgrade_command", self._upgrade_command)),
            )
        except (KeyError, TypeError, ValueError):
            return None
