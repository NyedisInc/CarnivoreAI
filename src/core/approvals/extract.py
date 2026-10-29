
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple

from src.core.attention.pane_markers import QUESTION_DIALOG_MARKERS
from src.core.timers.redact import redact

FAMILY_CLAUDE = "claude"
FAMILY_CODEX = "codex"

KIND_ASK = "ask_user_question"
KIND_PLAN = "plan_approval"
KIND_TRUST = "folder_trust"
KIND_PERMISSION = "permission"
KIND_CODEX = "codex_approval"
KIND_OTHER = "other"
KIND_UNREADABLE = "unreadable"  # a dialog is open

ROLE_OPTION = "option"
ROLE_OTHER = "other"
ROLE_CHAT = "chat"
ROLE_SUBMIT = "submit"

BODY_MAX_BYTES: int = 2048

_QUESTION_SCAN_LINES: int = 15
_DESCRIPTION_LINE = re.compile(r"^ {3,}\S")

DIALOG_SCROLLBACK_LINES: int = _QUESTION_SCAN_LINES + 5

_ASK_FOOTER: Pattern[str] = QUESTION_DIALOG_MARKERS[0]
_CLAUDE_FOOTER: Pattern[str] = re.compile(
    r"^\s*(?:Esc to cancel|ctrl[+-]g to edit in Vim)(?:\s*[·•|,-].*)?\s*$", re.M)
_CODEX_FOOTER: Pattern[str] = re.compile(
    r"^\s*Press enter to (?:confirm or esc to cancel|continue)\s*$", re.M | re.I)
_RULE: Pattern[str] = re.compile(r"^\s*[─━-]{10,}\s*$")
_ROW: Pattern[str] = re.compile(r"^(\s*)([❯›>])?\s*(?:(\d+)\.\s+)?(?:\[([^\]])\]\s+)?(\S.*?)\s*$")
_NUMBERED: Pattern[str] = re.compile(r"^\s*(?:[❯›>]\s*)?\d+\.\s+\S")
_KEY_HINT: Pattern[str] = re.compile(r"\s+\((?:[a-z]|esc)\)$")
_KEY_HINT_SQUASHED: Pattern[str] = re.compile(r"\((?:[a-z]|esc)\)$")
_QUOTE_BAR: Pattern[str] = re.compile(r"^\s*│\s?")
_WS: Pattern[str] = re.compile(r"\s+")
_AUTODENY_CLOCK: Pattern[str] = re.compile(r"(automaticallydenythisrequestin)\d+:\d{2}")
_ANSI: Pattern[str] = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_BORDER: Pattern[str] = re.compile("[\u2500-\u259f]")
_BODY_SCAN_LINES: int = 400
_FINGERPRINT_KEY_CHARS: int = 32
_FOOTER_WRAP_LINES: int = 3
_HEADER: Pattern[str] = re.compile(r"[☐☒✔←→]")
_PREVIEW_TOP: Pattern[str] = re.compile(r"\S\s{2,}([┌╭])[─━]")


@dataclass(frozen=True)
class Row:

    label: str
    role: str
    checked: Optional[bool] = None
    key: str = ""
    description: str = ""


@dataclass(frozen=True)
class Tab:

    title: str
    answered: bool


@dataclass(frozen=True)
class Dialog:

    family: str
    kind: str
    question: str
    body: str
    rows: Tuple[Row, ...]
    cursor: Optional[int]
    multi_select: bool
    fingerprint: str
    tabs: Tuple[Tab, ...] = ()
    question_index: Optional[int] = None
    startup_kind: Optional[str] = None

    @property
    def options(self) -> Tuple[str, ...]:
        return tuple(r.label for r in self.rows if r.role == ROLE_OPTION)

    @property
    def has_other(self) -> bool:
        return any(r.role == ROLE_OTHER for r in self.rows)

    def index_of(self, label: str, role: str = ROLE_OPTION) -> Optional[int]:
        want = squash(label)
        same = [i for i, r in enumerate(self.rows) if r.role == role and squash(r.label) == want]
        if same:
            return same[0]
        near = [i for i, r in enumerate(self.rows) if r.role == role and want and r.key.startswith(want)]
        return near[0] if len(near) == 1 else None

    def index_of_role(self, role: str) -> Optional[int]:
        for i, r in enumerate(self.rows):
            if r.role == role:
                return i
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family, "kind": self.kind, "question": self.question,
            "body": self.body, "options": list(self.options),
            "rows": [{"label": r.label, "role": r.role, "checked": r.checked, "description": r.description}
                     for r in self.rows],
            "cursor": self.cursor, "multi_select": self.multi_select,
            "has_other": self.has_other, "fingerprint": self.fingerprint,
            "question_index": self.question_index, "question_total": len(self.tabs) or None,
            "tabs": [{"title": t.title, "answered": t.answered} for t in self.tabs],
            "startup_kind": self.startup_kind,
        }


