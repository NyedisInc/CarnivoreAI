
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_GITHUB_SLUG_RE = re.compile(r"github\.com[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", re.IGNORECASE)


TRUNK_REPO_NAME = "CarnivoreAIDev"
_TRUNK_NAME_RE = re.compile(
    r"github\.com[:/][^/:]+/" + re.escape(TRUNK_REPO_NAME) + r"(?:\.git)?/?$", re.IGNORECASE
)


class TrunkRemoteError(Exception):
    pass


def _remote_names(repo: Path) -> list[str]:
    done = subprocess.run(
        ["git", "remote"], cwd=repo, capture_output=True, text=True
    )
    if done.returncode != 0:
        raise TrunkRemoteError(
            f"trunk-remote: not a git checkout ({repo}): "
            f"{done.stderr.strip()}"
        )
    return [line for line in done.stdout.splitlines() if line.strip()]


def _remote_url(repo: Path, name: str) -> str | None:
    done = subprocess.run(
        ["git", "remote", "get-url", name], cwd=repo, capture_output=True, text=True
    )
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def _origin_slug(repo: Path) -> str | None:
    url = _remote_url(repo, "origin")
    match = _GITHUB_SLUG_RE.search(url) if url else None
    return match.group(1) if match else None


def _url_matches_trunk(url: str, slug: str) -> bool:
    norm = url[:-4] if url.lower().endswith(".git") else url
    norm = norm.rstrip("/")
    norm_lower = norm.lower()
    slug_lower = slug.lower()
    return norm_lower.endswith(f"github.com:{slug_lower}") or norm_lower.endswith(
        f"github.com/{slug_lower}"
    )


def trunk_remote_name(
    repo: Path,
    *,
    override: str | None = None,
    slug: str | None = None,
) -> str:
    resolved_override = override if override is not None else os.environ.get(
        "CLOUDE_TRUNK_REMOTE"
    )
    resolved_slug = slug or os.environ.get("CLOUDE_TRUNK_REPO")

    if resolved_override:
        if _remote_url(repo, resolved_override) is None:
            raise TrunkRemoteError(
                f"trunk-remote: CLOUDE_TRUNK_REMOTE={resolved_override} names no "
                f"remote configured in this checkout (see: git remote -v)"
            )
        return resolved_override

    names = _remote_names(repo)
    if not names:
        raise TrunkRemoteError("trunk-remote: no remotes configured in this checkout")

    matched: list[str] = []
    if not resolved_slug:
        for name in names:
            url = _remote_url(repo, name)
            if url and _TRUNK_NAME_RE.search(url):
                matched.append(name)
        if not matched:
            resolved_slug = _origin_slug(repo)
            if not resolved_slug:
                raise TrunkRemoteError(
                    f"trunk-remote: no remote's fetch URL names {TRUNK_REPO_NAME} and origin "
                    f"is not a github.com remote (checked: {', '.join(names)}). Set "
                    "CLOUDE_TRUNK_REPO=owner/repo or override with CLOUDE_TRUNK_REMOTE=<name>"
                )
    if resolved_slug:
        for name in names:
            url = _remote_url(repo, name)
            if url and _url_matches_trunk(url, resolved_slug):
                matched.append(name)

    if not matched:
        raise TrunkRemoteError(
            f"trunk-remote: no configured remote's fetch URL matches "
            f"{resolved_slug} (checked: {', '.join(names)}). Add the remote, "
            f"or override with CLOUDE_TRUNK_REMOTE=<name>"
        )

    if "origin" in matched:
        return "origin"
    return matched[0]
