
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional, Tuple

import structlog

from src.core.claude_rename import parse_claude_version
from src.core.launch_profiles.check import scrubbed_env
from src.core.mods.validate_report import parse_report, report_sha
from src.models.catalog_review import ReviewBlock
from src.models.mods import ModReport

logger = structlog.get_logger()

MIN_CLAUDE: Tuple[int, int, int] = (2, 1, 287)

VALIDATE_TIMEOUT = 30

CLAUDE_MISSING = "claude_missing"
CLAUDE_TOO_OLD = "claude_too_old"
VALIDATE_FAILED = "mod_validate_failed"
VALIDATE_UNAVAILABLE = "mod_validate_unavailable"
REVIEW_BLOCKED = "review_blocked"
CONSENT_REQUIRED = "consent_required"
REPORT_CHANGED = "mod_report_changed"


class ModGateRefusal(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def check_version(cli_path: Optional[str], cli_version: Optional[str]) -> str:
    if not cli_path or not cli_version:
        raise ModGateRefusal(CLAUDE_MISSING, "claude code was not found on this computer, and a mod needs it to be checked")
    found = parse_claude_version(cli_version)
    if found is None or found < MIN_CLAUDE:
        raise ModGateRefusal(CLAUDE_TOO_OLD, f"mods need claude code 2.1.287 or newer; this computer has {cli_version.strip()}")
    return cli_version.strip()


def run_validate(cli_path: str, staged_dir: Path, cli_version: str) -> ModReport:
    argv = [cli_path, "plugin", "validate", "--json", "--strict", str(staged_dir)]
    with tempfile.TemporaryDirectory(prefix="carnivore-mod-validate-") as cwd:
        try:
            done = subprocess.run(argv, cwd=cwd, env=scrubbed_env(), stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=VALIDATE_TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("mod_validate_unavailable", error=type(exc).__name__)
            raise ModGateRefusal(VALIDATE_UNAVAILABLE, "claude code's checker could not be run on this mod, so it was not installed")
    try:
        raw: Any = json.loads(done.stdout)
    except ValueError:
        raw = None
    if done.returncode == 1:
        raise ModGateRefusal(VALIDATE_FAILED, "claude code's checker refused this mod: " + _errors(raw))
    if done.returncode != 0 or not isinstance(raw, dict):
        raise ModGateRefusal(VALIDATE_UNAVAILABLE, "claude code's checker gave no usable answer for this mod, so it was not installed")
    return parse_report(raw, cli_version)


def _errors(raw: Any) -> str:
    found: list = []
    if isinstance(raw, dict):
        blocks = [raw.get("manifest"), *(raw.get("contents") if isinstance(raw.get("contents"), list) else [])]
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("errors"), list):
                found += [e if isinstance(e, str) else json.dumps(e) for e in block["errors"]]
    return "; ".join(found)[:500] or "it reported a failure with no detail"


def needs_flagged_ack(review: Optional[ReviewBlock]) -> bool:
    return review is None or review.status != "reviewed" or review.verdict != "clean"


def check_review(review: Optional[ReviewBlock]) -> None:
    if review is not None and review.verdict == "blocked":
        raise ModGateRefusal(REVIEW_BLOCKED, "the security review blocked this mod, and a block is never overridden for mods")


def evaluate(cli_path: Optional[str], cli_version: Optional[str], staged_dir: Path,
             review: Optional[ReviewBlock]) -> Tuple[ModReport, str, bool]:
    version = check_version(cli_path, cli_version)
    check_review(review)
    report = run_validate(str(cli_path), staged_dir, version)
    return report, report_sha(report), needs_flagged_ack(review)


def check_consent(consent: Any, *, sha: str, flagged_ack_needed: bool) -> None:
    if consent is None or not getattr(consent, "mod_trust", False):
        raise ModGateRefusal(CONSENT_REQUIRED, "installing a mod needs the trust tick on the consent sheet")
    if flagged_ack_needed and not getattr(consent, "mod_flagged_ack", False):
        raise ModGateRefusal(CONSENT_REQUIRED, "this mod was flagged or has no clean review; it needs the extra tick")
    if getattr(consent, "mod_report_sha", "") != sha:
        raise ModGateRefusal(REPORT_CHANGED, "what this mod hooks and calls changed since the sheet was shown; review it again")
