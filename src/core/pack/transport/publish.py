
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.message_model_secrets import scan_text
from src.core.pack.transport import github_account, ladder

logger = structlog.get_logger()

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
MAX_SCAN_BYTES = 1024 * 1024
DEFAULT_GITIGNORE = "node_modules/\n.venv/\nvenv/\n__pycache__/\n.DS_Store\n.env\n.env.*\n"


class PublishRefused(Exception):

    def __init__(self, code: str, detail: str, files: Optional[List[str]] = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.files = code, detail, files or []


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


def scan_for_secrets(root: str) -> List[str]:
    done = _git(root, "ls-files", "-co", "--exclude-standard", "-z")
    if done.returncode != 0:
        raise PublishRefused("scan_failed", "the files could not be listed to scan them; nothing was published")
    flagged: List[str] = []
    for rel in filter(None, done.stdout.decode("utf-8", "replace").split("\0")):
        path = Path(root) / rel
        try:
            if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_SCAN_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            raise PublishRefused("scan_failed", "a file could not be read to scan it; nothing was published") from None
        if b"\0" in raw:
            continue
        if scan_text(raw.decode("utf-8", "replace")):
            flagged.append(rel)
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
