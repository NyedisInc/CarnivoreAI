
from __future__ import annotations

import shlex
from typing import Dict

FALLBACK_SHELL = '"${SHELL:-/bin/sh}" -i'


def missing_tool_message(binary: str, family: str) -> str:
    return "\n".join([
        f"carnivore: {binary} is not installed, or is not on the PATH of this pane.",
        f"fix any one of: install {binary}; or edit the {family} wrapper on the"
        " wrappers page.",
        "dropping you into a shell so this message stays readable.",
    ])


def guarded_launch_script(binary: str, invocation: str, family: str) -> str:
    lines = missing_tool_message(binary, family).split("\n")
    quoted = " ".join(shlex.quote(line) for line in lines)
    return (
        f"if command -v {shlex.quote(binary)} >/dev/null 2>&1; then "
        f'exec {invocation} "$@"; '
        f"else printf '%s\\n' {quoted} >&2; exec {FALLBACK_SHELL}; fi"
    )


def example_wrapper(family: str, binary: str, invocation: str, label: str) -> Dict[str, object]:
    return {
        "id": f"{family}-guarded",
        "family": family,
        "label": label,
        "script": guarded_launch_script(binary, invocation, family),
        "entry": None,
        "description": (
            f"example - runs {binary} when it is on PATH, and when it is not, "
            "prints what is wrong and leaves you in a shell instead of an "
            "empty pane that exits on its own."
        ),
        "default": False,
        "accepts_model": False,
    }
