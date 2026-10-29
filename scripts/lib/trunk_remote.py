
from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_TRUNK_REPO = "NyedisInc/CarnivoreAI"


class TrunkRemoteError(Exception):
    """No remote resolves to the trunk, or the checkout could not be read.

    Never caught to fall back to a guessed remote name - a caller that
    cannot resolve the trunk must refuse loudly (CLAUDE.md gotcha 11: a
    check that silently looked at the wrong repo is worse than one that
    stopped).
    """


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
    resolved_slug = slug or os.environ.get("CLOUDE_TRUNK_REPO") or DEFAULT_TRUNK_REPO

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
