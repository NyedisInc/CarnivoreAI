
from __future__ import annotations

from typing import Literal

import structlog

from src.core.pack.transport import bundles

logger = structlog.get_logger()

Outcome = Literal["fast_forwarded", "up_to_date", "no_incoming", "busy", "dirty", "diverged"]


def fast_forward(repo: str, sender_install_id: str, *, busy: bool, air_gap: bool = False) -> Outcome:
    branch = bundles.current_branch(repo)
    if not branch:
        return "no_incoming"
    ref = f"refs/carnivore/{sender_install_id}/heads/{branch}"
    incoming = bundles._git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", air_gap=air_gap)
    if incoming.returncode != 0:
        return "no_incoming"
    local = bundles._git(repo, "rev-parse", "--verify", "-q", "HEAD", air_gap=air_gap)
    if local.returncode == 0 and local.stdout.strip() == incoming.stdout.strip():
        return "up_to_date"
    reason = None
    if busy:
        reason = "busy"
    elif bundles._git(repo, "status", "--porcelain", air_gap=air_gap).stdout.strip():
        reason = "dirty"
    elif local.returncode == 0 and bundles._git(repo, "merge-base", "--is-ancestor", "HEAD", ref, air_gap=air_gap).returncode != 0:
        reason = "diverged"
    if reason:
        logger.info("pack_copy_ff_skipped", reason=reason, branch=branch)
        return reason  # type: ignore[return-value]
    done = bundles._git(repo, "merge", "--ff-only", "--quiet", ref, air_gap=air_gap)
    if done.returncode != 0:
        logger.warning("pack_copy_ff_failed", branch=branch, status=done.returncode)
        return "diverged"
    logger.info("pack_copy_ff_done", branch=branch)
    return "fast_forwarded"
