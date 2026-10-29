#!/usr/bin/env python3
"""
Release-time scraper for Claude Code's official slash command list.

Fetches https://code.claude.com/docs/en/commands (via its markdown mirror,
`<url>.md`, which is the server-rendered doc source with none of the SPA
chrome to strip) and parses the single authoritative table under the
"## All commands" heading into a structured, "databaseable" JSON file:
src/data/slash-commands.json.

Usage:
    python3 scripts/scrape-slash-commands.py [--out PATH] [--url URL]

Exit codes:
    0 - success, file written
    1 - fetch or parse failure (file NOT written / NOT touched)

Robustness contract (do not weaken):
    If the page structure changes such that the table can't be found, or
    the parsed row count looks implausible, this script FAILS LOUDLY and
    does NOT write a partial or empty file. A missing update is recoverable
    (the shipped list is simply stale); a silently truncated list that
    LOOKS current is not.

Note: https://code.claude.com/docs/llms.txt is a machine-readable index of
every doc page. It isn't needed for this single-page scrape (the commands
page's own `.md` mirror is already clean markdown), but it's the right
starting point if a future version of this script needs to discover or
validate OTHER doc pages (e.g. to cross-check /docs/en/skills for the
bundled-skills list independently of the marker text on this page).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

DEFAULT_SOURCE_URL = "https://code.claude.com/docs/en/commands.md"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "src" / "data" / "slash-commands.json"

MIN_PLAUSIBLE_COMMAND_COUNT = 40

TABLE_SECTION_HEADING = "## All commands"
NEXT_SECTION_RX = re.compile(r"^##\s+")

MD_LINK_RX = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MD_BOLD_RX = re.compile(r"\*\*([^*]+)\*\*")
MD_CODE_RX = re.compile(r"`([^`]*)`")

LEADING_MARKER_RX = re.compile(r"^\s*\*\*\[(?:Skill|Workflow)\]\([^)]*\)\.\*\*\s*")

ALIAS_RX = re.compile(r"Alias (?:for|of)\s+\[?`?(/[a-zA-Z0-9-]+)`?\]?", re.IGNORECASE)

COMMAND_CELL_RX = re.compile(r"^`(/[a-zA-Z0-9-]+)((?:\s+.*)?)`$")


class ParsedCommand(NamedTuple):
    command: str
    args: str
    description: str
    type: str
    alias_of: str | None


def fetch_source(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "CloudeCode-slash-command-scraper/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        fail(f"failed to fetch {url}: {exc}")


def extract_table_lines(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == TABLE_SECTION_HEADING)
    except StopIteration:
        fail(
            f'could not find the "{TABLE_SECTION_HEADING}" heading in the fetched page. '
            "The doc structure has likely changed - update TABLE_SECTION_HEADING or the "
            "parsing logic in this script before re-running."
        )

    section_lines = []
    for line in lines[start + 1 :]:
        if NEXT_SECTION_RX.match(line):
            break
        section_lines.append(line)

    table_rows = [l for l in section_lines if l.strip().startswith("|")]
    if len(table_rows) < 2:
        fail(
            f'found the "{TABLE_SECTION_HEADING}" heading but no markdown table under it. '
            "The doc structure has likely changed."
        )

    header = table_rows[0]
    if "Command" not in header or "Purpose" not in header:
        fail(
            f"table header under \"{TABLE_SECTION_HEADING}\" no longer reads "
            f'"Command | Purpose" (got: {header!r}). Column layout has changed - '
            "update the parser before trusting its output."
        )

    return table_rows[2:]


def split_table_row(row: str) -> list[str]:
    raw_cells = re.split(r"(?<!\\)\|", row.strip())
    cells = [c.strip().replace("\\|", "|") for c in raw_cells]
    return [c for i, c in enumerate(cells) if not (i in (0, len(cells) - 1) and c == "")]


def strip_markdown(text: str) -> str:
    text = MD_LINK_RX.sub(r"\1", text)
    text = MD_BOLD_RX.sub(r"\1", text)
    text = MD_CODE_RX.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_command_cell(raw_cell: str) -> tuple[str, str]:
    match = COMMAND_CELL_RX.match(raw_cell.strip())
    if not match:
        fail(f"command cell did not match the expected `/name [args]` pattern: {raw_cell!r}")
    command, args = match.group(1), match.group(2).strip()
    return command, args


def parse_purpose_cell(raw_cell: str) -> tuple[str, str, str | None]:
    if raw_cell.startswith("**[Skill]"):
        cmd_type = "skill"
    elif raw_cell.startswith("**[Workflow]"):
        cmd_type = "workflow"
    else:
        cmd_type = "builtin"

    alias_match = ALIAS_RX.search(raw_cell)
    alias_of = alias_match.group(1) if alias_match else None

    body = LEADING_MARKER_RX.sub("", raw_cell)
    description = strip_markdown(body)
    return description, cmd_type, alias_of


def parse_rows(table_rows: list[str]) -> list[ParsedCommand]:
    parsed: list[ParsedCommand] = []
    for row in table_rows:
        cells = split_table_row(row)
        if len(cells) != 2:
            fail(f"expected exactly 2 cells (Command, Purpose) but got {len(cells)} in row: {row!r}")
        command, args = parse_command_cell(cells[0])
        description, cmd_type, alias_of = parse_purpose_cell(cells[1])
        parsed.append(ParsedCommand(command, args, description, cmd_type, alias_of))
    return parsed


def build_document(commands: list[ParsedCommand], source_url: str) -> dict:
    return {
        "source_url": source_url,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command_count": len(commands),
        "commands": [
            {
                "command": c.command,
                "args": c.args,
                "description": c.description,
                "type": c.type,
                "alias_of": c.alias_of,
            }
            for c in commands
        ],
    }


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_SOURCE_URL, help="doc page markdown URL to scrape")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="output JSON path")
    args = parser.parse_args()

    markdown = fetch_source(args.url)
    table_rows = extract_table_lines(markdown)
    commands = parse_rows(table_rows)

    if len(commands) < MIN_PLAUSIBLE_COMMAND_COUNT:
        fail(
            f"parsed only {len(commands)} commands, fewer than the plausibility floor "
            f"of {MIN_PLAUSIBLE_COMMAND_COUNT}. Refusing to overwrite {args.out} with what "
            "is likely a partial parse caused by a doc structure change."
        )

    seen = set()
    duplicates = set()
    for c in commands:
        if c.command in seen:
            duplicates.add(c.command)
        seen.add(c.command)
    if duplicates:
        fail(f"parsed duplicate command entries, refusing to write: {sorted(duplicates)}")

    document = build_document(commands, args.url)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(commands)} commands to {args.out}")


if __name__ == "__main__":
    main()
