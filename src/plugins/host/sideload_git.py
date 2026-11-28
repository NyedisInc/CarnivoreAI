
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import structlog

from src.core.json_artifact import UnreadableArtifact, atomic_write_json, read_for_update
from src.plugins.host import sideload
from src.plugins.host.sideload import SideloadRefused

logger = structlog.get_logger()

ALLOWED_PROTOCOLS: Tuple[str, ...] = ("https", "ssh")
GIT_TIMEOUT_SECONDS = 180
CHECKOUTS_DIR = "sideload-git"
RECORD_FILE = "sideload-git.json"
MAX_URL_CHARS = 2048
MAX_SUBDIR_CHARS = 512
MAX_ERROR_CHARS = 300

_SCP = re.compile(r"^(?:(?P<user>[A-Za-z0-9._~-]+)@)?(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*):(?P<path>[^:].*)$")
_REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/+-]{0,254}$")
_HEX = re.compile(r"^[0-9a-fA-F]{7,64}$")
_USERINFO = re.compile(r"(?<=://)[^/@\s]+@")
_GH_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_GH_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_GH_SHORTHAND = re.compile(r"^(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<repo>[A-Za-z0-9._-]{1,100})(?:@(?P<ref>.+))?$")

_lock = threading.RLock()


def _refuse_url(reason: str) -> SideloadRefused:
    return SideloadRefused("git_url_refused", f"{reason}; give an https or ssh url with no password or token in it", 422)


def check_url(url: object) -> str:
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        raise _refuse_url("the url is empty or too long")
    if url.startswith("-") or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise _refuse_url("the url starts with - or holds a space or control character")
    if "::" in url:
        raise _refuse_url("a transport helper url (ext::, fd::) is not allowed")
    if "://" in url:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in ALLOWED_PROTOCOLS:
            raise _refuse_url(f"the scheme {scheme or '(none)'} is not allowed")
        if parts.password is not None or (scheme == "https" and parts.username is not None):
            raise _refuse_url("the url carries a credential")
        if not parts.hostname or parts.hostname.startswith("-") or (parts.username or "").startswith("-"):
            raise _refuse_url("the url has no usable host")
        if parts.path in ("", "/"):
            raise _refuse_url("the url names no repository")
        return url
    found = _SCP.match(url)
    if found is None or "ssh" not in ALLOWED_PROTOCOLS:
        raise _refuse_url("a local path or file url is not allowed")
    return url


def parse_github_source(source: object, ref: Optional[str] = None) -> Tuple[str, str, str, Optional[str]]:
    if not isinstance(source, str) or not source or len(source) > MAX_URL_CHARS:
        raise SideloadRefused("git_url_refused", "source must be owner/repo or https://github.com/owner/repo", 422)
    text = source.strip()
    if text != source or text.startswith("-") or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in text) or "::" in text:
        raise SideloadRefused("git_url_refused", "invalid characters in GitHub source", 422)
    embedded_ref: Optional[str] = None
    if "://" in text:
        parts = urlsplit(text)
        if parts.scheme.lower() != "https" or (parts.hostname or "").lower() != "github.com":
            raise SideloadRefused("git_url_refused", "only https://github.com/owner/repo or owner/repo is allowed", 422)
        if parts.username is not None or parts.password is not None or parts.port is not None or parts.query or parts.fragment:
            raise SideloadRefused("git_url_refused", "GitHub URL must not carry credentials, ports, query, or fragments", 422)
        segs = [s for s in parts.path.split("/") if s]
        if len(segs) != 2:
            raise SideloadRefused("git_url_refused", "GitHub URL path must be /owner/repo", 422)
        owner, repo = segs
    else:
        matched = _GH_SHORTHAND.match(text)
        if matched is None:
            raise SideloadRefused("git_url_refused", "only owner/repo[@ref] or https://github.com/owner/repo is allowed", 422)
        owner = matched.group("owner")
        repo = matched.group("repo")
        embedded_ref = matched.group("ref")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _GH_OWNER.match(owner) or not _GH_REPO.match(repo) or repo in (".", ".."):
        raise SideloadRefused("git_url_refused", "invalid GitHub owner or repository name", 422)
    checked_embedded = check_ref(embedded_ref) if embedded_ref is not None else None
    checked_explicit = check_ref(ref)
    if checked_embedded is not None and checked_explicit is not None and checked_embedded != checked_explicit:
        raise SideloadRefused("ref_invalid", "embedded @ref and explicit ref must match", 422)
    final_ref = checked_explicit if checked_explicit is not None else checked_embedded
    canonical_url = f"https://github.com/{owner}/{repo}.git"
    check_url(canonical_url)
    return owner, repo, canonical_url, final_ref


