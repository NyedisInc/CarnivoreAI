"""The Task Manager guide in pieces: the core sections, one section by number or name, and the one-line index of the rest (#1757).

**ONE FILE, NO SECOND COPY.** The rules live in the bundled skill (``guide_rev.GUIDE_PATH``). A section whose heading is
followed by the line :data:`CORE_MARKER` (an HTML comment, invisible to a skill reader) is CORE: what every writer needs.
``task_manager_guide`` answers the core plus an index of the rest by default, ONE section for ``topic``, and the whole file for
``detail: true``. Moving a section in or out of the core is moving one marker line in that file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

CORE_MARKER = "<!-- core -->"

_HEADING = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
_TRAILING_NOTE = re.compile(r"\s*\([^)]*\)\s*$")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n+", re.DOTALL)


class GuideTopicError(ValueError):
    pass


@dataclass(frozen=True)
class Section:

    number: int
    title: str
    text: str
    core: bool


def parse(guide: str) -> Tuple[str, List[Section]]:
    marks = list(_HEADING.finditer(guide))
    preamble = guide[:marks[0].start()] if marks else guide
    sections = []
    for at, mark in enumerate(marks):
        end = marks[at + 1].start() if at + 1 < len(marks) else len(guide)
        chunk = guide[mark.start():end].rstrip("\n") + "\n"
        core = f"\n{CORE_MARKER}\n" in chunk
        sections.append(Section(int(mark.group(1)), mark.group(2).strip(), chunk.replace(f"{CORE_MARKER}\n", "", 1), core))
    return preamble, sections


def index_line(sections: List[Section]) -> str:
    rest = [f"{s.number} {_TRAILING_NOTE.sub('', s.title)}" for s in sections if not s.core]
    if not rest:
        return ""
    return "Not shown here (task_manager_guide topic: <number or name> returns one, detail: true returns all): " + "; ".join(rest) + "."


def core_text(guide: str) -> str:
    preamble, sections = parse(guide)
    parts = [_FRONT_MATTER.sub("", preamble).rstrip("\n") + "\n"] + [s.text for s in sections if s.core]
    index = index_line(sections)
    return "\n".join(parts) + ("\n" + index + "\n" if index else "")


def find(sections: List[Section], topic: object) -> Section:
    if isinstance(topic, bool) or not isinstance(topic, (int, str)) or str(topic).strip() == "":
        raise GuideTopicError("topic must be a section number or part of a section name")
    word = str(topic).strip().lstrip("#").removeprefix("section ").strip().lower()
    if word.isdigit():
        for section in sections:
            if section.number == int(word):
                return section
        raise GuideTopicError(f"no section {word}; sections run {sections[0].number} to {sections[-1].number}")
    hits = [s for s in sections if word in s.title.lower()]
    if len(hits) == 1:
        return hits[0]
    names = ", ".join(f"{s.number} {_TRAILING_NOTE.sub('', s.title)}" for s in (hits or sections))
    raise GuideTopicError(f"topic {topic!r} matches {'several sections' if hits else 'no section'}: {names}")