def squash(text: str) -> str:
    return _WS.sub("", text)


def normalize_body(lines: List[str]) -> str:
    return squash(_BORDER.sub("", _ANSI.sub("", "\n".join(lines))))


def fingerprint_for(family: str, kind: str, question: str, labels: List[str], body: str = "") -> str:
    parts = [family, kind, question, *labels]
    if body:
        parts.append("body:" + body)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _substance(lines: List[str], q_at: int, first: int, ask: bool) -> str:
    if ask:
        return ""
    top = q_at
    lo = max(0, q_at - _BODY_SCAN_LINES)
    for i in range(q_at - 1, lo - 1, -1):
        if _RULE.match(lines[i]):
            top = i + 1
            break
    return _AUTODENY_CLOCK.sub(r"\1", normalize_body([ln for ln in lines[top:first] if not _RULE.match(ln)]))


def _footer_index(lines: List[str], family: str) -> Tuple[Optional[int], Optional[str]]:
    pats = (("codex", _CODEX_FOOTER),) if family == FAMILY_CODEX else (
        ("ask", _ASK_FOOTER), ("claude", _CLAUDE_FOOTER))
    best: Tuple[Optional[int], Optional[str]] = (None, None)
    covered = 0
    for i in range(len(lines)):
        if i < covered:
            continue
        for tag, pat in pats:
            for span in range(1, _FOOTER_WRAP_LINES + 1):
                chunk = lines[i:i + span]
                if len(chunk) < span or not all(ln.strip() for ln in chunk):
                    break
                if pat.match(" ".join(ln.strip() for ln in chunk)):
                    if best[0] is None or i >= best[0]:
                        best, covered = (i, tag), i + span
                    break
            if covered > i:
                break
    return best


def _without_preview(lines: List[str]) -> List[str]:
    col = next((m.start(1) for m in (_PREVIEW_TOP.search(ln) for ln in lines) if m), None)
    return lines if col is None else [ln[:col].rstrip() for ln in lines]


def _parse_rows(lines: List[str], first: int, end: int) -> Tuple[List[Row], Optional[int]]:
    built: List[Tuple[str, str, Optional[bool], List[str]]] = []
    cursor: Optional[int] = None
    label_col = 0
    number_col = 0
    last_number = 0
    for line in _without_preview(lines[first:end]):
        if not line.strip() or _RULE.match(line):
            continue
        m = _ROW.match(line)
        if not m:
            continue
        indent, glyph, number, box, text = m.groups()
        text_col = line.index(text, len(indent))
        if number is not None and built and (int(number) != last_number + 1 or m.start(3) >= label_col):
            number, text = None, line.strip()
            text_col = label_col
        if number is None and text_col >= label_col and built:
            built[-1][3].append(text)
            continue
        if number is None and number_col < text_col < label_col and built and built[-1][2] is None:
            label, role, checked, parts = built[-1]
            built[-1] = (f"{label} {_KEY_HINT.sub('', text)}", role, checked, [f"{parts[0]} {text}", *parts[1:]])
            continue
        if number is not None:
            label_col, number_col = text_col, m.start(3)
            last_number = int(number)
        label = _KEY_HINT.sub("", text)
        low = label.lower()
        if low.startswith("chat about this"):
            role = ROLE_CHAT
        elif number is None:
            role = ROLE_SUBMIT
        elif low.startswith("type something"):
            role = ROLE_OTHER
        else:
            role = ROLE_OPTION
        checked = None if box is None else box.strip() != ""
        if glyph:
            cursor = len(built)
        built.append((label, role, checked, [text]))
    rows = [Row(label, role, checked, _KEY_HINT_SQUASHED.sub("", squash("".join(parts))), " ".join(parts[1:]))
            for label, role, checked, parts in built]
    return rows, cursor


