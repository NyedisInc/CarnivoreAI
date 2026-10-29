
from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

OFFLINE_HELP = "list and attach sessions straight from tmux, without the server (automatic when it does not answer)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="carnivore",
        description="carnivore terminal client. talks to the carnivore server on this computer.",
    )
    parser.add_argument("--offline", action="store_true", help=OFFLINE_HELP)
    sub = parser.add_subparsers(dest="command", metavar="command")
    tui = sub.add_parser("tui", help="open the terminal interface (the default)")
    tui.add_argument("--offline", action="store_true", default=argparse.SUPPRESS, help=OFFLINE_HELP)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    from src.config import settings
    from src.tui.api_client import server_base_url
    from src.tui.offline.launch import run_offline, server_answers
    from src.tui.strings import t

    if args.offline:
        return run_offline(settings)
    if not server_answers(server_base_url(settings.port)):
        print(t("tui.offline.auto"), file=sys.stderr)
        return run_offline(settings)

    from src.tui.api_client import ApiClient
    from src.tui.app import CarnivoreTui
    from src.tui.token_store import TokenStore

    client = ApiClient(TokenStore(settings.get_state_dir()), server_base_url(settings.port))
    CarnivoreTui(client).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
