#!/usr/bin/env python3
"""Thin CLI wrapper around src/core/version.py and src/core/update_check.py.

THREE-OUTCOME CONTRACT (see project CLAUDE.md's "three-outcome rule"): every
subcommand exits with one of exactly three codes, and never invents a fourth
meaning by conflating two of them:

Exit code 1 is reserved for command-line usage errors (bad flags), which is
a different category from all three outcomes above.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def _install_src_on_path(install_dir: Path) -> None:
    resolved = str(install_dir.resolve())
    if resolved in sys.path:
        sys.path.remove(resolved)
    sys.path.insert(0, resolved)
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            del sys.modules[name]


def current_version(install_dir: Path) -> str:
    """Resolve the version this install would report right now.

    Description: delegates entirely to ``src.core.version.resolve_version``
      run against ``install_dir`` — no independent version logic here.
    Inputs:
      install_dir (Path): repository root to resolve against.
    Output: str - the resolved version, or "" when it could not be
      determined (the resolver's own documented "give up honestly" case).
    Example: current_version(Path("/opt/cloudecode")) -> "0.8.2"
    """
    _install_src_on_path(install_dir)
    from src.core.version import resolve_version  # noqa: E402

    return resolve_version(install_dir)


def resolve_remote(install_dir: Path, config_path: Optional[Path]) -> str:
    _install_src_on_path(install_dir)
    from src.core.update_check import (  # noqa: E402
        FALLBACK_REMOTE,
        discover_origin_remote,
        read_configured_remote,
    )

    configured = read_configured_remote(config_path) if config_path else ""
    return configured or discover_origin_remote(install_dir) or FALLBACK_REMOTE


def list_release_tags(install_dir: Path, remote: str) -> list[str]:
    _install_src_on_path(install_dir)
    from src.core.update_check import fetch_remote_tags  # noqa: E402

    return fetch_remote_tags(remote)


def _cmd_current(args: argparse.Namespace) -> int:
    version = current_version(Path(args.install_dir))
    if not version:
        print(
            "could not determine the installed version "
            f"(no CLOUDE_APP_VERSION, no VERSION file, no exact git tag, "
            f"no macOS/package.json, no git describe) in {args.install_dir}",
            file=sys.stderr,
        )
        return 3
    print(version)
    return 0


def _cmd_remote(args: argparse.Namespace) -> int:
    config_path = Path(args.config) if args.config else None
    print(resolve_remote(Path(args.install_dir), config_path))
    return 0


def _cmd_tags(args: argparse.Namespace) -> int:
    """Description: print every release tag on the remote, one per line.

    Inputs: args (argparse.Namespace) with ``install_dir`` and ``remote``.
    Output: int - 0 with tags on stdout (possibly zero lines, meaning FAIL
      "no tags published" is left for the caller to interpret), 3 with a
      reason on stderr when the remote could not be reached at all.
    """
    try:
        tags = list_release_tags(Path(args.install_dir), args.remote)
    except Exception as exc:
        print(f"could not list release tags from {args.remote}: {exc}", file=sys.stderr)
        return 3
    for tag in tags:
        print(tag)
    return 0


def _cmd_latest(args: argparse.Namespace) -> int:
    """Description: print the newest release tag on the remote.

    Inputs: args (argparse.Namespace) with ``install_dir`` and ``remote``.
    Output: int - 0 with the tag on stdout, 2 if the remote answered but
      published no release tags, 3 if the remote could not be reached.
    """
    try:
        tags = list_release_tags(Path(args.install_dir), args.remote)
    except Exception as exc:
        print(f"could not list release tags from {args.remote}: {exc}", file=sys.stderr)
        return 3
    if not tags:
        print(f"{args.remote} published no release tags", file=sys.stderr)
        return 2
    print(tags[-1])
    return 0


def _cmd_check_tag(args: argparse.Namespace) -> int:
    """Description: verify one exact tag exists among the remote's release tags.

    Inputs: args (argparse.Namespace) with ``install_dir``, ``remote``,
      ``tag``.
    Output: int - 0 if the tag exists, 2 if the remote answered but the tag
      is not in the list, 3 if the remote could not be reached.
    """
    try:
        tags = list_release_tags(Path(args.install_dir), args.remote)
    except Exception as exc:
        print(f"could not list release tags from {args.remote}: {exc}", file=sys.stderr)
        return 3
    if args.tag not in tags:
        print(
            f"{args.tag} is not a published release tag on {args.remote}. "
            f"Known tags: {', '.join(tags) if tags else '(none)'}",
            file=sys.stderr,
        )
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_current = sub.add_parser("current", help="print the resolved installed version")
    p_current.add_argument("--install-dir", required=True)
    p_current.set_defaults(func=_cmd_current)

    p_remote = sub.add_parser("remote", help="print the git remote used for release tags")
    p_remote.add_argument("--install-dir", required=True)
    p_remote.add_argument("--config", default=None, help="path to config.json, optional")
    p_remote.set_defaults(func=_cmd_remote)

    p_tags = sub.add_parser("tags", help="list every release tag on the remote")
    p_tags.add_argument("--install-dir", required=True)
    p_tags.add_argument("--remote", required=True)
    p_tags.set_defaults(func=_cmd_tags)

    p_latest = sub.add_parser("latest", help="print the newest release tag on the remote")
    p_latest.add_argument("--install-dir", required=True)
    p_latest.add_argument("--remote", required=True)
    p_latest.set_defaults(func=_cmd_latest)

    p_check = sub.add_parser("check-tag", help="verify a tag is a published release tag")
    p_check.add_argument("--install-dir", required=True)
    p_check.add_argument("--remote", required=True)
    p_check.add_argument("tag")
    p_check.set_defaults(func=_cmd_check_tag)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
