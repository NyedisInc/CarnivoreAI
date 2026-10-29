
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import yaml

Level = Literal["required", "recommended"]

GRADE_UNGRADED = "ungraded"

NAME_MAX_CHARS = 64
DESCRIPTION_MAX_CHARS = 1024
COMPATIBILITY_MAX_CHARS = 500
BODY_MAX_LINES = 500

MAX_DETAIL_CHARS = 240

RULE_SOURCES: Dict[str, Tuple[str, str]] = {
    "frontmatter.present": (
        "https://agentskills.io/specification#skill-md-format",
        "The SKILL.md file must contain YAML frontmatter followed by Markdown "
        "content.",
    ),
    "name.present": (
        "https://agentskills.io/specification#frontmatter",
        "name is a required frontmatter field.",
    ),
    "name.shape": (
        "https://agentskills.io/specification#name-field",
        "Must be 1-64 characters, may only contain lowercase alphanumeric "
        "characters and hyphens, must not start or end with a hyphen, and must "
        "not contain consecutive hyphens.",
    ),
    "name.matches-folder": (
        "https://agentskills.io/specification#name-field",
        "Must match the parent directory name.",
    ),
    "description.present": (
        "https://agentskills.io/specification#frontmatter",
        "description is a required frontmatter field and must be non-empty.",
    ),
    "description.length": (
        "https://agentskills.io/specification#description-field",
        "Must be 1-1024 characters.",
    ),
    "description.trigger": (
        "https://agentskills.io/specification#description-field",
        "Should describe both what the skill does and when to use it.",
    ),
    "body.present": (
        "https://agentskills.io/specification#body-content",
        "The Markdown body after the frontmatter contains the skill "
        "instructions.",
    ),
    "body.lines": (
        "https://agentskills.io/specification#progressive-disclosure",
        "Keep your main SKILL.md under 500 lines.",
    ),
    "compatibility.length": (
        "https://agentskills.io/specification#compatibility-field",
        "Must be 1-500 characters if provided.",
    ),
    "metadata.shape": (
        "https://agentskills.io/specification#metadata-field",
        "A map from string keys to string values.",
    ),
    "references.resolve": (
        "https://agentskills.io/specification#file-references",
        "When referencing other files in your skill, use relative paths from "
        "the skill root.",
    ),
    "bundled.referenced": (
        "https://agentskills.io/skill-creation/best-practices"
        "#structure-large-skills-with-progressive-disclosure",
        "The key is telling the agent when to load each file.",
    ),
    "paths.portable": (
        "https://code.claude.com/docs/en/skills",
        "Avoid absolute or machine-specific paths by using these substitution "
        "variables instead.",
    ),
}

RULE_LEVELS: Dict[str, Level] = {
    "frontmatter.present": "required",
    "name.present": "required",
    "name.shape": "required",
    "name.matches-folder": "required",
    "description.present": "required",
    "description.length": "required",
    "body.present": "required",
    "compatibility.length": "required",
    "metadata.shape": "required",
    "description.trigger": "recommended",
    "body.lines": "recommended",
    "references.resolve": "recommended",
    "bundled.referenced": "recommended",
    "paths.portable": "recommended",
}

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

TRIGGER_MARKERS: Tuple[str, ...] = (
    "use when",
    "use this when",
    "use it when",
    "used when",
    "use whenever",
    "used whenever",
    "use for",
    "use this for",
    "use this skill when",
    "trigger when",
    "triggers when",
    "triggered when",
    "trigger on",
    "triggers on",
    "invoke when",
    "invoked when",
    "invoke for",
    "apply when",
    "applies when",
    "activate when",
    "reach for",
    "when the user",
    "when you",
    "whenever the user",
    "whenever you",
)

MACHINE_PATH_RE = re.compile(
    r"(?:/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|/Volumes/[A-Za-z0-9._ -]+/"
    r"|[A-Za-z]:\\Users\\)"
)

FENCE_RE = re.compile(r"^(?P<fence>```|~~~).*?^(?P=fence)", re.M | re.S)