def _question(lines: List[str], first: int, ask: bool) -> Tuple[str, int]:
    lo = max(0, first - _QUESTION_SCAN_LINES)
    if not ask:
        for i in range(first - 1, lo - 1, -1):
            if lines[i].rstrip().endswith("?"):
                indent, top = len(lines[i]) - len(lines[i].lstrip()), i
                while (top - 1 >= lo and lines[top - 1].strip() and not _RULE.match(lines[top - 1])
                       and not _QUOTE_BAR.match(lines[top - 1])
                       and len(lines[top - 1]) - len(lines[top - 1].lstrip()) == indent):
                    top -= 1
                return " ".join(ln.strip() for ln in lines[top:i + 1]), top
    block: List[str] = []
    i = first - 1
    while i >= lo and not lines[i].strip():
        i -= 1
    while i >= lo and lines[i].strip() and not _RULE.match(lines[i]) and not _HEADER.search(lines[i]):
        block.insert(0, _QUOTE_BAR.sub("", lines[i]).strip())
        i -= 1
    return " ".join(block), i + 1


_TAB_STRIP: Pattern[str] = re.compile(r"^\s*←\s.*→\s*$")
_TAB: Pattern[str] = re.compile(r"([☐☒✔☑✓])\s+(\S.*?)\s*$")
_TAB_SUBMIT: str = "submit"
_ANSWERED_GLYPHS: str = "☒☑✓✔"


def _tab_strip(lines: List[str], q_at: int, ticked: bool = False) -> Tuple[Tuple[Tab, ...], Optional[int]]:
    at = next((i for i in range(q_at - 1, max(-1, q_at - 4), -1) if lines[i].strip()), None)
    if at is None:
        return (), None
    strip = lines[at]
    top = at
    while not strip.lstrip().startswith("←") and top > 0 and at - top < 2 and lines[top - 1].strip():
        top -= 1
        strip = f"{lines[top].rstrip()}  {strip.lstrip()}"
    if not _TAB_STRIP.match(strip):
        return (), None
    tabs: List[Tab] = []
    for chunk in re.split(r"\s{2,}", strip.strip().strip("←→").strip()):
        m = _TAB.match(chunk.strip())
        if m and m.group(2).strip().lower() != _TAB_SUBMIT:
            tabs.append(Tab(m.group(2).strip(), m.group(1) in _ANSWERED_GLYPHS))
    if not tabs:
        return (), None
    first_open = next((i + 1 for i, t in enumerate(tabs) if not t.answered), len(tabs) + 1)
    return tuple(tabs), max(1, min(len(tabs), first_open - 1 if ticked else first_open))


def _classify(family: str, tag: str, question: str, keys: List[str]) -> str:
    q = squash(question).lower()
    joined = "".join(keys).lower()
    if "trust" in q:
        return KIND_TRUST
    if family == FAMILY_CODEX:
        return KIND_CODEX
    if tag == "ask":
        return KIND_ASK
    if "readytocode" in q or "keepplanning" in joined or "writtenupaplan" in q:
        return KIND_PLAN
    return KIND_PERMISSION if keys else KIND_OTHER


_TRUST_FOOTER: Pattern[str] = re.compile(r"^\s*Enter to confirm\s*[·•|,.-]\s*Esc to [a-z][a-z ]*$")
_TRUST_QUESTION: str = "Quick safety check"
_TRUST_LABELS = frozenset({"No, exit", "Yes, I trust this folder"})
_IMPORTS_QUESTION: str = "Allow external CLAUDE.md"
_IMPORTS_LABELS = frozenset({"No, disable external imports", "Yes, allow external imports"})


_CHROME_QUESTION: str = "Claude in Chrome extension detected"
CHROME_DECLINE_LABEL: str = "No, keep browser tools off"
CHROME_ACCEPT_LABEL: str = "Yes, use my browser"
_CHROME_LABELS = frozenset({CHROME_DECLINE_LABEL, CHROME_ACCEPT_LABEL})

