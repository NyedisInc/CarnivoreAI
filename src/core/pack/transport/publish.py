
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, Tuple

import structlog

from src.core import message_model_secrets as secrets
from src.core.message_model_secrets import scan_text
from src.core.pack.transport import github_account, ladder

logger = structlog.get_logger()

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
MAX_LISTED_FILES = 20
SCAN_CHUNK_BYTES = 1024 * 1024
SCAN_OVERLAP_BYTES = 64 * 1024
MAX_TOTAL_SCAN_BYTES = 256 * 1024 * 1024
BUDGET_DETAIL = "the files total more than the scan limit; nothing was published"
BINARY_PASS_DETECTORS = (
    secrets.DETECTOR_GITHUB_TOKEN, secrets.DETECTOR_AWS_ACCESS_KEY_ID, secrets.DETECTOR_GOOGLE_API_KEY, secrets.DETECTOR_SLACK_TOKEN,
    secrets.DETECTOR_PEM_PRIVATE_KEY, secrets.DETECTOR_ANTHROPIC_API_KEY, secrets.DETECTOR_OPENAI_API_KEY,
    secrets.DETECTOR_CARNIVORE_API_KEY, secrets.DETECTOR_STRIPE_KEY, secrets.DETECTOR_HUGGINGFACE_TOKEN, secrets.DETECTOR_NPM_TOKEN,
    secrets.DETECTOR_GITLAB_TOKEN, secrets.DETECTOR_SENDGRID_KEY, secrets.DETECTOR_SLACK_APP_TOKEN, secrets.DETECTOR_CATALOG_BOT_TOKEN,
    secrets.DETECTOR_JWT,
)
BOUNDARY_KEPT_DETECTORS = frozenset((
    secrets.DETECTOR_STRIPE_KEY, secrets.DETECTOR_OPENAI_API_KEY, secrets.DETECTOR_HUGGINGFACE_TOKEN, secrets.DETECTOR_NPM_TOKEN,
    secrets.DETECTOR_SENDGRID_KEY, secrets.DETECTOR_SLACK_TOKEN, secrets.DETECTOR_SLACK_APP_TOKEN,
))
DEFAULT_GITIGNORE = "node_modules/\n.venv/\nvenv/\n__pycache__/\n.DS_Store\n.env\n.env.*\n"