LINK_RE = re.compile(r"\]\(\s*([^)\s]+?)\s*\)")
CODE_PATH_RE = re.compile(r"`((?:scripts|references|assets)/[^`\s]+)`")

_NOT_A_BUNDLED_FILE = ("http://", "https://", "mailto:", "#", "/", "$", "{")

SKILL_FILE = "SKILL.md"

FENCE = "---"


@dataclass(frozen=True)
class GradeNote:

    rule_id: str
    level: Level
    passed: bool
    detail: str


@dataclass(frozen=True)
class Grade:

    grade: str
    notes: Tuple[GradeNote, ...]
    not_graded: Tuple[Tuple[str, str], ...]

    @property
    def required_failed(self) -> int:
        return sum(
            1 for note in self.notes
            if note.level == "required" and not note.passed
        )

    @property
    def recommended_failed(self) -> int:
        return sum(
            1 for note in self.notes
            if note.level == "recommended" and not note.passed
        )

    def to_index(self) -> Dict[str, object]:
        return {
            "grade": self.grade,
            "checked": len(self.notes),
            "failed": [
                {
                    "rule": note.rule_id,
                    "level": note.level,
                    "detail": note.detail[:MAX_DETAIL_CHARS],
                }
                for note in self.notes if not note.passed
            ],
            "not_graded": [rule_id for rule_id, _why in self.not_graded],
        }


def letter_for(required_failed: int, recommended_failed: int) -> str:
    if required_failed >= 2:
        return "F"
    if required_failed == 1:
        return "D"
    if recommended_failed == 0:
        return "A"
    if recommended_failed == 1:
        return "B"
    return "C"


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _within(folder: Path, relpath: str) -> Optional[Path]:
    if os.path.isabs(relpath) or relpath.startswith("\\"):
        return None
    normal = os.path.normpath(relpath.replace("\\", "/"))
    if normal == ".." or normal.startswith("../") or normal.startswith("/"):
        return None
    return folder / normal


def split_skill_md(text: str) -> Optional[Tuple[str, str]]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FENCE:
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FENCE:
            return "".join(lines[1:index]), "".join(lines[index + 1:])
    return None


def read_manifest(folder: Path) -> Dict[str, object]:
    text = _read_text(folder / SKILL_FILE)
    if text is None:
        return {}
    split = split_skill_md(text)
    if split is None:
        return {}
    try:
        block = yaml.safe_load(split[0])
    except yaml.YAMLError:
        return {}
    return block if isinstance(block, dict) else {}


def _optional_text(manifest: Dict[str, object], key: str) -> Optional[str]:
    value = manifest.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bundled_files(folder: Path) -> List[str]:
    found: List[str] = []
    root = str(folder)
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            full = Path(dirpath) / filename
            if full.is_symlink() or not full.is_file():
                continue
            relpath = os.path.relpath(str(full), root).replace(os.sep, "/")
            if relpath != SKILL_FILE:
                found.append(relpath)
    return sorted(found)


def _referenced_paths(body: str) -> List[str]:
    seen: List[str] = []
    for match in list(LINK_RE.finditer(body)) + list(CODE_PATH_RE.finditer(body)):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or target.startswith(_NOT_A_BUNDLED_FILE):
            continue
        if "://" in target or "$" in target:
            continue
        if target not in seen:
            seen.append(target)
    return seen


def _strip_fences(body: str) -> str:
    return FENCE_RE.sub("\n", body)


def _name_rules(
    manifest: Dict[str, object], folder_name: str,
) -> Tuple[List[GradeNote], List[Tuple[str, str]]]:
    name = _optional_text(manifest, "name")
    if name is None:
        return (
            [GradeNote(
                "name.present", "required", False,
                "the front matter declares no name",
            )],
            [
                ("name.shape", "there is no name to check the shape of"),
                ("name.matches-folder", "there is no name to compare with the folder"),
            ],
        )

    notes = [GradeNote("name.present", "required", True, f"name is {name!r}")]
    shaped = bool(NAME_RE.match(name)) and len(name) <= NAME_MAX_CHARS
    notes.append(GradeNote(
        "name.shape", "required", shaped,
        f"name is {len(name)} characters"
        + ("" if shaped else
           ", and must be 1 to 64 lowercase letters, digits and single hyphens, "
           "with no leading, trailing or consecutive hyphen"),
    ))
    matches = name == folder_name
    notes.append(GradeNote(
        "name.matches-folder", "required", matches,
        f"name {name!r} matches the folder" if matches
        else f"name is {name!r} but the folder is {folder_name!r}",
    ))
    return notes, []