DEV_CHANNELS_TITLE: str = "WARNING: Loading development channels"
DEV_CHANNELS_ACCEPT: str = "I am using this for local development"
_DEV_CHANNELS_LABELS = frozenset({DEV_CHANNELS_ACCEPT, "Exit"})


def _claude_footer_choice(lines: List[str], marker: str, labels: frozenset, kind: str,
                          through_rows: bool = False) -> Optional[Dialog]:
    row = re.compile(r"^\s*(?:[❯›>]\s*)?(?:\d+\.\s+)?(?P<label>" + "|".join(re.escape(x) for x in sorted(labels)) + r")\s*$")
    foot = startup_footer_index(lines)
    q_at = next((i for i, ln in enumerate(lines) if marker in ln), None)
    if foot is None or q_at is None or q_at >= foot:
        return None
    hits = [(i, row.match(lines[i])) for i in range(q_at, foot)]
    hits = [(i, m) for i, m in hits if m]
    if {m.group("label") for _, m in hits} != labels:
        return None
    first = hits[0][0]
    end = q_at
    while end < first and lines[end].strip():
        end += 1
    question = " ".join(ln.strip() for ln in lines[q_at:end])
    rows = [Row(m.group("label"), ROLE_OPTION, None, squash(m.group("label"))) for _, m in hits]
    cursor = next((n for n, (i, _) in enumerate(hits) if lines[i].lstrip().startswith(("❯", "›", ">"))), None)
    body_from = q_at if through_rows else max(0, q_at - _QUESTION_SCAN_LINES)
    body_lines = [ln.rstrip() for ln in lines[body_from:foot] if ln.strip()]
    body = redact("\n".join(body_lines)).encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
    substance = normalize_body(lines[max(0, q_at - _QUESTION_SCAN_LINES):first if through_rows else q_at])
    return Dialog(
        family=FAMILY_CLAUDE, kind=kind, question=redact(question), body=body, rows=tuple(rows), cursor=cursor,
        multi_select=False,
        fingerprint=fingerprint_for(FAMILY_CLAUDE, kind, squash(question), [r.key for r in rows], substance),
    )


def _claude_trust(lines: List[str]) -> Optional[Dialog]:
    return _claude_footer_choice(lines, _TRUST_QUESTION, _TRUST_LABELS, KIND_TRUST)


def is_chrome_prompt(dialog: Optional[Dialog]) -> bool:
    return (dialog is not None and dialog.family == FAMILY_CLAUDE and dialog.kind == KIND_OTHER and _CHROME_QUESTION in dialog.question
            and len(dialog.rows) == len(_CHROME_LABELS) and {r.label for r in dialog.rows if r.role == ROLE_OPTION} == _CHROME_LABELS)


def enables_browser_tools(dialog: Dialog) -> bool:
    return (dialog.kind == KIND_OTHER and _CHROME_QUESTION in dialog.question
            and any(r.role == ROLE_OPTION and r.label == CHROME_ACCEPT_LABEL for r in dialog.rows))


def startup_footer_index(lines: List[str]) -> Optional[int]:
    return next((i for i in range(len(lines) - 1, -1, -1) if _TRUST_FOOTER.match(lines[i])), None)


def _claude_footer_dialog(lines: List[str]) -> Optional[Dialog]:
    from src.core.approvals import startup_extract

    exact = (_claude_trust(lines) or _claude_footer_choice(lines, _IMPORTS_QUESTION, _IMPORTS_LABELS, KIND_OTHER)
             or _claude_footer_choice(lines, _CHROME_QUESTION, _CHROME_LABELS, KIND_OTHER)
             or _claude_footer_choice(lines, DEV_CHANNELS_TITLE, _DEV_CHANNELS_LABELS, KIND_OTHER, through_rows=True))
    if exact is not None:
        return replace(exact, startup_kind=startup_extract.startup_kind_of(lines))
    return startup_extract.decode_startup_choice(lines)


def _row_number(line: str) -> int:
    return int(re.search(r"\d+", line).group())


def _number_column(line: str) -> int:
    return re.search(r"\d", line).start()