def github_owner_repo(url: object) -> Optional[Tuple[str, str]]:
    if not isinstance(url, str) or not url:
        return None
    try:
        owner, repo, _canon, _ref = parse_github_source(url)
        return owner, repo
    except SideloadRefused:
        return None


def redacted(url: str) -> str:
    if "://" in url:
        parts = urlsplit(url)
        host = parts.hostname or ""
        netloc = f"{host}:{parts.port}" if parts.port else host
        return parts._replace(netloc=netloc).geturl()
    found = _SCP.match(url)
    return f"{found.group('host')}:{found.group('path')}" if found else "(unparsed url)"


def check_ref(ref: object) -> Optional[str]:
    if ref is None or ref == "":
        return None
    if (not isinstance(ref, str) or not _REF.match(ref) or ".." in ref or "@{" in ref or "//" in ref
            or ref.endswith((".lock", "/", "."))):
        raise SideloadRefused("ref_invalid", "the ref is a branch, tag or commit name (letters, digits, . _ / + -, no leading -)", 422)
    return ref


def check_subdir(subdir: object) -> Tuple[str, ...]:
    if subdir is None or subdir == "":
        return ()
    if (
        not isinstance(subdir, str)
        or len(subdir) > MAX_SUBDIR_CHARS
        or subdir.startswith(("/", "-"))
        or "\\" in subdir
        or any(ord(c) < 32 or ord(c) == 127 for c in subdir)
    ):
        raise SideloadRefused("subdir_invalid", "the subfolder is a relative path inside the repository", 422)
    parts = tuple(p for p in PurePosixPath(subdir).parts if p != ".")
    if any(p == ".." or p.lower() == ".git" for p in parts) or (parts and parts[0].startswith("-")):
        raise SideloadRefused("subdir_invalid", "the subfolder must stay inside the repository", 422)
    return parts


def checkouts_root(state_dir: Path) -> Path:
    return Path(state_dir) / "cplugs" / CHECKOUTS_DIR


def checkout_of(state_dir: Path, name: str) -> Path:
    return checkouts_root(state_dir) / name


def source_in(checkout: Path, parts: Tuple[str, ...]) -> Path:
    path = checkout
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise SideloadRefused("subdir_invalid", "the subfolder goes through a link", 422)
    if not path.resolve().is_relative_to(checkout.resolve()):
        raise SideloadRefused("subdir_invalid", "the subfolder must stay inside the repository", 422)
    return path


def _env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", SSH_ASKPASS_REQUIRE="never", GCM_INTERACTIVE="never")
    return env


def _config() -> List[str]:
    out = ["-c", "protocol.allow=never"]
    for proto in ALLOWED_PROTOCOLS:
        out += ["-c", f"protocol.{proto}.allow=always"]
    return out + ["-c", "core.hooksPath=/dev/null", "-c", "submodule.recurse=false", "-c", "transfer.fsckObjects=true",
                  "-c", "core.fsmonitor=false", "-c", "advice.detachedHead=false"]