def _description_rules(
    manifest: Dict[str, object],
) -> Tuple[List[GradeNote], List[Tuple[str, str]]]:
    description = _optional_text(manifest, "description")
    if description is None:
        return (
            [GradeNote(
                "description.present", "required", False,
                "the front matter declares no description, which is the one "
                "field an agent matches a request against",
            )],
            [
                ("description.length", "there is no description to measure"),
                ("description.trigger", "there is no description to read"),
            ],
        )

    notes = [GradeNote(
        "description.present", "required", True,
        f"description is {len(description)} characters",
    )]
    within = len(description) <= DESCRIPTION_MAX_CHARS
    notes.append(GradeNote(
        "description.length", "required", within,
        f"description is {len(description)} characters"
        + ("" if within else f", over the {DESCRIPTION_MAX_CHARS} the "
                             f"specification allows"),
    ))
    lowered = description.lower()
    marker = next((m for m in TRIGGER_MARKERS if m in lowered), None)
    notes.append(GradeNote(
        "description.trigger", "recommended", marker is not None,
        f"the description states a trigger condition ({marker!r})"
        if marker is not None else
        "no stated trigger condition was found. this is a proxy: the grader "
        "looks for a closed list of phrasings such as 'use when' or 'triggers "
        "when', and a description that says when to use the skill some other "
        "way is marked down here in error",
    ))
    return notes, []


def _optional_field_rules(
    manifest: Dict[str, object],
) -> Tuple[List[GradeNote], List[Tuple[str, str]]]:
    notes: List[GradeNote] = []
    skipped: List[Tuple[str, str]] = []

    if "compatibility" in manifest:
        value = manifest.get("compatibility")
        text = value if isinstance(value, str) else ""
        ok = 1 <= len(text.strip()) <= COMPATIBILITY_MAX_CHARS
        notes.append(GradeNote(
            "compatibility.length", "required", ok,
            f"compatibility is {len(text.strip())} characters"
            + ("" if ok else f", outside the 1 to {COMPATIBILITY_MAX_CHARS} "
                             f"the specification allows"),
        ))
    else:
        skipped.append((
            "compatibility.length", "the front matter declares no compatibility",
        ))

    if "metadata" in manifest:
        value = manifest.get("metadata")
        ok = isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        )
        notes.append(GradeNote(
            "metadata.shape", "required", ok,
            "metadata is a map of string keys to string values" if ok else
            "metadata must be a map from string keys to string values",
        ))
    else:
        skipped.append(("metadata.shape", "the front matter declares no metadata"))

    return notes, skipped