def _number_end_column(line: str) -> int:
    return re.search(r"\d+", line).end()


def extract_dialog(text: str, family: Optional[str]) -> Optional[Dialog]:
    fam = FAMILY_CODEX if family == FAMILY_CODEX else FAMILY_CLAUDE
    lines = (text or "").splitlines()
    foot, tag = _footer_index(lines, fam)
    if foot is None or tag is None:
        return _claude_footer_dialog(lines) if fam == FAMILY_CLAUDE else None
    last = next((i for i in range(foot - 1, -1, -1) if _NUMBERED.match(lines[i])), None)
    if last is None:
        return _claude_footer_dialog(lines) if fam == FAMILY_CLAUDE else None
    first, gap = last, 0
    row_col, row_end = _number_column(lines[last]), _number_end_column(lines[last])
    for i in range(last - 1, -1, -1):
        if _NUMBERED.match(lines[i]):
            if _number_column(lines[i]) > row_col and _number_end_column(lines[i]) > row_end:
                continue
            if _row_number(lines[i]) < _row_number(lines[first]):
                first, gap = i, 0
        elif _DESCRIPTION_LINE.match(lines[i]):
            continue
        else:
            gap += 1
            if gap > 6:
                break
    rows, cursor = _parse_rows(lines, first, foot)
    if not rows:
        return None
    question, q_at = _question(lines, first, tag == "ask")
    top = q_at
    while top > 0 and not _RULE.match(lines[top - 1]) and q_at - top < _QUESTION_SCAN_LINES:
        top -= 1
    keys = [r.key for r in rows]
    kind = _classify(fam, tag, question, keys)
    tabs, qidx = _tab_strip(lines, q_at, any(r.checked for r in rows)) if tag == "ask" else ((), None)
    body_lines = [ln.rstrip() for ln in lines[top:foot] if ln.strip() and not _RULE.match(ln)]
    body = redact("\n".join(body_lines)).encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
    step = f"step:{qidx}/{len(tabs)}" if qidx else ""
    return Dialog(
        family=fam, kind=kind, question=redact(question), body=body, rows=tuple(rows), cursor=cursor,
        multi_select=any(r.checked is not None for r in rows),
        fingerprint=fingerprint_for(fam, kind, squash(question), [k[:_FINGERPRINT_KEY_CHARS] for k in keys],
                                    _substance(lines, q_at, first, tag == "ask") or step),
        tabs=tabs, question_index=qidx,
    )


def unreadable_dialog(family: Optional[str]) -> Dialog:
    fam = FAMILY_CODEX if family == FAMILY_CODEX else FAMILY_CLAUDE
    return Dialog(family=fam, kind=KIND_UNREADABLE, question="", body="", rows=(), cursor=None,
                  multi_select=False, fingerprint=fingerprint_for(fam, KIND_UNREADABLE, "", []))


def extract_dialog_scrolled(viewport: str, family: Optional[str],
                            read_scrolled: Callable[[], Optional[str]]) -> Optional[Dialog]:
    dialog = extract_dialog(viewport, family)
    if dialog is None:
        return None
    scrolled = read_scrolled()
    wide = extract_dialog(scrolled, family) if scrolled is not None else None
    return wide if wide is not None else dialog


REVIEW_QUESTION = "Ready to submit your answers?"
REVIEW_CONFIRM_LABEL = "Submit answers"


def extract_review(text: str) -> Optional[Dialog]:
    lines = (text or "").splitlines()
    at = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == REVIEW_QUESTION), None)
    if at is None:
        return None
    rows, cursor = _parse_rows(lines, at + 1, len(lines))
    if not rows:
        return None
    review = Dialog(
        family=FAMILY_CLAUDE, kind=KIND_ASK, question=REVIEW_QUESTION, body=REVIEW_QUESTION,
        rows=tuple(rows), cursor=cursor, multi_select=False,
        fingerprint=fingerprint_for(FAMILY_CLAUDE, KIND_ASK, squash(REVIEW_QUESTION), [r.key[:_FINGERPRINT_KEY_CHARS] for r in rows]))
    return review if review.index_of(REVIEW_CONFIRM_LABEL) is not None else None