def _git(args: List[str], cwd: Optional[Path] = None) -> str:
    try:
        done = subprocess.run(["git", *_config(), *args], cwd=cwd, env=_env(), stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=GIT_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        logger.warning("cplug_sideload_git_timeout", step=args[0], timeout_s=GIT_TIMEOUT_SECONDS)
        raise SideloadRefused("git_timeout", f"git {args[0]} took longer than {GIT_TIMEOUT_SECONDS} seconds", 504) from exc
    except OSError as exc:
        logger.warning("cplug_sideload_git_unavailable", error_type=type(exc).__name__)
        raise SideloadRefused("git_unavailable", "git could not be run on this computer", 503) from exc
    if done.returncode != 0:
        tail = _USERINFO.sub("", done.stderr or "").strip()[-MAX_ERROR_CHARS:]
        logger.warning("cplug_sideload_git_failed", step=args[0], returncode=done.returncode)
        raise SideloadRefused("git_failed", f"git {args[0]} failed: {tail}", 502)
    return done.stdout


def fetch(checkout: Path, url: str, ref: Optional[str]) -> str:
    with _lock:
        if not (checkout / ".git").is_dir():
            checkout.mkdir(parents=True, exist_ok=True)
            _git(["init", "-q", str(checkout)])
            _git(["remote", "add", "origin", url], cwd=checkout)
        else:
            _git(["remote", "set-url", "origin", url], cwd=checkout)
        target = "FETCH_HEAD"
        try:
            _git(["fetch", "-q", "--depth", "1", "--no-tags", "--no-recurse-submodules", "origin", ref or "HEAD"], cwd=checkout)
        except SideloadRefused as exc:
            if exc.code != "git_failed" or ref is None or not _HEX.match(ref):
                raise
            unshallow = ["--unshallow"] if (checkout / ".git" / "shallow").exists() else []
            _git(["fetch", "-q", "--no-tags", "--no-recurse-submodules", *unshallow, "origin"], cwd=checkout)
            target = ref
        _git(["checkout", "-q", "--force", "--detach", target, "--"], cwd=checkout)
        _git(["clean", "-q", "-ffdx"], cwd=checkout)
        return _git(["rev-parse", "HEAD"], cwd=checkout).strip()


def incoming(state_dir: Path) -> Path:
    return checkouts_root(state_dir) / f".incoming-{os.getpid()}-{time.monotonic_ns()}"


def adopt(state_dir: Path, staged: Path, name: str) -> Path:
    dest = checkout_of(state_dir, name)
    with _lock:
        old = checkouts_root(state_dir) / f".old-{name}-{os.getpid()}"
        if dest.exists():
            os.replace(dest, old)
        os.replace(staged, dest)
        shutil.rmtree(old, ignore_errors=True)
    return dest


def _record_path(state_dir: Path) -> Path:
    return Path(state_dir) / "cplugs" / RECORD_FILE


def _with_owner_repo(entry: Dict[str, Any]) -> Dict[str, Any]:
    if "owner" in entry and "repo" in entry:
        return entry
    gh = github_owner_repo(entry.get("url"))
    if gh is None:
        return entry
    return {**entry, "owner": gh[0], "repo": gh[1]}


def records(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(_record_path(state_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("cplug_sideload_git_record_unreadable", error_type=type(exc).__name__)
        return {}
    return {k: _with_owner_repo(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _records_for_update(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    try:
        data = read_for_update(_record_path(state_dir), log_event="cplug_sideload_git_record_unreadable")
    except UnreadableArtifact as exc:
        raise SideloadRefused("sideload_unreadable", f"the git sideload record is unreadable and was left as it is: {exc}", 500) from exc
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def record(state_dir: Path, name: str, url: str, ref: Optional[str], subdir: Tuple[str, ...], commit: str) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"url": url, "ref": ref, "subdir": "/".join(subdir), "commit": commit, "synced_at": sideload.wall()}
    gh = github_owner_repo(url)
    if gh is not None:
        entry["owner"], entry["repo"] = gh
    with _lock:
        data = _records_for_update(state_dir)
        data[name] = entry
        if not atomic_write_json(_record_path(state_dir), data, log_event="cplug_sideload_git_record_write_failed"):
            raise SideloadRefused("sideload_not_saved", "the git sideload record could not be written", 500)
    return entry


def describe(state_dir: Path, name: str, source: str) -> Optional[Dict[str, Any]]:
    entry = records(state_dir).get(name)
    if entry is None:
        return None
    try:
        expected = source_in(checkout_of(state_dir, name), check_subdir(entry.get("subdir")))
    except SideloadRefused:
        return None
    return entry if source == str(expected) else None


def forget(state_dir: Path, name: str) -> None:
    with _lock:
        data = _records_for_update(state_dir)
        if data.pop(name, None) is not None and not atomic_write_json(_record_path(state_dir), data,
                                                                      log_event="cplug_sideload_git_record_write_failed"):
            raise SideloadRefused("sideload_not_saved", "the git sideload record could not be written", 500)
        shutil.rmtree(checkout_of(state_dir, name), ignore_errors=True)


def restore_record(state_dir: Path, name: str, entry: Dict[str, Any]) -> None:
    with _lock:
        data = _records_for_update(state_dir)
        data[name] = dict(entry)
        if not atomic_write_json(_record_path(state_dir), data, log_event="cplug_sideload_git_record_write_failed"):
            raise SideloadRefused("sideload_not_saved", "the git sideload record could not be written", 500)