class PublishRefused(Exception):

    def __init__(self, code: str, detail: str, files: Optional[List[str]] = None, params: Optional[Dict[str, str]] = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.files, self.params = code, detail, files or [], params or {}


def budget_params() -> Dict[str, str]:
    return {"limit": f"{MAX_TOTAL_SCAN_BYTES // (1024 * 1024)} MiB"}


def fill_params(sentence: str, params: Dict[str, str]) -> str:
    for key, value in params.items():
        sentence = sentence.replace("{" + key + "}", value)
    return sentence


def listed_files(files: List[str]) -> Dict[str, Any]:
    return {"files": files[:MAX_LISTED_FILES], "files_more": max(0, len(files) - MAX_LISTED_FILES)}


def repo_name(display_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", display_name.strip()).strip("-.")
    return (slug or "project")[:100]


def card(*, display_name: str, air_gap: bool, has_remote: bool, owner_pointer: Optional[str],
         account: github_account.Resolution) -> Dict[str, Any]:
    out: Dict[str, Any] = {"name": repo_name(display_name), "private": True, "owner": owner_pointer, "account": account.account,
                           "account_source": account.source, "asks": [], "offered": True, "reason": None}
    if air_gap:
        return {**out, "offered": False, "reason": "air_gap", "owner": None, "account": None}
    if has_remote:
        return {**out, "offered": False, "reason": "has_remote"}
    if not github_account.valid_account(owner_pointer):
        out["asks"].append("owner")
    if account.account is None:
        out["asks"].append("account")
    return out


def _git(root: str, *args: str, env: Optional[Dict[str, str]] = None):
    return ladder.run(["git", "-C", root, *args], air_gap=False, env=env, timeout=300.0)


class ScanBudgetExceeded(Exception):
    pass


def _windows(handle: BinaryIO, remaining: Optional[List[int]], limit: Optional[int] = None) -> Iterator[Tuple[bytes, bytes]]:
    tail, consumed = b"", 0
    while limit is None or consumed < limit:
        chunk = handle.read(SCAN_CHUNK_BYTES if limit is None else min(SCAN_CHUNK_BYTES, limit - consumed))
        if not chunk:
            return
        consumed += len(chunk)
        if remaining is not None:
            remaining[0] -= len(chunk)
            if remaining[0] < 0:
                raise ScanBudgetExceeded()
        window = tail + chunk
        yield window, chunk
        tail = window[-SCAN_OVERLAP_BYTES:]


def _glued_hit_counts(text: str, offset: int, length: int, detector: str) -> bool:
    if detector not in BOUNDARY_KEPT_DETECTORS:
        return True
    before = text[offset - 1] if offset > 0 else ""
    if not (before.isascii() and before.isalnum()):
        return True
    token = text[offset:offset + length]
    return any(c.isdigit() for c in token) and any(c.islower() for c in token) and any(c.isupper() for c in token)


def _binary_hits(window: bytes) -> bool:
    for index, view in enumerate((window, window[0::2], window[1::2])):
        text = view.decode("utf-8", "replace")
        if any(_glued_hit_counts(text, f.offset, f.length, f.detector) for f in scan_text(text, BINARY_PASS_DETECTORS, trust_vendor_marker=True)):
            return True
        if index and scan_text(text):
            return True
    return False


def _file_holds_secret(path: Path, remaining: List[int]) -> bool:
    binary, consumed = False, 0
    with path.open("rb") as handle:
        for window, chunk in _windows(handle, remaining):
            if scan_text(window.decode("utf-8", "replace")):
                return True
            if not binary and b"\0" in chunk:
                binary = True
                if consumed:
                    with path.open("rb") as again:
                        if any(_binary_hits(earlier) for earlier, _ in _windows(again, None, consumed)):
                            return True
            if binary and _binary_hits(window):
                return True
            consumed += len(chunk)
    return False


def _listed_sizes(root: str, listing: List[str]) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for rel in listing:
        path = Path(root) / rel
        try:
            if path.is_symlink() or not path.is_file():
                continue
            out.append((rel, path.stat().st_size))
        except OSError:
            out.append((rel, 0))
    return out


def scan_for_secrets(root: str) -> List[str]:
    done = _git(root, "ls-files", "-co", "--exclude-standard", "-z")
    if done.returncode != 0:
        raise PublishRefused("scan_failed", "the files could not be listed to scan them; nothing was published")
    sized = _listed_sizes(root, [rel for rel in done.stdout.decode("utf-8", "replace").split("\0") if rel])
    if sum(size for _, size in sized) > MAX_TOTAL_SCAN_BYTES:
        biggest = [rel for rel, _ in sorted(sized, key=lambda entry: entry[1], reverse=True)]
        raise PublishRefused("scan_budget_exceeded", BUDGET_DETAIL, biggest, budget_params())
    flagged: List[str] = []
    unscannable: List[str] = []
    remaining = [MAX_TOTAL_SCAN_BYTES]
    for rel, _size in sized:
        try:
            if _file_holds_secret(Path(root) / rel, remaining):
                flagged.append(rel)
        except ScanBudgetExceeded:
            raise PublishRefused("scan_budget_exceeded", BUDGET_DETAIL, [rel], budget_params()) from None
        except OSError:
            unscannable.append(rel)
    if flagged:
        return flagged
    if unscannable:
        raise PublishRefused("unscannable_files", "files that could not be opened to check for a credential; nothing was published", unscannable)
    return flagged


def publish(root: str, *, name: str, owner: str, account: str, air_gap: bool) -> Dict[str, Any]:
    if air_gap:
        raise PublishRefused("air_gap", "air-gap is on for this project; it never contacts GitHub")
    if not _NAME_RE.match(name):
        raise PublishRefused("bad_name", "that is not a usable repo name")
    if not github_account.valid_account(owner):
        raise PublishRefused("bad_owner", "that is not a GitHub owner name")
    if not github_account.valid_account(account):
        raise PublishRefused("bad_account", "that is not a GitHub account name")
    if not os.path.isdir(root):
        raise PublishRefused("git_failed", "the project folder is not there")
    gh = github_account.gh_path()
    if gh is None:
        raise github_account.AccountError("gh_missing", "gh is not installed on this computer")
    token = github_account.token_env(account)
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        if _git(root, "init", "-b", "main").returncode != 0:
            raise PublishRefused("git_failed", "git init failed")
    gitignore = Path(root) / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(DEFAULT_GITIGNORE, encoding="utf-8")
    flagged = scan_for_secrets(root)
    if flagged:
        raise PublishRefused("secrets_found", "files that look like they hold a credential; nothing was published", flagged)
    if _git(root, "rev-parse", "--verify", "HEAD").returncode != 0:
        who = [] if _git(root, "config", "user.email").stdout.strip() else ["-c", "user.name=Carnivore", "-c", "user.email=carnivore@localhost"]
        if _git(root, "add", "-A").returncode != 0 or ladder.run(
                ["git", "-C", root, *who, "commit", "-m", "first commit", "--no-gpg-sign"], air_gap=False, timeout=300.0).returncode != 0:
            raise PublishRefused("git_failed", "the first commit failed")
    done = ladder.run([gh, "repo", "create", f"{owner}/{name}", "--private", "--source", ".", "--push"], air_gap=False,
                      cwd=root, env=token, timeout=600.0)
    if done.returncode != 0:
        logger.warning("pack_publish_failed", status=done.returncode, stderr_bytes=len(done.stderr))
        raise PublishRefused("gh_failed", "gh could not create the repo")
    logger.info("pack_publish_created", owner=owner, name=name, account=account)
    return {"url": f"https://github.com/{owner}/{name}", "owner": owner, "name": name, "private": True}
