
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Annotated, Any, Callable, Dict, FrozenSet, List, Literal, NamedTuple, Optional, Sequence, Union

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.cplugs.huddle import rules
from src.cplugs.sdk import app_info

logger = structlog.get_logger()

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
RUN_TIMEOUT_S = 10.0
_CHILD_ENV_KEYS = ("PATH", "HOME", "GH_TOKEN", "LANG")
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@{}^~-]{0,199}$")
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
MAX_TEXT = 200
NO_REPO = "this install has no git repository to check; set CARNIVORE_REPO_ROOT to the app's repo"


class Verdict(NamedTuple):

    status: str
    what: str


class _Check(BaseModel):
    """Base of every check: no extra fields, whitespace trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VersionLive(_Check):

    kind: Literal["version_live"]
    version: str = Field(min_length=1, max_length=64)


class GitContains(_Check):

    kind: Literal["git_contains"]
    repo: str = Field(min_length=1, max_length=MAX_TEXT)
    ref: str = Field(min_length=1, max_length=MAX_TEXT)
    sha: str

    @field_validator("sha")
    @classmethod
    def _sha(cls, value: str) -> str:
        if not _SHA.match(value):
            raise ValueError("sha must be 7 to 64 hex characters")
        return value.lower()

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        if not _REF.match(value):
            raise ValueError("ref must be a plain branch, tag or commit name")
        return value


class _GithubCheck(_Check):

    repo: str
    number: int = Field(ge=1, le=10_000_000)

    @field_validator("repo")
    @classmethod
    def _repo(cls, value: str) -> str:
        if not _SLUG.match(value):
            raise ValueError("repo must look like owner/repo")
        return value


class IssueClosed(_GithubCheck):

    kind: Literal["issue_closed"]


class PrMerged(_GithubCheck):

    kind: Literal["pr_merged"]


class ItemState(_Check):

    kind: Literal["item_state"]
    item: int = Field(ge=1)
    state: str

    @field_validator("state")
    @classmethod
    def _state(cls, value: str) -> str:
        state = rules.canonical_state(value)
        if state not in rules.STATES:
            raise ValueError(f"state must be one of {', '.join(rules.STATES)}")
        return str(state)


class SessionIdle(_Check):

    kind: Literal["session_idle"]
    session: str = Field(min_length=1, max_length=MAX_TEXT)


class FileExists(_Check):

    kind: Literal["file_exists"]
    path: str = Field(min_length=1, max_length=1000)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if "\0" in value or not os.path.isabs(value) or ".." in Path(value).parts:
            raise ValueError("path must be absolute with no .. part")
        return value


class UrlOk(_Check):

    kind: Literal["url_ok"]
    url: str = Field(min_length=1, max_length=1000)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("url must be http or https with a host")
        return value


Check = Annotated[Union[VersionLive, GitContains, IssueClosed, PrMerged, ItemState, SessionIdle, FileExists, UrlOk], Field(discriminator="kind")]
KINDS = ("version_live", "git_contains", "issue_closed", "pr_merged", "item_state", "session_idle", "file_exists", "url_ok")
EVENT_KINDS = ("item_state",)


class _Wrapper(BaseModel):
    """Holder so one discriminated union can be validated from a bare dict."""

    check: Check


def parse(raw: Any) -> BaseModel:
    if not isinstance(raw, dict):
        raise rules.TaskManagerInvalid(f"check must be an object with a kind: one of {', '.join(KINDS)}")
    try:
        return _Wrapper.model_validate({"check": raw}).check
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"][1:])
        raise rules.TaskManagerInvalid(f"check is not valid ({where or 'kind'}: {first['msg']}); the menu is {', '.join(KINDS)}") from None


def describe(check: BaseModel) -> str:
    if isinstance(check, VersionLive):
        return f"version {check.version} is live"
    if isinstance(check, GitContains):
        return f"{check.ref} contains {check.sha[:10]}"
    if isinstance(check, IssueClosed):
        return f"{check.repo}#{check.number} is closed"
    if isinstance(check, PrMerged):
        return f"{check.repo}#{check.number} is merged"
    if isinstance(check, ItemState):
        return f"item {check.item} reached {check.state}"
    if isinstance(check, SessionIdle):
        return f"session {check.session} is idle"
    if isinstance(check, FileExists):
        return f"{check.path} exists"
    return f"{check.url} answers"  # type: ignore[attr-defined]


def _child_env() -> Dict[str, str]:
    return {k: os.environ[k] for k in _CHILD_ENV_KEYS if k in os.environ}


def app_repo_roots(root: Optional[Path] = None) -> List[Path]:
    found = root if root is not None else app_info.repo_root()
    if found is None:
        return []
    base = found.resolve()
    roots = [base]
    try:
        done = subprocess.run(["git", "-C", str(base), "worktree", "list", "--porcelain"], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT_S, env=_child_env(), check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("task_manager_wait_worktrees_unreadable", error=str(exc)[:200])
        return roots
    for line in done.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):]).resolve()
            if path not in roots:
                roots.append(path)
    return roots


def _run(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=RUN_TIMEOUT_S, env=_child_env(), check=False)


def check_git(check: GitContains, roots: Optional[Sequence[Path]] = None) -> Verdict:
    allowed = list(roots) if roots is not None else app_repo_roots()
    if not allowed:
        return Verdict(UNKNOWN, NO_REPO)
    repo = Path(check.repo).resolve()
    if repo not in allowed:
        return Verdict(UNKNOWN, f"{check.repo} is not one of the app's repos")
    try:
        done = _run(["git", "-C", str(repo), "merge-base", "--is-ancestor", check.sha, check.ref])
    except (OSError, subprocess.SubprocessError) as exc:
        return Verdict(UNKNOWN, f"git could not run: {type(exc).__name__}")
    what = describe(check)
    if done.returncode == 0:
        return Verdict(PASS, what)
    return Verdict(FAIL if done.returncode == 1 else UNKNOWN, what)


def check_github(check: _GithubCheck) -> Verdict:
    route = "pulls" if isinstance(check, PrMerged) else "issues"
    field = "merged" if isinstance(check, PrMerged) else "state"
    try:
        done = _run(["gh", "api", f"repos/{check.repo}/{route}/{check.number}", "--jq", f".{field}"])
    except (OSError, subprocess.SubprocessError) as exc:
        return Verdict(UNKNOWN, f"gh could not run: {type(exc).__name__}")
    what = describe(check)
    if done.returncode != 0:
        return Verdict(UNKNOWN, f"{what}: github did not answer (no auth or no access)")
    answer = done.stdout.strip()
    if answer in ("closed", "true"):
        return Verdict(PASS, what)
    return Verdict(FAIL if answer in ("open", "false") else UNKNOWN, what)


def check_version(check: VersionLive, reader: Optional[Callable[[], str]] = None) -> Verdict:
    try:
        live = (reader or app_info.app_version)()
    except (ImportError, OSError, ValueError) as exc:
        return Verdict(UNKNOWN, f"version unreadable: {type(exc).__name__}")
    if not live:
        return Verdict(UNKNOWN, "version unreadable")
    return Verdict(PASS if live == check.version else FAIL, describe(check))


def check_file(check: FileExists) -> Verdict:
    try:
        return Verdict(PASS if Path(check.path).exists() else FAIL, describe(check))
    except OSError as exc:
        return Verdict(UNKNOWN, f"{check.path} unreadable: {type(exc).__name__}")


def host_allowed(url: str, extra_hosts: Sequence[str] = ()) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not host:
        return False
    if host in {h.strip().lower() for h in extra_hosts if h.strip()}:
        return True
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D102
        return None


def check_url(check: UrlOk, extra_hosts: Sequence[str] = ()) -> Verdict:
    if not host_allowed(check.url, extra_hosts):
        return Verdict(UNKNOWN, "url host is not loopback or on the allow-list")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(urllib.request.Request(check.url, method="GET"), timeout=RUN_TIMEOUT_S) as response:  # noqa: S310
            return Verdict(PASS if 200 <= response.status < 300 else FAIL, describe(check))
    except urllib.error.HTTPError:
        return Verdict(FAIL, describe(check))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Verdict(FAIL, f"{check.url}: {type(exc).__name__}")


_IDLE_STATUSES = frozenset({"idle", "finished_unread"})


async def check_session(check: SessionIdle, ops: Any) -> Verdict:
    try:
        infos = await ops.list()
        keys = await ops.durable_keys(infos)
    except (OSError, RuntimeError, AttributeError) as exc:
        return Verdict(UNKNOWN, f"sessions unreadable: {type(exc).__name__}")
    found = next((i for i in infos if check.session in (i.session.id, keys.get(i.session.id))), None)
    status = getattr(found, "activity_status", None) if found is not None else None
    if status is None:
        return Verdict(UNKNOWN, f"session {check.session} has no measured status")
    return Verdict(PASS if status in _IDLE_STATUSES else FAIL, describe(check))


async def run(check: BaseModel, *, ops: Any = None, extra_hosts: Sequence[str] = ()) -> Verdict:
    if isinstance(check, SessionIdle):
        return await check_session(check, ops)
    if isinstance(check, VersionLive):
        return await asyncio.to_thread(check_version, check)
    if isinstance(check, GitContains):
        return await asyncio.to_thread(check_git, check)
    if isinstance(check, (IssueClosed, PrMerged)):
        return await asyncio.to_thread(check_github, check)
    if isinstance(check, FileExists):
        return await asyncio.to_thread(check_file, check)
    if isinstance(check, UrlOk):
        return await asyncio.to_thread(check_url, check, extra_hosts)
    return Verdict(UNKNOWN, "this check runs on a state change, not on a timer")
