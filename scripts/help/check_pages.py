#!/usr/bin/env python3
"""Check the ``help/`` pages against the repo they describe.

Findings (exit 1):
  * a page lists a feature id with no ``features/catalog/<id>.json``;
  * a page lists a ``sources`` path that does not exist;
  * a page's ``verified_at`` is not a commit, or a source changed after it
    (``git log <verified_at>..HEAD -- <sources>`` is not empty).
Reported but not failing: catalog features no page covers (the catalog is far
larger than the help tree, so this is a coverage list, not a defect; pass
``--strict-coverage`` to fail on it).

Exit: 0 clean, 1 findings, 2 could not check (no help/ pages, no catalog, git
unusable, a malformed page). A check that could not look never reads as a pass.

Usage: python3 scripts/help/check_pages.py [--strict-coverage] [--repo DIR]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.help.pages import HELP_DIR_NAME, Page, PageError, load_pages  # noqa: E402

CATALOG_DIR = Path("features") / "catalog"
GIT_TIMEOUT_SECONDS = 60


class CheckError(RuntimeError):
    """The check could not look at something it needs (exit 2)."""


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckError(f"git unusable: {exc}") from exc


def catalog_ids(repo: Path) -> set[str]:
    ids = {p.stem for p in (repo / CATALOG_DIR).glob("*.json")}
    if not ids:
        raise CheckError(f"no catalog entries under {CATALOG_DIR}")
    return ids


def stale_sources(repo: Path, page: Page) -> list[str]:
    sha = str(page.meta["verified_at"])
    if git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        raise CheckError(f"{repo} is not a git work tree")
    known = git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    if known.returncode != 0:
        return ["<verified_at not a commit>"]
    changed = []
    for src in page.sources:
        if not (repo / src).exists():
            continue
        log = git(repo, "log", "--format=%h", f"{sha}..HEAD", "--", src)
        if log.returncode != 0:
            raise CheckError(f"git log failed for {src}: {log.stderr.strip()}")
        if log.stdout.strip():
            changed.append(src)
    return changed


def run_checks(repo: Path) -> tuple[list[str], list[str]]:
    if not (repo / HELP_DIR_NAME).is_dir():
        raise CheckError(f"no {HELP_DIR_NAME}/ folder under {repo}")
    pages = load_pages(repo)
    if not pages:
        raise CheckError("no help pages found")
    ids = catalog_ids(repo)
    findings: list[str] = []
    covered: set[str] = set()
    for page in pages:
        covered.update(page.features)
        for fid in page.features:
            if fid not in ids:
                findings.append(f"{page.rel}: feature id '{fid}' has no features/catalog/{fid}.json")
        for src in page.sources:
            if not (repo / src).exists():
                findings.append(f"{page.rel}: source '{src}' does not exist")
        for src in stale_sources(repo, page):
            findings.append(
                f"{page.rel}: source '{src}' changed since verified_at {page.meta['verified_at']}")
    return findings, sorted(ids - covered)


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Returns 0 clean, 1 findings, 2 could not check."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict-coverage", action="store_true",
                    help="also fail when a catalog feature has no page")
    ap.add_argument("--repo", type=Path, default=REPO_ROOT, help="repo root (tests)")
    args = ap.parse_args(argv)
    try:
        findings, uncovered = run_checks(args.repo)
    except (CheckError, PageError, OSError) as exc:
        print(f"check_pages: could not check: {exc}", file=sys.stderr)
        return 2
    for line in findings:
        print(f"finding: {line}")
    print(f"coverage: {len(uncovered)} catalog features have no help page"
          + (" (listed below)" if args.strict_coverage else " (use --strict-coverage to list/fail)"))
    if args.strict_coverage:
        findings += [f"feature '{f}' has no help page" for f in uncovered]
        for f in uncovered:
            print(f"finding: feature '{f}' has no help page")
    print(f"check_pages: {'FINDINGS' if findings else 'clean'} ({len(findings)})")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