def _body_rules(folder: Path, body: str) -> List[GradeNote]:
    notes: List[GradeNote] = []

    stripped = body.strip()
    notes.append(GradeNote(
        "body.present", "required", bool(stripped),
        f"the body is {len(body.splitlines())} lines" if stripped else
        "the body is empty, so an activated skill loads no instructions",
    ))

    line_count = len(body.splitlines())
    under = line_count < BODY_MAX_LINES
    notes.append(GradeNote(
        "body.lines", "recommended", under,
        f"the body is {line_count} lines"
        + ("" if under else f", over the {BODY_MAX_LINES} the specification "
                            f"recommends; move reference material into "
                            f"references/"),
    ))

    referenced = _referenced_paths(body)
    unresolved: List[str] = []
    for target in referenced:
        resolved = _within(folder, target)
        if resolved is None or not resolved.is_file():
            unresolved.append(target)
    notes.append(GradeNote(
        "references.resolve", "recommended", not unresolved,
        f"all {len(referenced)} bundled file references resolve"
        if referenced and not unresolved else
        "the body references no bundled files" if not referenced else
        f"{len(unresolved)} reference(s) name no file in this folder: "
        + ", ".join(unresolved[:5]),
    ))

    bundled = _bundled_files(folder)
    unmentioned = [relpath for relpath in bundled if relpath not in body]
    notes.append(GradeNote(
        "bundled.referenced", "recommended", not unmentioned,
        f"all {len(bundled)} bundled files are named in the body"
        if bundled and not unmentioned else
        "the folder bundles no files besides SKILL.md" if not bundled else
        f"{len(unmentioned)} bundled file(s) the body never names, so nothing "
        f"tells an agent when to load them: " + ", ".join(unmentioned[:5]),
    ))

    prose = _strip_fences(body)
    machine = sorted({match.group(0) for match in MACHINE_PATH_RE.finditer(prose)})
    notes.append(GradeNote(
        "paths.portable", "recommended", not machine,
        "the body names no absolute machine-specific path" if not machine else
        f"{len(machine)} absolute machine-specific path prefix(es) outside a "
        f"code fence, which cannot resolve for another user: "
        + ", ".join(machine[:5]),
    ))
    return notes


def grade_skill(folder: Path, manifest: Dict[str, object]) -> Grade:
    text = _read_text(folder / SKILL_FILE)
    if text is None:
        return Grade(
            grade=GRADE_UNGRADED,
            notes=(),
            not_graded=tuple(
                (rule_id, f"{folder.name} has no readable {SKILL_FILE}")
                for rule_id in RULE_SOURCES
            ),
        )

    split = split_skill_md(text)
    notes: List[GradeNote] = []
    skipped: List[Tuple[str, str]] = []

    notes.append(GradeNote(
        "frontmatter.present", "required", split is not None,
        "the file opens and closes a front matter fence" if split is not None
        else f"the file does not open and close a {FENCE} front matter fence",
    ))
    body = split[1] if split is not None else text

    for produced, not_run in (
        _name_rules(manifest, folder.name),
        _description_rules(manifest),
        _optional_field_rules(manifest),
    ):
        notes.extend(produced)
        skipped.extend(not_run)
    notes.extend(_body_rules(folder, body))

    order = list(RULE_SOURCES)
    notes.sort(key=lambda note: order.index(note.rule_id))
    grade = Grade(grade="", notes=tuple(notes), not_graded=tuple(skipped))
    return Grade(
        grade=letter_for(grade.required_failed, grade.recommended_failed),
        notes=grade.notes,
        not_graded=grade.not_graded,
    )


def grade_folder(folder: Path) -> Dict[str, object]:
    return grade_skill(folder, read_manifest(folder)).to_index()


def summary_table(document: Dict[str, object]) -> str:
    lines = [
        "## quality grades",
        "",
        "Advisory. A grade never blocks a publish. Every rule cites the "
        "published requirement it came from in `tools/index_builder/grade.py`.",
        "",
        "| skill | version | grade | failed |",
        "|---|---|---|---|",
    ]
    items = document.get("items")
    rows = 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        versions = item.get("versions")
        for version in versions if isinstance(versions, list) else []:
            if not isinstance(version, dict):
                continue
            rows += 1
            block = version.get("grade")
            if not isinstance(block, dict):
                lines.append(
                    f"| {item.get('id', '?')} | {version.get('v', '?')} | "
                    f"not graded | this build wrote no grade |"
                )
                continue
            failed = block.get("failed")
            names = ", ".join(
                str(entry.get("rule"))
                for entry in (failed if isinstance(failed, list) else [])
                if isinstance(entry, dict)
            )
            lines.append(
                f"| {item.get('id', '?')} | {version.get('v', '?')} | "
                f"{block.get('grade', '?')} | {names or 'nothing'} |"
            )
    if not rows:
        lines.append("| none | | | this build published no versions |")
    return "\n".join(lines) + "\n"
